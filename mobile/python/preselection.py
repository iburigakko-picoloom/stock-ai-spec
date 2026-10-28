"""Versioned, received-before-cutoff TOPIX500 lists; opt-in during acceptance."""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import membership
from .storage import connect

RULE = "jquants-scalecat-topix500-v1"
SCALES = frozenset(("TOPIX Core30", "TOPIX Large70", "TOPIX Mid400"))
LEGACY = "legacy300"
MODE = "topix500-preview"
JST = ZoneInfo("Asia/Tokyo")


def initialize(path):
    with connect(path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS mobile_universe_policy("
            "id INTEGER PRIMARY KEY CHECK(id=1),mode TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS mobile_preselection_lists("
            "list_hash TEXT PRIMARY KEY,effective_at TEXT NOT NULL,"
            "payload BLOB NOT NULL)"
        )


def policy(path, mode=None):
    initialize(path)
    with connect(path) as db:
        if mode is not None:
            if mode not in (LEGACY, MODE):
                raise ValueError("Unknown universe policy")
            db.execute("INSERT OR REPLACE INTO mobile_universe_policy VALUES(1,?)", (mode,))
        row = db.execute("SELECT mode FROM mobile_universe_policy WHERE id=1").fetchone()
    return {
        "mode": row[0] if row else LEGACY,
        "experimental": row is not None and row[0] == MODE,
        "model_adoption": "HOLD",
    }


def _encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()


def _checked(row):
    decoder = zlib.decompressobj()
    content = decoder.decompress(row[2], 4 * 1024 * 1024 + 1)
    if len(content) > 4 * 1024 * 1024 or not decoder.eof or decoder.unused_data:
        raise ValueError("Invalid preselection list block")
    if hashlib.sha256(content).hexdigest() != row[0]:
        raise ValueError("Preselection list changed")
    value = json.loads(content)
    if value["effective_at"] != row[1] or value["rule_version"] != RULE:
        raise ValueError("Preselection rule/effective time changed")
    return {**value, "list_hash": row[0]}


def _liquidity_window(path, as_of, *, include_today=False):
    """Freeze constraint evidence, without using liquidity to narrow membership."""
    from .universe import _observations, reference_end_date

    last = (reference_end_date(path, as_of) if include_today
            else as_of.astimezone(JST).date() - timedelta(days=1))
    first = last - timedelta(days=89)
    calendar = {}
    for _, rows, _ in _observations(path, "trading_calendar", first, last, as_of):
        for row in rows:
            day = date.fromisoformat(row["Date"])
            if first <= day <= last:
                calendar[day] = str(row["HolDiv"])
    sessions = sorted(day for day, division in calendar.items() if division in ("1", "2"))
    if len(sessions) < 20:
        return [], []
    window = [str(day) for day in sessions[-20:]]
    if any(
        sessions[-20] + timedelta(days=i) not in calendar
        for i in range((last - sessions[-20]).days + 1)
    ):
        return [], []
    with connect(path) as db:
        rows = db.execute(
            "WITH versions AS (SELECT day,sequence,received_at,payload_hash,ROW_NUMBER() OVER("
            "PARTITION BY day ORDER BY received_at DESC,sequence DESC) n FROM market_batches "
            "WHERE dataset='daily_prices' AND day>=? AND day<=? AND received_at<=?) "
            "SELECT day,sequence,received_at,payload_hash FROM versions WHERE n=1 ORDER BY day",
            (window[0], window[-1], as_of.astimezone(UTC).isoformat(timespec="microseconds")),
        ).fetchall()
    return window, [
        {
            "dataset": "daily_prices",
            "date": day,
            "observation_id": sequence,
            "received_at": received,
            "payload_hash": digest,
        }
        for day, sequence, received, digest in rows
        if day in window
    ]


def select(path, as_of: datetime, holding_symbols=()):
    if as_of.tzinfo is None:
        raise ValueError("Aware preselection cutoff required")
    held = sorted(set(holding_symbols))
    if any(not isinstance(x, str) or not re.fullmatch(r"[0-9A-Z]{4,5}", x) for x in held):
        raise ValueError("Invalid holding symbol")
    initialize(path)
    stamp = as_of.astimezone(UTC).isoformat(timespec="microseconds")
    with connect(path) as db:
        row = db.execute(
            "SELECT list_hash,effective_at,payload FROM mobile_preselection_lists "
            # Several received corrections may share one frozen cutoff. Hash
            # order cannot identify the last immutable revision we recorded.
            "WHERE effective_at<=? ORDER BY effective_at DESC,rowid DESC LIMIT 1",
            (stamp,),
        ).fetchone()
    previous = None if row is None else _checked(row)
    current = membership.snapshot(path, as_of)
    result = {
        "as_of": as_of.isoformat(),
        "policy": RULE,
        "new_candidates": [],
        "decision_symbols": held,
        "held_only": held,
        "excluded": [],
        "sources": [],
        "blocking_reasons": [],
        "research_only": True,
        "membership_verified": False,
        "membership_mode": "preselected",
        "fallback": False,
    }
    if current is not None and not current["is_business_day"]:
        result["blocking_reasons"] = ["non_business_day"]
        return result
    if current is None:
        # No inference from a stale list that a market day or its composition is
        # still valid. An explicit stop is safer than resurrecting delisted shares.
        result["blocking_reasons"] = ["current_membership_missing_no_verified_fallback"]
        return result
    source = {
        "dataset": "current_membership",
        "date": current["date"],
        "received_at": current["received_at"],
        "payload_hash": current["payload_hash"],
        "observation_id": current["acquisitionId"],
        "provider": "J-Quants",
        "source_endpoint": "/v2/equities/master",
    }
    selected, unsupported, seen, supported = [], [], set(), set()
    for item in current["datasets"]["security_master"]:
        code = item["Code"]
        if code in seen:
            raise ValueError("Duplicate master code")
        seen.add(code)
        domestic = (
            re.fullmatch(r"[0-9A-Z]{4}0", code) is not None
            and item.get("ProdCat") == "011"
            and item["Mkt"] in ("0111", "0112", "0113")
        )
        symbol = code[:-1] if code.endswith("0") else code
        if domestic:
            supported.add(symbol)
        if item.get("ScaleCat") in SCALES:
            if not domestic:
                unsupported.append(
                    {
                        "symbol": symbol,
                        "reason": "UNSUPPORTED_DOMESTIC_COMMON_SHARE",
                        "scale_category": item["ScaleCat"],
                    }
                )
            else:
                selected.append(
                    {
                        "symbol": symbol,
                        "company_name": item["CoName"],
                        "scale_category": item["ScaleCat"],
                        "reason": "topix500_scale_category",
                    }
                )
    if not selected:
        result["blocking_reasons"] = ["topix500_scale_categories_unavailable"]
        return result
    selected.sort(key=lambda x: x["symbol"])
    unsupported.sort(key=lambda x: x["symbol"])
    members = {x["symbol"] for x in selected}
    old = set() if previous is None else {x["symbol"] for x in previous["members"]}
    old_members = None if previous is None else previous["members"]
    monthly = previous is None or previous["review_month"] != as_of.astimezone(JST).strftime(
        "%Y-%m"
    )
    changed = old_members != selected or (
        previous is not None and previous["unsupported"] != unsupported
    )
    if monthly or changed:
        value = {
            "rule_version": RULE,
            "members": selected,
            "unsupported": unsupported,
            "source": source,
            "effective_at": stamp,
            "review_month": as_of.astimezone(JST).strftime("%Y-%m"),
            "review_reason": "monthly" if monthly else "observed_master_change",
            "previous_list_hash": None if previous is None else previous["list_hash"],
            "diff": {"added": sorted(members - old), "removed": sorted(old - members)},
            "fallback_policy": "stop_without_current_received_membership",
            "historical_membership_reconstructed": False,
        }
        old_values = {} if previous is None else {x["symbol"]: x for x in previous["members"]}
        value["diff"]["changed"] = [
            {"before": old_values[item["symbol"]], "after": item}
            for item in selected
            if item["symbol"] in old_values and old_values[item["symbol"]] != item
        ]
        content = _encoded(value)
        digest = hashlib.sha256(content).hexdigest()
        with connect(path) as db:
            db.execute(
                "INSERT OR IGNORE INTO mobile_preselection_lists VALUES(?,?,?)",
                (digest, stamp, zlib.compress(content)),
            )
        previous = {**value, "list_hash": digest}
    # The frozen monthly list is supplemented by today's independently verified
    # source, even on a day when its constituent names have not changed.
    window, price_sources = _liquidity_window(path, as_of)
    result.update(
        new_candidates=selected,
        decision_symbols=sorted(members | set(held)),
        held_only=sorted(set(held) - members),
        excluded=unsupported
        + [
            {"symbol": x, "reason": "HELD_INSTRUMENT_UNSUPPORTED_OR_NOT_LISTED"}
            for x in held
            if x not in supported
        ],
        sources=[source, *price_sources],
        membership_verified=True,
        membership_source_date=current["date"],
        membership_received_at=current["received_at"],
        membership_acquisition_id=current["acquisitionId"],
        latest_source_date=window[-1] if window else None,
        window_dates=window,
        preselection=previous,
        holding_reasons=[{"symbol": x, "reason": "holding"} for x in held],
    )
    if set(held) - supported:
        result["blocking_reasons"] = ["held_instrument_unsupported_or_not_listed"]
    return result

"""Auditable mobile candidate selection; broad feature contexts remain unchanged."""

from __future__ import annotations

import json
import re
import sqlite3
import zlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_ai.data.normalize import canonical_payload_hash

_CODE = re.compile(r"[0-9A-Z]{4}[0-9]")
_MARKETS = frozenset(("0111", "0112", "0113"))


def amount(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("Invalid monetary value")
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Invalid monetary value") from error
    if not number.is_finite() or number < 0:
        raise ValueError("Invalid monetary value")
    return number


def validate_valuations(rows, day):
    if len(rows) > 50000:
        raise ValueError("Valuation size limit")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("Date") != str(day):
            raise ValueError("Valuation source date mismatch")
        code = row.get("Code")
        if not isinstance(code, str) or not _CODE.fullmatch(code) or code in seen:
            raise ValueError("Invalid/duplicate valuation code")
        seen.add(code)
        if "MktCap" not in row:
            raise ValueError("Missing valuation field")
        amount(row["MktCap"])


def _observations(path, dataset, first, last, cutoff):
    valuation = dataset == "valuations"
    table = "market_valuations" if valuation else "market_batches"
    query = (
        "WITH versions AS (SELECT sequence,day,received_at,payload_hash,raw,"
        "ROW_NUMBER() OVER(PARTITION BY day ORDER BY received_at DESC,sequence DESC) n "
        f"FROM {table} WHERE day>=? AND day<=? AND received_at<=?"
    )
    values = [str(first), str(last), cutoff.astimezone(UTC).isoformat(timespec="microseconds")]
    if not valuation:
        query += " AND dataset=?"
        values.append(dataset)
    query += (
        ") SELECT sequence,day,received_at,payload_hash,raw FROM versions WHERE n=1 "
        "ORDER BY received_at,sequence"
    )
    with sqlite3.connect(path) as db:
        for sequence, day, received, digest, raw in db.execute(query, values):
            records = json.loads(zlib.decompress(raw))
            if canonical_payload_hash(tuple(records)) != digest:
                raise ValueError("Stored candidate source changed")
            yield day, records, {"dataset": dataset, "date": day, "observation_id": sequence,
                                 "received_at": received, "payload_hash": digest}


def select(path: Path, as_of: datetime, holding_symbols=()) -> dict:
    if as_of.tzinfo is None:
        raise ValueError("Aware candidate cutoff required")
    held = sorted(set(holding_symbols))
    if any(not isinstance(x, str) or not re.fullmatch(r"[0-9A-Z]{4}", x) for x in held):
        raise ValueError("Invalid holding symbol")
    result = {"as_of": as_of.isoformat(), "policy": "cap30bn-adv20-top300-v1",
              "latest_source_date": None, "window_dates": [], "new_candidates": [],
              "decision_symbols": held, "held_only": held, "excluded": [], "sources": [],
              "blocking_reasons": [], "research_only": True}
    last = as_of.astimezone(ZoneInfo("Asia/Tokyo")).date() - timedelta(days=1)
    first = last - timedelta(days=89)
    calendar = {}
    sources = result["sources"]
    for _, rows, source in _observations(path, "trading_calendar", first, last, as_of):
        sources.append(source)
        for row in rows:
            day = date.fromisoformat(row["Date"])
            if first <= day <= last:
                calendar[day] = str(row["HolDiv"])
    sessions = sorted(day for day, division in calendar.items() if division in ("1", "2"))
    if len(sessions) < 20:
        result["blocking_reasons"] = ["twenty_sessions_required"]
        return result
    window = sessions[-20:]
    if any(window[0] + timedelta(days=i) not in calendar
           for i in range((last - window[0]).days + 1)):
        result["blocking_reasons"] = ["calendar_coverage_gap"]
        return result
    end = window[-1]
    result.update(latest_source_date=str(end), window_dates=[str(x) for x in window])
    master_batches = list(_observations(path, "security_master", end, end, as_of))
    valuation_batches = list(_observations(path, "valuations", end, end, as_of))
    if not master_batches or not valuation_batches:
        result["blocking_reasons"] = ["latest_master_or_valuation_missing"]
        return result
    _, master, master_source = master_batches[0]
    _, valuations, valuation_source = valuation_batches[0]
    sources.extend((master_source, valuation_source))
    caps = {row["Code"]: amount(row["MktCap"]) for row in valuations}
    totals, counts, missing, dates = {}, {}, set(), set()
    for day, rows, source in _observations(path, "daily_prices", window[0], end, as_of):
        if date.fromisoformat(day) not in window:
            continue
        sources.append(source)
        dates.add(day)
        for row in rows:
            code = row["Code"]
            value = amount(row["Va"])
            if value is None:
                missing.add(code)
            else:
                totals[code] = totals.get(code, Decimal(0)) + value
                counts[code] = counts.get(code, 0) + 1
    if dates != set(result["window_dates"]):
        result["blocking_reasons"] = ["price_session_missing"]
        return result
    ranked = []
    for row in master:
        code = row["Code"]
        if not code.endswith("0") or row["Mkt"] not in _MARKETS:
            continue
        cap = caps.get(code)
        reason = None
        if cap is None:
            reason = "market_cap_missing"
        elif cap < 30000:  # Provider unit: million JPY; JPY 30 billion = 30,000.
            reason = "below_market_cap"
        elif code in missing or counts.get(code) != 20:
            reason = "twenty_valid_trading_values_required"
        if reason:
            result["excluded"].append({"symbol": code[:-1], "reason": reason})
        else:
            ranked.append((totals[code], code[:-1], row, cap))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    result["new_candidates"] = [
        {"symbol": symbol, "company_name": row["CoName"], "market_cap_yen": str(cap * 1000000),
         "mean_trading_value_yen": str(total / 20), "rank": index + 1}
        for index, (total, symbol, row, cap) in enumerate(ranked[:300])
    ]
    selected = {row["symbol"] for row in result["new_candidates"]}
    result["held_only"] = sorted(set(held) - selected)
    result["decision_symbols"] = sorted(set(held) | selected)
    return result

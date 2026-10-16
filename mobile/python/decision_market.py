"""Frozen previous-session prices and twenty-session liquidity for share proposals."""

from __future__ import annotations

import json
import zlib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from stock_ai.data.normalize import canonical_payload_hash
from stock_ai.domain import MarketSnapshot, Security
from stock_ai.operations.daily import content_id
from stock_ai.operations.personal import PersonalMarket

from . import market, membership, universe
from .storage import connect


class EvidenceUnavailable(ValueError):
    pass


def _rows(path, source, cutoff):
    dataset = source["dataset"]
    table = "market_valuations" if dataset == "valuations" else "market_batches"
    with connect(path) as db:
        row = db.execute(
            f"SELECT day,received_at,payload_hash,raw FROM {table} WHERE sequence=?"
            + (" AND dataset=?" if dataset != "valuations" else ""),
            (source["observation_id"], dataset) if dataset != "valuations"
            else (source["observation_id"],),
        ).fetchone()
    if row is None or tuple(row[:3]) != (
        source["date"], source["received_at"], source["payload_hash"],
    ) or market.receipt_time(row[1]) > cutoff:
        raise EvidenceUnavailable("FROZEN_MARKET_SOURCE_MISSING")
    decoder = zlib.decompressobj()
    try:
        decoded = decoder.decompress(row[3], 64 * 1024 * 1024 + 1)
    except zlib.error as error:
        raise EvidenceUnavailable("FROZEN_MARKET_SOURCE_INVALID") from error
    if (len(decoded) > 64 * 1024 * 1024 or decoder.unconsumed_tail
            or decoder.unused_data or not decoder.eof):
        raise EvidenceUnavailable("FROZEN_MARKET_SOURCE_INVALID")
    rows = json.loads(decoded)
    if canonical_payload_hash(tuple(rows)) != row[2]:
        raise EvidenceUnavailable("FROZEN_MARKET_SOURCE_CHANGED")
    return rows


def prepare(path: Path, forecast_run: dict) -> dict:
    snapshot, scope = forecast_run["snapshot"], forecast_run["scope"]
    if snapshot is None or forecast_run["phase"] != "published":
        raise EvidenceUnavailable("NUMERICAL_FORECAST_INCOMPLETE")
    cutoff = datetime.fromisoformat(scope["as_of"])
    selected = scope["universe"]
    if not selected["membership_verified"]:
        raise EvidenceUnavailable("CURRENT_MEMBERSHIP_UNVERIFIED")
    member = membership.reference(path, selected["membership_acquisition_id"], cutoff)
    if (not member["is_business_day"] or member["received_at"] != selected["membership_received_at"]
            or member["date"] != selected["membership_source_date"]):
        raise EvidenceUnavailable("FROZEN_MEMBERSHIP_CHANGED")
    window = selected["window_dates"]
    if (len(window) != 20 or window != sorted(set(window))
            or window[-1] != selected["latest_source_date"]
            or date.fromisoformat(window[-1]) >= cutoff.date()):
        raise EvidenceUnavailable("FROZEN_PRICE_WINDOW_INVALID")
    symbols = sorted(x["symbol"] for x in snapshot["predictions"])
    sources = [x for x in selected["sources"] if x["dataset"] == "daily_prices"]
    if len(sources) != 20 or {x["date"] for x in sources} != set(window):
        raise EvidenceUnavailable("TWENTY_LIQUIDITY_SESSIONS_REQUIRED")
    totals = dict.fromkeys(symbols, Decimal(0))
    prices, used = {}, []
    for source in sorted(sources, key=lambda x: x["date"]):
        rows = _rows(path, source, cutoff)
        by_symbol = {x["Code"][:-1]: x for x in rows if x["Code"].endswith("0")}
        for symbol in symbols:
            row = by_symbol.get(symbol)
            if row is None or universe.amount(row["Va"]) is None:
                raise EvidenceUnavailable("HELD_OR_CANDIDATE_LIQUIDITY_MISSING:" + symbol)
            totals[symbol] += universe.amount(row["Va"])
            if source["date"] == window[-1]:
                price = universe.amount(row["C"])
                if price is None or price <= 0:
                    raise EvidenceUnavailable("REFERENCE_PRICE_MISSING:" + symbol)
                prices[symbol] = price
        used.append(source)
    if any(value <= 0 for value in totals.values()):
        raise EvidenceUnavailable("POSITIVE_LIQUIDITY_REQUIRED")
    master = {x["Code"][:-1]: x for x in member["datasets"]["security_master"]
              if x["Code"].endswith("0")}
    fallback = sorted(set(symbols) - set(master))
    metadata_sources = []
    if fallback:
        references = forecast_run["data_proof"].get("security_master_sources")
        if not references:
            raise EvidenceUnavailable("FROZEN_HELD_METADATA_UNAVAILABLE")
        missing = set(fallback)
        for source in sorted(references, key=lambda x: x["date"], reverse=True):
            if source["dataset"] != "security_master" or source["date"] > cutoff.date().isoformat():
                raise EvidenceUnavailable("FROZEN_HELD_METADATA_INVALID")
            rows = _rows(path, source, cutoff)
            found = {row["Code"][:-1]: row for row in rows
                     if row["Code"].endswith("0") and row["Code"][:-1] in missing}
            if found:
                master.update(found)
                missing -= found.keys()
                metadata_sources.append(source)
            if not missing:
                break
        if missing:
            raise EvidenceUnavailable("HELD_SECURITY_METADATA_MISSING:" + sorted(missing)[0])
    securities = tuple(Security(symbol=symbol, company_name=master[symbol]["CoName"],
                                sector=master[symbol]["S33"], market_segment=master[symbol]["Mkt"],
                                lot_size=100) for symbol in symbols)
    received = max([market.receipt_time(member["received_at"]),
                    *(market.receipt_time(x["received_at"]) for x in used + metadata_sources)])
    proof = {"schema_version": "mobile-decision-market-v1", "as_of": cutoff.isoformat(),
             "reference_price_date": window[-1], "price_semantics": "previous_session_raw_close",
             "lot_semantics": "explicit_100_share_research_policy", "sources": used,
             "membership_acquisition_id": member["acquisitionId"],
             "membership_sha256": member["payload_hash"],
             "historical_metadata_symbols": fallback,
             "historical_metadata_sources": metadata_sources}
    evidence = PersonalMarket(
        market=MarketSnapshot(snapshot_id=content_id(proof), as_of=cutoff, available_at=received,
                              source="jquants-v2-previous-close-research-v1", prices=prices),
        observed_at=received, securities=securities,
        average_daily_trading_values=tuple((symbol, totals[symbol] / 20) for symbol in symbols),
    )
    return {"evidence": evidence.model_dump(mode="json"), "proof": proof}

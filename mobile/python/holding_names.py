"""Resolve held symbols from already received security-master observations."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import market, membership, universe
from .storage import connect


def read(path: Path, store, now: datetime) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Aware observation time required")
    portfolio = store.latest_portfolio()
    if portfolio is None:
        return {"portfolioId": None, "names": {}, "prices": {}, "priceDate": None}
    missing = {position.symbol for position in portfolio.positions}
    held = set(missing)
    names = {}
    if not missing:
        return {"portfolioId": portfolio.portfolio_id, "names": names,
                "prices": {}, "priceDate": None}
    day = now.astimezone(ZoneInfo("Asia/Tokyo")).date().isoformat()
    cutoff = now.astimezone(UTC).isoformat(timespec="microseconds")
    with connect(path) as db:
        observed = db.execute(
            "SELECT acquisition_id,payload_hash,raw,received_at,day FROM mobile_membership "
            "WHERE day<=? AND received_at<=? ORDER BY day DESC,received_at DESC,sequence DESC "
            "LIMIT 5", (day, cutoff)
        ).fetchall()
        master = db.execute(
            "SELECT day,received_at FROM market_batches WHERE dataset='security_master' "
            "AND day<=? AND received_at<=? ORDER BY day DESC,received_at DESC,sequence DESC "
            "LIMIT 1", (day, cutoff)
        ).fetchone()
        latest_price = db.execute(
            "SELECT day FROM market_batches WHERE dataset='daily_prices' "
            "AND day<=? AND received_at<=? ORDER BY day DESC,received_at DESC,sequence DESC "
            "LIMIT 1", (str(date.fromisoformat(day) - timedelta(days=1)), cutoff)
        ).fetchone()
    sources = [(row[4], row[3], "membership", row) for row in observed]
    if master:
        sources.append((master[0], master[1], "master", master))
    sources.sort(key=lambda row: (row[0], row[1]), reverse=True)
    for source_day, _, kind, row in sources:
        if kind == "membership":
            record = membership._checked(row[:4], date.fromisoformat(source_day), now)
            batches = [record["datasets"]["security_master"]]
        else:
            batches = (rows for _, rows, _ in universe._observations(
                path, "security_master", source_day, source_day, now
            ))
        for records in batches:
            seen = set()
            for record in records:
                code, label = record.get("Code"), record.get("CoName")
                if not isinstance(code, str) or not isinstance(label, str) or not label.strip():
                    continue
                symbol = code if code in missing else code[:-1] if code.endswith("0") else None
                if symbol not in missing:
                    continue
                if symbol in seen:
                    raise ValueError("Duplicate held symbol in security master")
                names[symbol] = label.strip()
                seen.add(symbol)
            missing.difference_update(seen)
        if not missing:
            break
    prices = {}
    if latest_price:
        for _, records, source in universe._observations(
            path, "daily_prices", latest_price[0], latest_price[0], now
        ):
            closed_at = datetime.combine(date.fromisoformat(latest_price[0]), time(15, 30),
                                         ZoneInfo("Asia/Tokyo"))
            if market.receipt_time(source["received_at"]) < closed_at:
                continue
            if any(record.get("Date") != latest_price[0] for record in records):
                raise ValueError("Daily price date differs from source")
            seen = set()
            for record in records:
                code = record.get("Code")
                if not isinstance(code, str):
                    continue
                symbol = code if code in held else code[:-1] if code.endswith("0") else None
                if symbol not in held:
                    continue
                if symbol in seen:
                    raise ValueError("Duplicate held symbol in daily price")
                seen.add(symbol)
                close = universe.amount(record.get("C"))
                if close is not None and close > 0:
                    prices[symbol] = str(close)
    return {"portfolioId": portfolio.portfolio_id, "names": names,
            "prices": prices, "priceDate": latest_price[0] if latest_price else None}

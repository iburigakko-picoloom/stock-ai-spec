"""Read-only chart inputs from authenticated market and forecast records."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_ai.operations.daily import DAILY_NEXT_SESSION_CLOSE_LABEL

from . import forecasts, universe
from .storage import connect

MAX_DAYS = 366


def _number(value, *, positive=False):
    amount = universe.amount(value)
    if amount is None or (positive and amount == 0):
        return None
    result = float(amount)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("Chart source value is not finite")
    return result


def _prices(path: Path, symbol: str, first: date, last: date, now: datetime):
    result = {}
    for day, rows, source in universe._observations(path, "daily_prices", first, last, now):
        if any(row.get("Date") != day for row in rows):
            raise ValueError("Daily source date mismatch")
        matching = [row for row in rows if row.get("Code") == symbol + "0"]
        if len(matching) > 1:
            raise ValueError("Duplicate symbol in daily source")
        if matching:
            row = matching[0]
            result[day] = {
                "date": day,
                "close": _number(row.get("C"), positive=True),
                "volume": _number(row.get("Vo")),
                "adjustedClose": _number(row.get("AdjC"), positive=True),
                "adjustmentFactor": _number(row.get("AdjFactor"), positive=True),
                "exRightsType": row.get("ExRT") or None,
                "receivedAt": source["received_at"],
            }
    return result


def _calendar(path: Path, first: date, last: date, now: datetime):
    result = {}
    # A calendar response can include the following 21 days, including days
    # after the first chart date even if that date has no daily acquisition.
    for _, rows, _ in universe._observations(
        path, "trading_calendar", first - timedelta(days=21), last, now
    ):
        for row in rows:
            day = date.fromisoformat(row["Date"])
            if first <= day <= last:
                division = str(row["HolDiv"])
                if division not in {"0", "1", "2", "3"}:
                    raise ValueError("Unknown trading calendar division")
                result[str(day)] = division in {"1", "2"}
    return result


def realized(price_date: date, horizon: int, last: date, calendar: dict, prices: dict):
    """Compare adjusted close at T+1 and T+1+h only with continuous calendar proof."""
    sessions = []
    day = price_date + timedelta(days=1)
    while day <= last and len(sessions) < horizon + 1:
        key = str(day)
        if key not in calendar:
            return {
                "status": "calendar_missing",
                "return": None,
                "entryDate": None,
                "exitDate": None,
            }
        if calendar[key]:
            sessions.append(key)
        day += timedelta(days=1)
    if len(sessions) < horizon + 1:
        return {"status": "pending", "return": None, "entryDate": None, "exitDate": None}
    entry, exit = sessions[0], sessions[-1]
    for session in sessions:
        quote = prices.get(session)
        if quote is None or quote["adjustedClose"] is None:
            return {"status": "price_missing", "return": None, "entryDate": entry, "exitDate": exit}
        if quote.get("adjustmentFactor") is None:
            return {
                "status": "adjustment_missing",
                "return": None,
                "entryDate": entry,
                "exitDate": exit,
            }
        if quote["adjustmentFactor"] != 1 or quote.get("exRightsType") is not None:
            return {
                "status": "corporate_action",
                "return": None,
                "entryDate": entry,
                "exitDate": exit,
            }
    a, b = prices.get(entry, {}).get("adjustedClose"), prices.get(exit, {}).get("adjustedClose")
    if a is None or b is None:
        return {"status": "price_missing", "return": None, "entryDate": entry, "exitDate": exit}
    result = b / a - 1
    if not math.isfinite(result):
        raise ValueError("Chart return is not finite")
    return {"status": "available", "return": result, "entryDate": entry, "exitDate": exit}


def _predictions(path, store, symbol, first, last, now, calendar, prices):
    values = []
    linked = set()
    with connect(path) as db:
        for table, phase, kind in (
            ("mobile_forecast_runs", "published", "daily"),
            ("mobile_reference_runs", "reference_saved", "reference"),
        ):
            rows = db.execute(
                f"SELECT run_id,scope_hash,payload,content_hash,phase FROM {table} "
                "WHERE phase=? ORDER BY sequence",
                (phase,),
            )
            for row in rows:
                value, snapshot = forecasts._checked_with_snapshot(row)
                if snapshot is None:
                    raise ValueError("Saved forecast lacks a snapshot")
                linked.add(snapshot.snapshot_id)
                if snapshot.generated_at > now:
                    continue
                raw_day = value["scope"]["universe"].get("latest_source_date")
                price_day = None if raw_day is None else date.fromisoformat(raw_day)
                ordering_day = price_day or snapshot.as_of.astimezone(ZoneInfo("Asia/Tokyo")).date()
                if not first <= ordering_day <= last:
                    continue
                if kind == "daily" and store.prediction_snapshot(snapshot.snapshot_id) != snapshot:
                    raise ValueError("Published snapshot differs from saved forecast")
                prediction = next((p for p in snapshot.predictions if p.symbol == symbol), None)
                if prediction is None:
                    continue
                supported = snapshot.label_definition == DAILY_NEXT_SESSION_CLOSE_LABEL
                horizons = []
                for horizon, number in (
                    (5, prediction.expected_return_5d),
                    (20, prediction.expected_return_20d),
                ):
                    outcome = (
                        realized(price_day, horizon, last, calendar, prices)
                        if supported and number is not None and price_day is not None
                        else {
                            "status": (
                                "label_unsupported"
                                if not supported
                                else "prediction_missing"
                                if number is None
                                else "price_date_missing"
                            ),
                            "return": None,
                            "entryDate": None,
                            "exitDate": None,
                        }
                    )
                    horizons.append({"horizon": horizon, "expectedReturn": number, **outcome})
                values.append(
                    {
                        "runId": value["run_id"],
                        "snapshotId": snapshot.snapshot_id,
                        "kind": kind,
                        "priceDate": None if price_day is None else str(price_day),
                        "asOf": snapshot.as_of.isoformat(),
                        "generatedAt": snapshot.generated_at.isoformat(),
                        "modelVersion": snapshot.model_version,
                        "horizons": horizons,
                    }
                )
    # Older operational snapshots may have no mobile receipt. Preserve their
    # predictions, but never guess the original price day or invent a result.
    with store._connect() as db:
        ids = [row[0] for row in db.execute("SELECT snapshot_id FROM prediction_snapshots")]
    for identity in ids:
        if identity in linked:
            continue
        snapshot = store.prediction_snapshot(identity)
        local_day = snapshot.as_of.astimezone(ZoneInfo("Asia/Tokyo")).date()
        if snapshot.generated_at > now or not first <= local_day <= last:
            continue
        prediction = next((p for p in snapshot.predictions if p.symbol == symbol), None)
        if prediction is None:
            continue
        values.append(
            {
                "runId": "archive:" + identity,
                "snapshotId": identity,
                "kind": "archive",
                "priceDate": None,
                "asOf": snapshot.as_of.isoformat(),
                "generatedAt": snapshot.generated_at.isoformat(),
                "modelVersion": snapshot.model_version,
                "horizons": [
                    {
                        "horizon": horizon,
                        "expectedReturn": number,
                        "status": "price_date_missing",
                        "return": None,
                        "entryDate": None,
                        "exitDate": None,
                    }
                    for horizon, number in (
                        (5, prediction.expected_return_5d),
                        (20, prediction.expected_return_20d),
                    )
                ],
            }
        )
    return sorted(
        values,
        key=lambda x: (
            x["priceDate"]
            or str(datetime.fromisoformat(x["asOf"]).astimezone(ZoneInfo("Asia/Tokyo")).date()),
            datetime.fromisoformat(x["generatedAt"]),
            x["runId"],
        ),
    )


def read(path: Path, store, symbol: str, now: datetime, *, days=90):
    if not re.fullmatch(r"[0-9A-Z]{4}", symbol):
        raise ValueError("Invalid chart symbol")
    if (
        now.tzinfo is None
        or now.utcoffset() is None
        or type(days) is not int
        or not 1 <= days <= MAX_DAYS
    ):
        raise ValueError("Invalid chart interval")
    last = now.astimezone(ZoneInfo("Asia/Tokyo")).date() - timedelta(days=1)
    first = last - timedelta(days=days - 1)
    prices = _prices(path, symbol, first, last, now)
    calendar = _calendar(path, first, last, now)
    predictions = _predictions(path, store, symbol, first, last, now, calendar, prices)
    return {
        "symbol": symbol,
        "firstDate": str(first),
        "lastDate": str(last),
        "observedAt": now.isoformat(),
        "prices": [prices[k] for k in sorted(prices)],
        "calendar": calendar,
        "forecasts": predictions,
    }

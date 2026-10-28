"""Read saved predictions for a symbol without loading market price history."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import forecasts
from .storage import connect


def read(path: Path, store, symbol: str, now: datetime, *, days: int = 90):
    if not re.fullmatch(r"[A-Z0-9]{4}", symbol):
        raise ValueError("Invalid forecast symbol")
    if (now.tzinfo is None or now.utcoffset() is None
            or type(days) is not int or not 1 <= days <= 366):
        raise ValueError("Invalid forecast interval")
    jst = ZoneInfo("Asia/Tokyo")
    last = now.astimezone(jst).date()
    first = last - timedelta(days=days - 1)
    records = []
    linked = set()

    def add(snapshot, kind, run_id, price_day=None):
        decision_day = snapshot.as_of.astimezone(jst).date()
        if snapshot.generated_at > now or not first <= decision_day <= last:
            return
        prediction = next((item for item in snapshot.predictions if item.symbol == symbol), None)
        if prediction is None:
            return
        records.append({
            "runId": run_id,
            "snapshotId": snapshot.snapshot_id,
            "kind": kind,
            "date": str(decision_day),
            "asOf": snapshot.as_of.isoformat(),
            "generatedAt": snapshot.generated_at.isoformat(),
            "modelVersion": snapshot.model_version,
            "return5d": prediction.expected_return_5d,
            "return20d": prediction.expected_return_20d,
            "_dedupe": (price_day, snapshot.model_version, prediction.expected_return_5d,
                        prediction.expected_return_20d, getattr(prediction, "rank_score_20d", None))
                       if kind == "reference" and price_day is not None else None,
        })

    with connect(path) as db:
        for table, phase, kind in (
            ("mobile_forecast_runs", "published", "daily"),
            ("mobile_reference_runs", "reference_saved", "reference"),
        ):
            rows = db.execute(
                f"SELECT run_id,scope_hash,payload,content_hash,phase FROM {table} "
                "WHERE phase=? ORDER BY sequence", (phase,),
            )
            for row in rows:
                receipt, snapshot = forecasts._checked_with_snapshot(row)
                if snapshot is None:
                    raise ValueError("Saved forecast lacks a snapshot")
                linked.add(snapshot.snapshot_id)
                if kind == "daily" and store.prediction_snapshot(snapshot.snapshot_id) != snapshot:
                    raise ValueError("Published snapshot differs from saved forecast")
                price_day = receipt["scope"].get("universe", {}).get("latest_source_date")
                add(snapshot, kind, receipt["run_id"], price_day)
    with store._connect() as db:
        ids = [row[0] for row in db.execute("SELECT snapshot_id FROM prediction_snapshots")]
    for identity in ids:
        if identity not in linked:
            add(store.prediction_snapshot(identity), "archive", "archive:" + identity)
    records.sort(key=lambda item: (
        item["date"], datetime.fromisoformat(item["generatedAt"]), item["runId"]
    ))
    # Existing receipts remain immutable; collapse duplicate reference points
    # in the graph while preserving distinct models, prices, and daily runs.
    seen = set()
    unique = []
    for row in reversed(records):
        key = row.pop("_dedupe")
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        unique.append(row)
    records = list(reversed(unique))
    return {"symbol": symbol, "firstDate": str(first), "lastDate": str(last), "forecasts": records}

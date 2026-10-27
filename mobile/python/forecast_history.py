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

    def add(snapshot, kind, run_id):
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
                add(snapshot, kind, receipt["run_id"])
    with store._connect() as db:
        ids = [row[0] for row in db.execute("SELECT snapshot_id FROM prediction_snapshots")]
    for identity in ids:
        if identity not in linked:
            add(store.prediction_snapshot(identity), "archive", "archive:" + identity)
    records.sort(key=lambda item: (
        item["date"], datetime.fromisoformat(item["generatedAt"]), item["runId"]
    ))
    return {"symbol": symbol, "firstDate": str(first), "lastDate": str(last), "forecasts": records}

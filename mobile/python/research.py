"""Read the exact active numerical scope for device-scheduled company research."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_ai.operations.daily import PredictionSnapshot

from . import decisions, forecasts


def plan(path: Path, store, now: datetime) -> dict:
    if now.tzinfo is None:
        raise ValueError("Aware research scheduling time required")
    day = now.astimezone(ZoneInfo("Asia/Tokyo")).date()
    numerical, decision = forecasts.latest(path), decisions.view(path, store)
    if (not numerical or not decision or not decision["is_active"]
            or datetime.fromisoformat(numerical["scope"]["as_of"]).date() != day
            or datetime.fromisoformat(numerical["scope"]["as_of"]) > now
            or datetime.fromisoformat(numerical["checked_at"]) > now
            or datetime.fromisoformat(decision["checked_at"]) > now
            or decision["scope"]["numerical_run_id"] != numerical["run_id"]):
        raise ValueError("Current active numerical publication required")
    if numerical["phase"] == "cash_only" and decision["outcome"] == "cash_only":
        return {"day": str(day), "snapshot_id": None, "symbols": []}
    if numerical["phase"] != "published" or decision["phase"] != "published":
        raise ValueError("Numerical publication incomplete")
    snapshot = PredictionSnapshot.model_validate(numerical["snapshot"])
    if store.prediction_snapshot(snapshot.snapshot_id) != snapshot:
        raise ValueError("Frozen numerical publication changed")
    if snapshot.generated_at > now:
        raise ValueError("Future numerical publication")
    return {"day": str(day), "snapshot_id": snapshot.snapshot_id,
            "symbols": list(snapshot.research_symbols())}

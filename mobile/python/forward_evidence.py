"""Read-only inventory of saved daily forecast evidence, never score outcomes.

These receipts are already persisted by the normal daily pipeline. This view is
not a forward-evaluation registration and does not establish an adoption gate.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import forecasts
from .storage import connect


def inventory(path: Path, store, *, now: datetime) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("inventory time must be timezone-aware")
    rows = []
    with connect(path) as db:
        receipts = db.execute(
            "SELECT run_id,scope_hash,payload,content_hash,phase FROM mobile_forecast_runs "
            "WHERE phase='published' ORDER BY sequence"
        ).fetchall()
    for row in receipts:
        receipt, snapshot = forecasts._checked_with_snapshot(row)
        if snapshot is None or store.prediction_snapshot(snapshot.snapshot_id) != snapshot:
            raise ValueError("daily forecast and archived snapshot differ")
        if snapshot.generated_at > now:
            raise ValueError("daily forecast was generated in the future")
        proof = receipt["data_proof"]
        universe = receipt["scope"]["universe"]
        rows.append(
            {
                "run_id": receipt["run_id"],
                "snapshot_id": snapshot.snapshot_id,
                "as_of": snapshot.as_of.isoformat(),
                "generated_at": snapshot.generated_at.isoformat(),
                "data_as_of": snapshot.data_as_of.isoformat(),
                "model_version": snapshot.model_version,
                "feature_version": snapshot.feature_version,
                "selection_id": snapshot.selection_id,
                "data_proof_hash": snapshot.data_snapshot_id,
                "source_snapshot_ids": proof["source_snapshot_ids"],
                "membership_received_at": universe.get("membership_received_at"),
                "candidate_count": len(universe["new_candidates"]),
                "decision_count": len(universe["decision_symbols"]),
                "prediction_count": len(snapshot.predictions),
                "excluded_candidates": receipt["excluded_candidates"],
                "label_definition": snapshot.label_definition,
                "has_5d_return": all(
                    p.expected_return_5d is not None for p in snapshot.predictions
                ),
                "has_20d_return": all(
                    p.expected_return_20d is not None for p in snapshot.predictions
                ),
                "has_20d_rank": all(
                    getattr(p, "rank_score_20d", None) is not None for p in snapshot.predictions
                ),
                "outcomes_scored": False,
                "forward_registration_verified": False,
            }
        )
    return {
        "schema_version": "daily-evidence-inventory-v1",
        "read_at": now.isoformat(),
        "runs": rows,
        "formal_evaluation": False,
    }

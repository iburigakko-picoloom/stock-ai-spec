"""Only APK-pinned, reviewed model hashes may produce an adopted-model result."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .features import bundled_selection, calculate
from .market import feature_inputs
from .portable_model import predict


def policy() -> dict:
    path = Path("/stockai-code/model-policy.json")
    if not path.exists():
        path = Path(__file__).parents[1] / "model-policy.json"
    return json.loads(path.read_text(encoding="utf-8"))


def initialize(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS mobile_models("
            "sha256 TEXT PRIMARY KEY, payload TEXT NOT NULL, imported_at TEXT NOT NULL)"
        )


def import_model(path: Path, content: str) -> dict:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    entries = [item for item in policy()["approved_models"] if item["sha256"] == digest]
    if len(entries) != 1:
        raise ValueError("MODEL_NOT_ADOPTED_OR_REVIEWED")
    entry = entries[0]
    for key in (
        "adoption_evidence_sha256",
        "pc_parity_evidence_sha256",
        "device_parity_evidence_sha256",
    ):
        if len(entry.get(key, "")) != 64:
            raise ValueError("MODEL_EVIDENCE_MISSING")
    if entry.get("distribution_review") not in ("private-user-import-approved", "public-approved"):
        raise ValueError("MODEL_DISTRIBUTION_NOT_REVIEWED")
    model = json.loads(content)
    selection = bundled_selection()
    if any(
        entry.get(key) != selection[key]
        for key in ("feature_selection_id", "feature_manifest_hash")
    ):
        raise ValueError("Model feature selection is not the frozen PC selection")
    names = next(
        item["feature_names"]
        for item in selection["horizons"]
        if item["horizon"] == entry["horizon"]
    )
    if model["task"] != entry["task"] or not set(model["preprocessor"]["retained"]) <= set(names):
        raise ValueError("Model feature/task mismatch")
    predict(model, [])  # Validate scalar inference contract before persistence.
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT OR IGNORE INTO mobile_models VALUES(?,?,?)",
            (digest, content, datetime.now(UTC).isoformat()),
        )
    return {"sha256": digest, "model_id": entry["model_id"], "research_only": True}


def status(path: Path) -> dict:
    with sqlite3.connect(path) as db:
        imported = {row[0] for row in db.execute("SELECT sha256 FROM mobile_models")}
    approved = policy()["approved_models"]
    return {
        "approved_count": len(approved),
        "imported_count": len(imported),
        "model_adopted": bool(approved),
        "research_only": True,
    }


def infer(path: Path, now: datetime) -> dict:
    approved = policy()["approved_models"]
    required = {(5, "regression"), (20, "regression"), (20, "quantile"), (20, "large_loss")}
    if not required <= {(item["horizon"], item["task"]) for item in approved}:
        raise ValueError("MODEL_NOT_ADOPTED")
    features = calculate(feature_inputs(path, now), bundled_selection())
    result = []
    with sqlite3.connect(path) as db:
        for item in approved:
            row = db.execute(
                "SELECT payload FROM mobile_models WHERE sha256=?", (item["sha256"],)
            ).fetchone()
            if not row or hashlib.sha256(row[0].encode("utf-8")).hexdigest() != item["sha256"]:
                raise ValueError("Approved model missing or altered")
            values = features["features"][str(item["horizon"])]
            cutoff = datetime.fromisoformat(features["as_of"])
            if any(
                datetime.fromisoformat(value["available_at"].replace("Z", "+00:00")) != cutoff
                for value in values
            ):
                raise ValueError("STALE_FEATURES")
            predictions = predict(json.loads(row[0]), values)
            result.append(
                {
                    "model_id": item["model_id"],
                    "sha256": item["sha256"],
                    "horizon": item["horizon"],
                    "task": item["task"],
                    "values": [
                        {"symbol": value["symbol"], "value": prediction}
                        for value, prediction in zip(values, predictions, strict=True)
                    ],
                }
            )
    return {
        "as_of": features["as_of"],
        "generated_at": now.isoformat(),
        "research_only": True,
        "order_submission": False,
        "model_outputs": result,
    }

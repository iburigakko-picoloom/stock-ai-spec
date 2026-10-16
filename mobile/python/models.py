"""Only APK-pinned, reviewed model hashes may produce an adopted-model result."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .features import bundled_selection, calculate
from .market import feature_inputs
from .model_bundle import approved
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
        db.execute(
            "CREATE TABLE IF NOT EXISTS mobile_model_bundles("
            "sha256 TEXT PRIMARY KEY,payload TEXT NOT NULL,imported_at TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS mobile_model_selections("
            "sequence INTEGER PRIMARY KEY,sha256 TEXT NOT NULL,selected_at TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS mobile_model_repairs("
            "sequence INTEGER PRIMARY KEY,sha256 TEXT NOT NULL,old_content_sha256 TEXT NOT NULL,"
            "repaired_at TEXT NOT NULL)"
        )


def import_bundle(path: Path, content: str, now: datetime) -> dict:
    bundle, entry = approved(content, policy(), bundled_selection)
    if now.tzinfo is None or bundle.created_at > now:
        raise ValueError("Invalid model import time")
    digest = entry["sha256"]
    with sqlite3.connect(path) as db:
        # All four heads, calibration and review are validated before a single
        # immutable write. No partial head import can become usable.
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT payload,imported_at FROM mobile_model_bundles WHERE sha256=?",
                              (digest,)).fetchone()
        if previous is not None and hashlib.sha256(previous[0].encode()).hexdigest() != digest:
            if datetime.fromisoformat(previous[1]) > now:
                raise ValueError("Model repair clock moved backward")
            db.execute("INSERT INTO mobile_model_repairs VALUES(NULL,?,?,?)", (
                digest, hashlib.sha256(previous[0].encode()).hexdigest(),
                now.astimezone(UTC).isoformat(),
            ))
            # Restore only an exactly pinned artifact. Its renewed availability
            # is now, so a late repair cannot backdate usable model parameters.
            db.execute("UPDATE mobile_model_bundles SET payload=?,imported_at=? WHERE sha256=?",
                       (content, now.astimezone(UTC).isoformat(), digest))
        db.execute("INSERT OR IGNORE INTO mobile_model_bundles VALUES(?,?,?)",
                   (digest, content, now.astimezone(UTC).isoformat()))
        selected = db.execute(
            "SELECT sha256,selected_at FROM mobile_model_selections ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if selected is not None and datetime.fromisoformat(selected[1]) > now:
            raise ValueError("Model selection clock moved backward")
        if selected is None or selected[0] != digest:
            db.execute("INSERT INTO mobile_model_selections VALUES(NULL,?,?)",
                       (digest, now.astimezone(UTC).isoformat()))
    return {"sha256": digest, "bundle_id": bundle.bundle_id,
            "head_count": 4, "research_only": True}


def load_bundle(path: Path, cutoff: datetime):
    if cutoff.tzinfo is None:
        raise ValueError("Aware model cutoff required")
    with sqlite3.connect(path) as db:
        row = db.execute(
            "SELECT b.sha256,b.payload,b.imported_at,s.selected_at FROM mobile_model_selections s "
            "LEFT JOIN mobile_model_bundles b ON b.sha256=s.sha256 "
            "ORDER BY s.sequence DESC LIMIT 1"
        ).fetchone()
    current = policy()
    pins = {x["sha256"] for x in current.get("approved_bundles", [])}
    if row is None:
        raise ValueError("MODEL_BUNDLE_NOT_IMPORTED")
    digest, content, imported, selected = row
    if digest not in pins:
        raise ValueError("MODEL_BUNDLE_APPROVAL_REMOVED")
    if content is None or hashlib.sha256(content.encode()).hexdigest() != digest:
        raise ValueError("Imported bundle changed")
    bundle, entry = approved(content, current, bundled_selection)
    if max(datetime.fromisoformat(imported), datetime.fromisoformat(selected)) > cutoff:
        raise ValueError("MODEL_IMPORTED_AFTER_ALPHA_CUTOFF")
    bundle.at(cutoff)
    return bundle, entry


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


def status(path: Path, store=None) -> dict:
    with sqlite3.connect(path) as db:
        imported = {row[0] for row in db.execute("SELECT sha256 FROM mobile_models")}
        bundles = {row[0] for row in db.execute("SELECT sha256 FROM mobile_model_bundles")}
    current = policy()
    approved = current["approved_models"]
    bundle_pins = {x["sha256"] for x in current.get("approved_bundles", [])}
    ready = False
    adopted = False
    reason = None
    if bundles & bundle_pins:
        try:
            bundle, _ = load_bundle(path, datetime.now(UTC))
            ready = True
            if store is not None and bundle.adoption_review.decision == "adopt":
                try:
                    adopted = store.adoption_review(
                        bundle.adoption_review.review_id
                    ) == bundle.adoption_review
                except KeyError:
                    adopted = False
        except (ValueError, KeyError, TypeError):
            reason = "MODEL_BUNDLE_INVALID_OR_UNAVAILABLE"
    return {
        "approved_count": len(approved),
        "imported_count": len(imported),
        "approved_bundle_count": len(bundle_pins),
        "imported_bundle_count": len(bundles & bundle_pins),
        # A reviewed legacy head alone is not a calibrated daily model bundle.
        "model_adopted": adopted,
        "bundle_ready": ready,
        "bundle_blocking_reason": reason,
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

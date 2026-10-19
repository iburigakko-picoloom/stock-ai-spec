from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from mobile.pc.package_bundle import package
from mobile.python import models
from mobile.python.model_bundle import ModelBundle, approved, encoded
from mobile.python.portable_model import predict

from stock_ai.operations.daily import (
    QUOTE_SESSION_LABEL,
    OwnerAdoptionReview,
    canonical_json,
    content_id,
)

IMPORTED = datetime.fromisoformat("2026-02-02T09:00:00Z")
CUTOFF = datetime.fromisoformat("2026-02-03T11:30:00+09:00")
SELECTION = {"feature_selection_id": "a" * 64, "feature_manifest_hash": "b" * 64,
             "horizons": [{"horizon": 5, "feature_names": ["f1"]},
                          {"horizon": 20, "feature_names": ["f1"]}]}


def fixture_bundle():
    review = OwnerAdoptionReview.create(
        selection_id="c" * 64, holdout_report_id="d" * 64, evaluator_receipt_id="e" * 64,
        decision_policy_hash="f" * 64,
        reviewed_at=datetime.fromisoformat("2026-02-02T07:00:00Z"),
        decision="continue_paper", unresolved_gates=("synthetic-test-only",),
        acknowledged_limitations=("Never use these fixture values as market data",),
        note="Synthetic test owner review",
    )
    heads = []
    for horizon, task, leaf in ((5, "regression", .01), (20, "regression", .04),
                                (20, "quantile", -.08), (20, "large_loss", -2.0)):
        model = {"schema_version": "stockai-portable-tree-v1", "family": "lightgbm",
                 "task": task, "preprocessor": {"retained": ["f1"], "lower": {"f1": None},
                 "upper": {"f1": None}, "median": {"f1": 0.0}}, "base_score": 0.0,
                 "link": "sigmoid" if task == "large_loss" else "identity",
                 "trees": [{"leaf": leaf}], "research_only": True}
        content = canonical_json(model)
        heads.append({"horizon": horizon, "task": task, "model_id": f"fixture-{horizon}-{task}",
                      "content": content, "sha256": hashlib.sha256(content.encode()).hexdigest()})
    return ModelBundle.create(
        created_at="2026-02-02T08:00:00Z", trained_at="2026-02-01T00:00:00Z",
        training_data_cutoff="2026-01-30T00:00:00Z",
        feature_selection_id=SELECTION["feature_selection_id"],
        feature_manifest_hash=SELECTION["feature_manifest_hash"], selection_id="c" * 64,
        adoption_review=review, calibration={"method": "received_past_only_20d_residual_rmse",
        "residual_rmse": .02, "rows": 40, "dates": 20,
        "latest_label_available_at": "2026-02-01T00:00:00Z",
        "fitted_at": "2026-02-01T01:00:00Z", "source_evidence_sha256": "1" * 64},
        large_loss_threshold=-.08, downside_quantile_alpha=.1, heads=heads,
    )


def fixture_pin(bundle):
    content = encoded(bundle)
    return {"sha256": hashlib.sha256(content.encode()).hexdigest(), "bundle_id": bundle.bundle_id,
            "adoption_evidence_sha256": content_id(bundle.adoption_review.model_dump(mode="json")),
            "calibration_evidence_sha256": bundle.calibration.source_evidence_sha256,
            "pc_parity_evidence_sha256": "2" * 64, "device_parity_evidence_sha256": "3" * 64,
            "distribution_review": "private-user-import-approved"}


@pytest.fixture()
def imported(tmp_path, monkeypatch):
    bundle = fixture_bundle()
    pin = fixture_pin(bundle)
    current = {"approved_models": [], "approved_bundles": [pin]}
    monkeypatch.setattr(models, "policy", lambda: current)
    monkeypatch.setattr(models, "bundled_selection", lambda: SELECTION)
    path = tmp_path / "mobile.sqlite3"
    models.initialize(path)
    return path, bundle, pin, current


def test_atomic_idempotent_bundle_import_does_not_promote_adoption(imported):
    path, bundle, _, _ = imported
    assert models.status(path)["bundle_ready"] is False
    models.import_bundle(path, encoded(bundle), IMPORTED)
    models.import_bundle(path, encoded(bundle), IMPORTED + timedelta(days=1))
    assert models.load_bundle(path, CUTOFF)[0] == bundle
    status = models.status(path)
    assert status["bundle_ready"] is True and status["model_adopted"] is False
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM mobile_model_bundles").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM mobile_model_selections").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM mobile_models").fetchone()[0] == 0


def test_legacy_label_bundle_is_archivable_but_cannot_be_imported_or_selected(imported):
    path, bundle, _, current = imported
    legacy = ModelBundle.create(
        **{**bundle.model_dump(mode="json", exclude={"bundle_id"}),
           "label_definition": QUOTE_SESSION_LABEL}
    )
    content = encoded(legacy)
    assert ModelBundle.model_validate_json(content).bundle_id == legacy.bundle_id
    pin = fixture_pin(legacy)
    current["approved_bundles"].append(pin)
    with pytest.raises(ValueError, match="LABEL_DEFINITION_UNVERIFIED"):
        models.import_bundle(path, content, IMPORTED)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM mobile_model_bundles").fetchone()[0] == 0
        # Simulate a previously saved legacy bundle without reinterpreting it.
        db.execute("INSERT INTO mobile_model_bundles VALUES(?,?,?)",
                   (pin["sha256"], content, IMPORTED.isoformat()))
        db.execute("INSERT INTO mobile_model_selections VALUES(NULL,?,?)",
                   (pin["sha256"], IMPORTED.isoformat()))
    with pytest.raises(ValueError, match="LABEL_DEFINITION_UNVERIFIED"):
        models.load_bundle(path, CUTOFF)
    assert models.status(path)["bundle_ready"] is False
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT payload FROM mobile_model_bundles").fetchone()[0] == content
    metadata = legacy.model_dump(mode="json", exclude={"bundle_id", "heads"})
    with pytest.raises(ValueError, match="LABEL_DEFINITION_UNVERIFIED"):
        package(metadata, [h.model_dump(mode="json") for h in legacy.heads], SELECTION)


def test_import_or_new_selection_after_cutoff_never_falls_back_to_an_older_model(imported):
    path, bundle, _, current = imported
    models.import_bundle(path, encoded(bundle), IMPORTED)
    data = bundle.model_dump(mode="json", exclude={"bundle_id"})
    data["calibration"]["residual_rmse"] = .03
    newer = ModelBundle.create(**data)
    current["approved_bundles"].append(fixture_pin(newer))
    models.import_bundle(path, encoded(newer), CUTOFF + timedelta(microseconds=1))
    with pytest.raises(ValueError, match="AFTER_ALPHA_CUTOFF"):
        models.load_bundle(path, CUTOFF)
    current["approved_bundles"].pop()
    with pytest.raises(ValueError, match="APPROVAL_REMOVED"):
        models.load_bundle(path, CUTOFF + timedelta(days=1))
    assert models.status(path)["bundle_ready"] is False


@pytest.mark.parametrize("field", ["device_parity_evidence_sha256", "calibration_evidence_sha256",
                                  "pc_parity_evidence_sha256", "distribution_review"])
def test_missing_review_or_parity_blocks_the_entire_import(imported, field):
    path, bundle, pin, _ = imported
    pin[field] = None
    with pytest.raises(ValueError):
        models.import_bundle(path, encoded(bundle), IMPORTED)
    assert models.status(path)["imported_bundle_count"] == 0


def test_rehashed_invalid_tree_is_rejected_before_any_head_is_saved(imported):
    path, bundle, _, current = imported
    data = bundle.model_dump(mode="json", exclude={"bundle_id"})
    head = data["heads"][-1]
    tree = json.loads(head["content"])
    tree["trees"] = [{"feature": 99, "threshold": 0.0, "operator": "<=", "missing_left": True,
                      "left": {"leaf": 0.0}, "right": {"leaf": 1.0}}]
    head["content"] = canonical_json(tree)
    head["sha256"] = hashlib.sha256(head["content"].encode()).hexdigest()
    invalid = ModelBundle.create(**data)
    current["approved_bundles"][:] = [fixture_pin(invalid)]
    with pytest.raises(ValueError, match="Invalid model split"):
        models.import_bundle(path, encoded(invalid), IMPORTED)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM mobile_model_bundles").fetchone()[0] == 0


def test_unreviewed_weights_and_tampered_storage_never_produce_output(imported):
    path, bundle, _, _ = imported
    with pytest.raises(ValueError, match="NOT_REVIEWED"):
        models.import_bundle(path, encoded(bundle) + " ", IMPORTED)
    models.import_bundle(path, encoded(bundle), IMPORTED)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE mobile_model_bundles SET payload='{}'")
    with pytest.raises(ValueError, match="bundle changed"):
        models.load_bundle(path, CUTOFF)
    assert models.status(path)["bundle_ready"] is False
    models.import_bundle(path, encoded(bundle), CUTOFF + timedelta(microseconds=1))
    assert models.status(path)["bundle_ready"] is True
    with pytest.raises(ValueError, match="AFTER_ALPHA_CUTOFF"):
        models.load_bundle(path, CUTOFF)
    assert models.load_bundle(path, CUTOFF + timedelta(days=1))[0] == bundle
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM mobile_model_repairs").fetchone()[0] == 1
        db.execute("UPDATE mobile_model_bundles SET payload='{}'")
    with pytest.raises(ValueError, match="clock moved backward"):
        models.import_bundle(path, encoded(bundle), CUTOFF)
    assert models.status(path)["bundle_ready"] is False
    models.import_bundle(path, encoded(bundle), CUTOFF + timedelta(days=1))


def test_calibration_counts_units_and_future_receipts_cannot_be_invented(imported):
    _, bundle, pin, current = imported
    data = bundle.model_dump(mode="json", exclude={"bundle_id"})
    for field, value in (("dates", 19), ("residual_rmse", None), ("residual_rmse", float("nan"))):
        modified = copy.deepcopy(data)
        modified["calibration"][field] = value
        with pytest.raises(ValueError):
            ModelBundle.create(**modified)
    modified = copy.deepcopy(data)
    modified["unit"] = "percent"
    with pytest.raises(ValueError):
        ModelBundle.create(**modified)
    assert approved(encoded(bundle), current, SELECTION)[1] == pin
    with pytest.raises(ValueError, match="unavailable"):
        bundle.at(datetime.fromisoformat("2026-02-01T00:00:00Z"))


def test_packager_outputs_a_pending_proposal_and_never_approves_its_own_file():
    bundle = fixture_bundle()
    metadata = bundle.model_dump(mode="json", exclude={"bundle_id", "heads"})
    content, proposal = package(metadata, [x.model_dump() for x in bundle.heads], SELECTION)
    assert content == encoded(bundle)
    assert proposal["distribution_review"] == "pending"
    with pytest.raises(ValueError, match="EVIDENCE_MISSING"):
        approved(content, {"approved_bundles": [proposal]}, SELECTION)


def test_empty_parity_inputs_still_validate_every_tree():
    model = json.loads(fixture_bundle().heads[0].content)
    model["trees"] = [{"leaf": float("inf")}]
    with pytest.raises(ValueError, match="leaf"):
        predict(model, [])


def test_packaging_command_preserves_existing_files_and_outputs_one_private_bundle(tmp_path):
    bundle = fixture_bundle()
    metadata = tmp_path / "metadata.json"
    metadata.write_text(canonical_json(bundle.model_dump(
        mode="json", exclude={"bundle_id", "heads"}
    )), encoding="utf-8")
    heads = []
    for index, head in enumerate(bundle.heads):
        path = tmp_path / f"head-{index}.json"
        path.write_bytes(head.content.encode())
        heads.append({"horizon": head.horizon, "task": head.task,
                      "model_id": head.model_id, "path": path.name})
    manifest, selection, output = (tmp_path / name for name in
                                   ("heads.json", "selection.json", "private-bundle.json"))
    manifest.write_text(canonical_json(heads), encoding="utf-8")
    selection.write_text(canonical_json(SELECTION), encoding="utf-8")
    environment = {k: v for k, v in os.environ.items()
                   if k not in ("JQUANTS_API_KEY", "OPENAI_API_KEY")}
    root = Path(__file__).resolve().parents[1]
    environment["PYTHONPATH"] = str(root / "src")
    command = [sys.executable, "-m", "mobile.pc.package_bundle", "--metadata", str(metadata),
               "--heads", str(manifest), "--selection", str(selection), "--output", str(output)]
    result = subprocess.run(command, cwd=root, env=environment, capture_output=True, check=True)
    assert b"unapproved pin" in result.stdout
    assert output.read_bytes() == encoded(bundle).encode()
    pin = json.loads(output.with_suffix(".pin-proposal.json").read_text())
    assert pin["distribution_review"] == "pending"
    original = output.read_bytes()
    assert subprocess.run(command, cwd=root, env=environment, capture_output=True).returncode != 0
    assert output.read_bytes() == original

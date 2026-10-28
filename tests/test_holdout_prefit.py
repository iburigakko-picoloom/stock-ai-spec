"""Synthetic-only same-fit inlet; never private artifacts or real final data."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import stock_ai.ml.holdout as holdout_module
import tests.test_final_strategy as final_fixture
from stock_ai.ml.advanced import frozen_training_identity
from stock_ai.ml.holdout import evaluate_locked_holdout
from stock_ai.ml.selection import (
    FrozenCompositionManifest,
    FrozenPrefitArtifact,
    FrozenPrefitReceipt,
    FrozenPrefitReceiptReference,
)
from tests.test_holdout_frozen_composition import composition
from tests.test_locked_holdout import _selection_fixture


def artifact(path: Path) -> FrozenPrefitArtifact:
    payload = path.read_bytes()
    return FrozenPrefitArtifact(
        path=str(path), bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()
    )


def composition_inputs(value: FrozenCompositionManifest):
    # create() takes typed choices, preserving nested legacy serializer identities.
    return {
        name: getattr(value, name)
        for name in FrozenCompositionManifest.model_fields
        if name != "composition_id"
    }


def identity_frame() -> pd.DataFrame:
    dates = pd.date_range("2025-01-06", periods=4).as_unit("ns")
    return pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D"],
            "trading_date": dates,
            "as_of": pd.to_datetime(dates, utc=True) + pd.Timedelta(hours=11),
            "target_return_5d": [0.01, -0.02, 0.03, 0.04],
            "label_status_5d": "AVAILABLE",
            "label_end_date_5d": dates + pd.Timedelta(days=8),
            "label_available_at_5d": pd.to_datetime(dates, utc=True) + pd.Timedelta(days=9),
            "x": [1.0, np.inf, np.nan, 4.0],
            "z": [4.0, 3.0, 2.0, 1.0],
        }
    )


def test_frozen_training_identity_columnwise_coercion_and_raw_tamper():
    frame = identity_frame()

    def digest(data, names=("x", "z")):
        return frozen_training_identity(
            data, feature_names=names, target_column="target_return_5d", horizon=5
        )["identity_sha256"]

    expected = digest(frame)
    equivalent = frame.sample(frac=1, random_state=7).copy()
    equivalent["unused_column"] = "not a fit input"
    equivalent["x"] = equivalent.x.replace([np.inf, -np.inf], np.nan).astype("float32")
    assert digest(equivalent) == expected
    for column in (
        "x",
        "target_return_5d",
        "label_status_5d",
        "as_of",
        "label_end_date_5d",
        "label_available_at_5d",
    ):
        changed = frame.copy()
        if column in ("as_of", "label_available_at_5d", "label_end_date_5d"):
            changed.loc[[0], column] = changed.loc[[0], column] + pd.Timedelta(days=1)
        elif column == "label_status_5d":
            changed.loc[0, column] = "CORRECTED"
        else:
            changed.loc[0, column] += 0.125
        assert digest(changed) != expected
    assert digest(frame, ("z", "x")) != expected


def test_empty_prefit_preserves_original_manifest_identity():
    selection = _selection_fixture(build_id="a" * 64, dataset_id="b" * 64)
    selection = selection.model_copy(
        update={"horizons": tuple(h for h in selection.horizons if h.horizon in (5, 20))}
    )
    # The helper only needs coherent horizon component references, not a published Selection.
    old = composition(selection)
    payload = old.model_dump(mode="json")
    assert "prefit_receipts" not in payload
    assert "prefit_receipts" not in old.model_dump_json()
    rebuilt = FrozenCompositionManifest.create(**composition_inputs(old))
    assert rebuilt.composition_id == old.composition_id
    without_id = {k: v for k, v in payload.items() if k != "composition_id"}
    assert old.composition_id == hashlib.sha256(
        json.dumps(without_id, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="content hash"):
        FrozenCompositionManifest.model_validate({**payload, "composition_id": "f" * 64})


def build_prefit_fixture(tmp_path, monkeypatch, *, failure=None):
    calls = []
    retained = []
    actual_evaluate = evaluate_locked_holdout
    original_frames = holdout_module._holdout_frames

    def predictor(receipt, features):
        assert receipt in retained
        assert not any(name.startswith(("target", "label")) for name in features.columns)
        assert "symbol" not in features and "trading_date" not in features
        calls.append(receipt.component.component_name)
        if failure == "shape":
            return np.zeros((len(features), 1))
        if failure == "nonfinite":
            return np.full(len(features), np.nan)
        return np.linspace(0.01, 0.03, len(features))

    def builder(selection):
        c = composition(selection)
        boundary = pd.Timestamp(selection.locked_holdout_start).tz_localize("UTC").to_pydatetime()
        data = composition_inputs(c)
        data["components"] = tuple(
            p.model_copy(update={"train_cutoff": boundary}) for p in c.components
        )
        c = FrozenCompositionManifest.create(**data)
        build_path = next((tmp_path / "builds").glob("*/*.json"))
        dataset_path = json.loads(build_path.read_text())["dataset_parquet_path"]
        dataset = pd.read_parquet(dataset_path)
        frames = original_frames(dataset, selection, c)
        refs = []
        for part in c.components:
            component = part.component
            training, _ = frames[component.horizon]
            assert pd.to_datetime(training.trading_date, utc=True).max() < boundary
            assert (
                pd.to_datetime(training[f"label_end_date_{component.horizon}d"], utc=True).max()
                < boundary
            )
            assert (
                pd.to_datetime(training[f"label_available_at_{component.horizon}d"], utc=True).max()
                < boundary
            )
            component_key = hashlib.sha256(component.component_name.encode()).hexdigest()[:16]
            root = tmp_path / f"prefit-h{component.horizon}-{component_key}"
            root.mkdir()
            native, processor = root / "synthetic-native.bin", root / "synthetic-processor.json"
            native.write_bytes(b"SYNTHETIC_ONLY_NO_MODEL_FIT")
            processor.write_text('{"fixture_only":true}', encoding="utf8")
            identity = frozen_training_identity(
                training,
                feature_names=next(
                    h for h in selection.horizons if h.horizon == component.horizon
                ).feature_names,
                target_column=f"target_return_{component.horizon}d",
                horizon=component.horizon,
            )
            receipt = FrozenPrefitReceipt(
                component=component,
                build_id=selection.build_id,
                data_snapshot_id=selection.data_snapshot_id,
                feature_names_hash=part.feature_names_hash,
                preprocessing_rule_sha256=part.preprocessing_rule_sha256,
                training_identity_sha256=identity["identity_sha256"],
                training_identity_version=identity["version"],
                train_cutoff=part.train_cutoff,
                created_at=c.created_at - timedelta(seconds=1),
                native=artifact(native),
                full_processor=artifact(processor),
            )
            if failure == "snapshot":
                receipt = receipt.model_copy(update={"data_snapshot_id": "f" * 64})
            if failure == "config":
                altered = component.model_copy(
                    update={"parameters": {**component.parameters, "changed": 1}}
                )
                receipt = receipt.model_copy(update={"component": altered})
            if failure == "feature_order":
                receipt = receipt.model_copy(update={"feature_names_hash": "f" * 64})
            path = root / "receipt.json"
            path.write_text(receipt.model_dump_json(), encoding="utf8")
            refs.append(
                FrozenPrefitReceiptReference(
                    horizon=component.horizon,
                    component_name=component.component_name,
                    receipt=artifact(path),
                )
            )
            retained.append(receipt)
        if failure in ("native", "processor"):
            target = retained[0].native if failure == "native" else retained[0].full_processor
            Path(target.path).write_bytes(b"ALTERED")
        if failure == "training":

            def altered_frames(*args):
                result = dict(original_frames(*args))
                h = c.components[0].component.horizon
                training, holdout = result[h]
                training = training.copy()
                column = next(x for x in selection.horizons if x.horizon == h).feature_names[0]
                training.loc[0, column] += 0.5
                result[h] = (training, holdout)
                return result

            monkeypatch.setattr(holdout_module, "_holdout_frames", altered_frames)
        data = composition_inputs(c)
        data["prefit_receipts"] = tuple(refs)
        return FrozenCompositionManifest.create(**data)

    def evaluate(**kwargs):
        return actual_evaluate(
            **kwargs,
            prefit_predictor=None if failure == "missing_predictor" else predictor,
            require_model_retention=True,
        )

    monkeypatch.setattr(final_fixture, "evaluate_locked_holdout", evaluate)
    fixture = final_fixture.fixture(tmp_path, monkeypatch, composition_builder=builder)
    return fixture, calls


def test_prefit_native_path_never_fits_and_completed_resume_never_predicts(tmp_path, monkeypatch):
    f, calls = build_prefit_fixture(tmp_path, monkeypatch)
    assert f["calls"] == [] and len(calls) == 6
    report = json.loads(f["report_path"].read_text())["report"]
    assert not report["adoption_eligible"]
    before = len(calls)
    again = evaluate_locked_holdout(
        selection_path=f["selection_path"],
        build_manifest_path=f["build"],
        evaluation_root=tmp_path / "holdout",
        evaluator_code_commit="synthetic-final-evaluator",
        composition_path=f["composition_path"],
    )
    assert again.resumed and len(calls) == before and f["calls"] == []


@pytest.mark.parametrize(
    "failure,match",
    [
        ("native", "artifact byte/hash"),
        ("processor", "artifact byte/hash"),
        ("training", "training frame identity"),
        ("shape", "invalid values or shape"),
        ("nonfinite", "invalid values or shape"),
        ("missing_predictor", "no fit fallback"),
        ("snapshot", "differs from frozen composition"),
        ("config", "differs from frozen composition"),
        ("feature_order", "differs from frozen composition"),
    ],
)
def test_prefit_mismatch_or_missing_inlet_fails_closed(tmp_path, monkeypatch, failure, match):
    with pytest.raises(ValueError, match=match):
        build_prefit_fixture(tmp_path, monkeypatch, failure=failure)


def test_retention_request_needs_sink_on_legacy_path(tmp_path):
    from stock_ai.ml.selection import write_development_selection
    from tests.test_locked_holdout import _production_fixture

    build, dataset_id, build_id = _production_fixture(tmp_path)
    selection = _selection_fixture(build_id=build_id, dataset_id=dataset_id)
    path = write_development_selection(selection, tmp_path / "selection")
    with pytest.raises(ValueError, match="synchronous fitted model sink"):
        evaluate_locked_holdout(
            selection_path=path,
            build_manifest_path=build,
            evaluation_root=tmp_path / "holdout",
            evaluator_code_commit="test",
            require_model_retention=True,
        )
    assert not (path.parent / "holdout-access.json").exists()


def test_retention_request_rejects_fit_without_sink_emission(monkeypatch):
    selection = _selection_fixture(build_id="a" * 64, dataset_id="b" * 64)
    plan = holdout_module._component_plans(selection, None)[0]
    monkeypatch.setattr(
        holdout_module, "fit_predict_frozen_model", lambda *a, **kw: np.ones(4)
    )
    retained = []
    with pytest.raises(ValueError, match="without retained native model and processor"):
        holdout_module._fit_pending_component(
            identity_frame(), identity_frame(), plan, lambda *a: retained.append(a), True
        )
    assert retained == []


def test_exclusive_cutoff_may_equal_boundary_but_must_not_cross_it():
    from stock_ai.ml.selection import _validate_composition_selection

    selection = _selection_fixture(build_id="a" * 64, dataset_id="b" * 64)
    c = composition(
        selection.model_copy(
            update={"horizons": tuple(h for h in selection.horizons if h.horizon in (5, 20))}
        )
    )
    boundary = pd.Timestamp(selection.locked_holdout_start).tz_localize("UTC").to_pydatetime()
    for offset in (timedelta(0), timedelta(seconds=1)):
        values = composition_inputs(c)
        values["components"] = tuple(
            p.model_copy(update={"train_cutoff": boundary + offset}) for p in c.components
        )
        changed = FrozenCompositionManifest.create(**values)
        if offset:
            with pytest.raises(ValueError, match="cutoff crosses"):
                _validate_composition_selection(changed, selection)
        else:
            _validate_composition_selection(changed, selection)

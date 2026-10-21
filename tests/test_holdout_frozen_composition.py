"""Synthetic composition-to-single-use holdout bridge; no private holdout access."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from mobile.python.research_ensemble import (
    EnsembleCalibration,
    EnsembleOutput,
    average_percentile,
    inference,
)

import stock_ai.ml.holdout as holdout_module
from stock_ai.ml.holdout import evaluate_locked_holdout
from stock_ai.ml.selection import (
    FrozenCompositionComponent,
    FrozenCompositionManifest,
    FrozenCompositionOutput,
    FrozenCompositionPopulation,
    FrozenModelComponent,
    compose_frozen_predictions,
    load_frozen_composition,
    write_frozen_composition,
)
from stock_ai.operations.daily import content_id
from tests.test_final_strategy import fixture, run
from tests.test_locked_holdout import _selection_fixture
from tests.test_mobile_bundles import SELECTION
from tests.test_mobile_research_ensemble import ensemble_bundle, fixture_rows, universes


def composition(selection) -> FrozenCompositionManifest:
    now = datetime.now(UTC)
    past = datetime(2025, 2, 26, tzinfo=UTC)
    parts, outputs, population = [], [], []
    for horizon in selection.horizons:
        first = horizon.expected_return_component
        values = first.model_dump(mode="python")
        config = first.source_config.model_copy(update={"model_families": ("xgboost",)})
        values.update(
            component_name="extra-xgboost-regression-s17",
            model_family="xgboost",
            source_config=config,
            source_config_hash=config.config_hash,
        )
        second = FrozenModelComponent.model_validate(values)
        rank = next(c for c in horizon.ensemble_components if c.task == "ranking")
        for component in (first, second, rank):
            cfg = component.source_config
            parts.append(
                FrozenCompositionComponent(
                    component=component,
                    feature_names_hash=horizon.feature_names_hash,
                    preprocessing_rule_sha256=content_id(
                        {
                            "feature_names_hash": horizon.feature_names_hash,
                            "clip_lower_quantile": cfg.clip_lower_quantile,
                            "clip_upper_quantile": cfg.clip_upper_quantile,
                            "correlation_threshold": cfg.correlation_threshold,
                        }
                    ),
                    definition_received_at=past,
                    train_cutoff=past,
                )
            )
        for role, names, transform in (
            ("return", (first.component_name, second.component_name), "identity"),
            (
                "ranking",
                (first.component_name, rank.component_name),
                "within_date_average_percentile_v1",
            ),
        ):
            ranked = role == "ranking"
            outputs.append(
                FrozenCompositionOutput(
                    output_id=f"h{horizon.horizon}-{role}",
                    horizon=horizon.horizon,
                    role=role,
                    recipe_version="daily-forward-crossfit-v1",
                    components=names,
                    weights=(0.25, 0.75),
                    weight_source="learned",
                    transform=transform,
                    unit="rank_score" if ranked else "fractional_return",
                    rank_universe="decision_symbols" if ranked else None,
                    universe_rule_version="synthetic-independent-v1" if ranked else None,
                    universe_evidence_sha256=content_id("independent-population")
                    if ranked
                    else None,
                    source_evidence_sha256=content_id("development-forward-crossfit"),
                    latest_weight_label_available_at=past - timedelta(days=1),
                    weights_fitted_at=past,
                    received_at=past,
                )
            )
        for day in pd.bdate_range("2025-03-03", periods=10):
            decision = (day + pd.offsets.BDay(1)).to_pydatetime().replace(tzinfo=UTC)
            population.append(
                FrozenCompositionPopulation(
                    horizon=horizon.horizon,
                    trading_date=day.date(),
                    decision_as_of=decision,
                    available_at=decision - timedelta(minutes=1),
                    symbols=("A", "B", "C"),
                    source_evidence_sha256=content_id("independent-public-membership"),
                )
            )
    values = dict(
        created_at=now,
        selection_id=selection.selection_id,
        build_id=selection.build_id,
        data_snapshot_id=selection.data_snapshot_id,
        owner_confirmation_reference="TEST-ONLY-confirmation-never-owner-approval",
        components=tuple(parts),
        outputs=tuple(outputs),
        prediction_population=tuple(population),
    )
    return FrozenCompositionManifest.create(**values)


def test_frozen_daily_return_and_rank_composition_reaches_final_nav_once(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch, composition_builder=composition)
    receipt = run(f)
    assert receipt.status == "PASS"
    assert receipt.formal_adoption_status == "HOLD" and not receipt.adoption_eligible
    assert len(f["calls"]) == 6
    assert {task for _, task in f["calls"]} == {"regression", "ranking"}
    report = json.loads(f["report_path"].read_text(encoding="utf-8"))["report"]
    assert report["schema_version"] == "locked-holdout-report-v3"
    assert report["ensemble_results"] == [] and len(report["composition_results"]) == 4
    assert not report["adoption_eligible"]
    again = evaluate_locked_holdout(
        selection_path=f["selection_path"],
        build_manifest_path=f["build"],
        evaluation_root=tmp_path / "holdout",
        evaluator_code_commit="synthetic-final-evaluator",
        composition_path=f["composition_path"],
    )
    assert again.resumed and len(f["calls"]) == 6
    assert run(f).receipt_id == receipt.receipt_id
    # Omitting the manifest cannot start a second legacy evaluation.
    with pytest.raises(RuntimeError, match="authorization provenance mismatch"):
        evaluate_locked_holdout(
            selection_path=f["selection_path"],
            build_manifest_path=f["build"],
            evaluation_root=tmp_path / "holdout",
            evaluator_code_commit="synthetic-final-evaluator",
        )


def test_projected_holdout_keeps_full_identity_receipts_and_missing_labels(tmp_path, monkeypatch):
    original_loader = holdout_module.load_production_dataset_snapshot
    observed = []

    def projected_loader(path, *, columns=None):
        assert columns is not None
        assert {"as_of", "label_available_at_5d", "label_available_at_20d"} <= set(columns)
        snapshot, projected = original_loader(path, columns=columns)
        full_snapshot, full = original_loader(path)
        assert snapshot.snapshot_id == full_snapshot.snapshot_id
        assert len(columns) < len(full.columns)
        pd.testing.assert_frame_equal(projected, full.loc[:, list(columns)])
        for horizon in (5, 20):
            target = f"target_return_{horizon}d"
            assert projected[target].isna().sum() == full[target].isna().sum() > 0
        observed.append(tuple(columns))
        return snapshot, projected

    monkeypatch.setattr(holdout_module, "load_production_dataset_snapshot", projected_loader)
    f = fixture(tmp_path, monkeypatch, missing_labels=True, composition_builder=composition)
    receipt = run(f)
    assert receipt.status == "INCOMPLETE" and not receipt.adoption_eligible
    assert len(observed) == 1
    assert len(f["calls"]) == 6
    assert {task for _, task in f["calls"]} == {"regression", "ranking"}
    report = json.loads(f["report_path"].read_text(encoding="utf-8"))["report"]
    assert all(result["prediction"]["rows"] == 30 for result in report["composition_results"])


def test_missing_exit_labels_still_receive_all_composed_predictions(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch, missing_labels=True, composition_builder=composition)
    receipt = run(f)
    assert receipt.status == "INCOMPLETE"
    report = json.loads(f["report_path"].read_text(encoding="utf-8"))["report"]
    assert all(r["prediction"]["rows"] == 30 for r in report["composition_results"])
    assert any(c["unavailable_rows"] > 0 for c in report["label_coverage"])


@pytest.mark.parametrize("transform", ["identity", "within_date_average_percentile_v1"])
def test_composition_matches_mobile_scalar_math_ties_order_and_optional_calibration(transform):
    ranked = transform != "identity"
    role = "ranking" if ranked else "return"
    # Both schemas validate the identical portable recipe fields.
    source = dict(
        horizon=5,
        role=role,
        output_id="out",
        recipe_version="daily-forward-crossfit-v1",
        components=("a", "b"),
        weights=(0.3, 0.7),
        weight_source="learned",
        transform=transform,
        unit="rank_score" if ranked else "fractional_return",
        rank_universe="decision_symbols" if ranked else None,
        universe_rule_version="test" if ranked else None,
        universe_evidence_sha256=content_id("universe") if ranked else None,
    )
    EnsembleOutput(**source)
    t = datetime(2025, 1, 1, tzinfo=UTC)
    recipe = FrozenCompositionOutput(
        **source,
        source_evidence_sha256=content_id("dev"),
        latest_weight_label_available_at=t,
        weights_fitted_at=t,
        received_at=t,
    )
    a, b = [2.0, 2.0, 5.0, -1.0], [4.0, 1.0, 1.0, 8.0]
    day = pd.Timestamp("2025-01-06")
    frames = {
        name: pd.DataFrame(
            {"symbol": list("ABCD"), "trading_date": [day] * 4, "prediction": value}
        ).iloc[::-1]
        for name, value in (("a", a), ("b", b))
    }
    actual = compose_frozen_predictions(recipe, frames).prediction.tolist()
    matrices = [average_percentile(v) if ranked else v for v in (a, b)]
    expected = [sum(w * v[i] for w, v in zip((0.3, 0.7), matrices, strict=True)) for i in range(4)]
    assert actual == expected
    if ranked:
        calibration = dict(
            method="affine_rank_to_return",
            source_evidence_sha256=content_id("cal"),
            latest_label_available_at=t,
            fitted_at=t,
            slope=0.25,
            intercept=0.01,
        )
        data = recipe.model_dump()
        data.update(role="return", unit="fractional_return", calibration=calibration)
        calibrated = FrozenCompositionOutput.model_validate(data)
        mobile = EnsembleCalibration(**calibration)
        assert compose_frozen_predictions(calibrated, frames).prediction.tolist() == [
            mobile.apply(v) for v in expected
        ]
    with pytest.raises(ValueError, match="key sets differ"):
        compose_frozen_predictions(recipe, {**frames, "b": frames["b"].iloc[1:]})


def test_refreeze_snapshot_mismatch_and_composed_file_tamper_rejected(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch, composition_builder=composition)
    original = load_frozen_composition(f["composition_path"], f["selection"])
    with pytest.raises(ValueError, match="after holdout access"):
        write_frozen_composition(original, f["selection_path"])
    with pytest.raises(ValueError, match="snapshot mismatch"):
        load_frozen_composition(
            f["composition_path"], f["selection"].model_copy(update={"data_snapshot_id": "f" * 64})
        )
    report = json.loads(f["report_path"].read_text(encoding="utf-8"))["report"]
    path = Path(report["composition_results"][0]["prediction"]["prediction_path"])
    values = pd.read_parquet(path)
    values.loc[0, "prediction"] += 0.1
    values.to_parquet(path, index=False)
    with pytest.raises(RuntimeError, match="Parquet hash mismatch"):
        run(f)


def test_actual_mobile_runtime_and_final_composer_produce_identical_outputs():
    bundle, rows = ensemble_bundle(), fixture_rows()
    mobile = inference(bundle, rows, SELECTION, rank_universes=universes(rows))
    raw = {part["model_id"]: part for part in mobile["components"]}
    stamp = datetime(2025, 1, 1, tzinfo=UTC)
    for output in bundle.outputs:
        frames = {
            name: pd.DataFrame(
                {
                    "symbol": [s for s, _ in raw[name]["values"]],
                    "trading_date": [pd.Timestamp("2025-01-06")] * 3,
                    "prediction": [v for _, v in raw[name]["values"]],
                }
            )
            for name in output.components
        }
        recipe = FrozenCompositionOutput(
            **output.model_dump(),
            source_evidence_sha256=content_id("synthetic-development"),
            latest_weight_label_available_at=stamp,
            weights_fitted_at=stamp,
            received_at=stamp,
        )
        actual = compose_frozen_predictions(recipe, frames)
        expected = next(x for x in mobile["outputs"] if x["output_id"] == output.output_id)
        assert list(zip(actual.symbol, actual.prediction, strict=True)) == expected["values"]


def test_changed_weights_cannot_be_rehashed_after_access(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch, composition_builder=composition)
    values = json.loads(f["composition_path"].read_text(encoding="utf-8"))
    values["outputs"][0]["weights"] = [0.5, 0.5]
    values["composition_id"] = content_id(
        {k: v for k, v in values.items() if k != "composition_id"}
    )
    f["composition_path"].write_text(json.dumps(values), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen manifest"):
        evaluate_locked_holdout(
            selection_path=f["selection_path"],
            build_manifest_path=f["build"],
            evaluation_root=tmp_path / "holdout",
            evaluator_code_commit="synthetic-final-evaluator",
            composition_path=f["composition_path"],
        )


def test_final_composition_cannot_freeze_a_risk_only_horizon():
    selection = _selection_fixture(build_id="a" * 64, dataset_id="b" * 64)
    selection = selection.model_copy(update={
        "horizons": tuple(h for h in selection.horizons if h.horizon in (5, 20)),
    })
    data = composition(selection).model_dump(exclude={"composition_id"})
    parts = list(data["components"])
    risk = next(p for p in parts if p["component"]["horizon"] == 20)
    risk["component"]["task"] = "quantile"
    risk["component"]["component_name"] = "TEST_ONLY_QUANTILE20"
    data["components"] = [p for p in parts if p["component"]["horizon"] == 5] + [risk]
    output = next(o for o in data["outputs"] if o["horizon"] == 20 and o["role"] == "return")
    output.update(role="quantile", components=["TEST_ONLY_QUANTILE20"],
                  weights=[1.], weight_source="single")
    data["outputs"] = [o for o in data["outputs"] if o["horizon"] == 5] + [output]
    with pytest.raises(ValueError, match="daily priority"):
        FrozenCompositionManifest.create(**data)

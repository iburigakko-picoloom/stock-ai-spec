from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pytest
from mobile.python.research_ensemble import average_percentile

from stock_ai.ml import daily_ensemble as module
from stock_ai.ml.daily_ensemble import (
    POPULATION_KEYS,
    POPULATION_VERSION,
    PopulationComponent,
    crossfit_population_panel,
    population_combine,
    score_population_predictions,
    validate_population_panel,
)
from tests.test_daily_ensemble import _panel


def _inputs(horizon=20, *, tasks=("regression", "regression", "ranking")):
    frame, matrices = _panel(horizon)
    frame["horizon"] = horizon
    frame["data_snapshot_id"] = "frozen-feature-version"
    frame["label_evaluable"] = True
    components = [
        PopulationComponent(
            component_id=f"model-{i}",
            task=task,
            source_id=f"whole-fold-version-{i}",
            predictions=frame.loc[:, list(POPULATION_KEYS)].assign(prediction=matrices[task][:, i]),
        )
        for i, task in enumerate(tasks)
    ]
    return frame, components


def _run(frame, components, eligible=None, **kwargs):
    return crossfit_population_panel(
        frame,
        components,
        eligible_population=frame if eligible is None else eligible,
        population_id="independent-dated-topix500-v2",
        horizon=int(frame.horizon.iloc[0]),
        holdout_start="2026-01-01",
        batch_rows=71,
        **kwargs,
    )


@pytest.mark.parametrize("horizon", [5, 20])
def test_unscored_delisted_rows_are_predicted_ranked_and_never_change_fit_masks(horizon):
    frame, components = _inputs(horizon)
    missing = (frame.index >= 600) & frame.symbol.eq("D")
    frame.loc[missing, "target"] = np.nan
    frame.loc[missing, "label_evaluable"] = False
    frame.loc[missing, "label_available_at"] = pd.NaT
    for c in components:
        c.predictions.loc[missing, "prediction"] = 1000.0
    eligible = frame.copy()
    unavailable = eligible.iloc[[0]].copy()
    unavailable["symbol"] = "Z"
    unavailable["abstention_reason"] = "FEATURE_UNAVAILABLE: no frozen input row"
    eligible = pd.concat([eligible, unavailable], ignore_index=True)
    result, receipt = _run(frame, components, eligible)
    assert receipt["version"] == POPULATION_VERSION != module.VERSION
    assert receipt["eligible_rows"] == 1201 and receipt["predictable_rows"] == 1200
    assert len(receipt["feature_abstentions"]) == 1
    assert receipt["feature_abstentions"][0]["symbol"] == "Z"
    assert len(result) == 600
    assert result[result.symbol.eq("D")].target.isna().all()
    assert result[result.symbol.eq("D")].uniform_rank.eq(1.0).all()
    assert "weighted_probability" not in result and "uniform_quantile" not in result
    assert not receipt["adoption_eligible"]
    assert not receipt["all_18_configurations_compared"]
    json.dumps(receipt, allow_nan=False)
    assert receipt["scores"]["weighted_rank"]["unknown_label_rows"] == 150
    assert receipt["scores"]["weighted_rank"]["top_20"]["mean_target"] is None
    assert receipt["component_sources"][0]["source_id"] == "whole-fold-version-0"
    # Each emitted score is bit-identical to the mobile percentile and sequential sum.
    for fold in receipt["folds"]:
        weights = fold["models"]["rank"]["weights"]
        for _, part in result[result.meta_fold.eq(fold["meta_fold"])].groupby("trading_date"):
            transformed = [
                average_percentile(part[f"component__{c.component_id}"].tolist())
                for c in components
            ]
            expected = [
                sum(w * values[i] for w, values in zip(weights, transformed, strict=True))
                for i in range(len(part))
            ]
            assert part.weighted_rank.tolist() == expected
            # Removing unlabeled D first would change the other three daily percentiles.
            before_mask = average_percentile(part["component__model-0"].tolist())[:3]
            after_mask = average_percentile(part.iloc[:3]["component__model-0"].tolist())
            assert before_mask != after_mask
        assert fold["fit"]["dates"] >= 20 and fold["calibration"]["dates"] >= 20
        assert fold["embargo_observed_dates"] == horizon


@pytest.mark.parametrize("tasks", [("regression",), ("ranking",)])
def test_single_component_and_optional_heads_are_independent(tasks):
    frame, components = _inputs(tasks=tasks)
    result, receipt = _run(frame, components, expected_component_ids=["model-0", "not-compared"])
    assert len(result) == 600
    assert result.uniform_rank.equals(result.weighted_rank)
    assert ("weighted_return" in result) == (tasks == ("regression",))
    assert all(f["models"]["rank"]["weights"] == [1.0] for f in receipt["folds"])
    assert receipt["comparison_status"] == "PARTIAL"
    assert receipt["uncompared_component_ids"] == ["not-compared"]


def test_optional_risk_heads_use_their_own_mature_label_masks():
    frame, components = _inputs(tasks=("regression", "large_loss", "quantile"))
    missing = frame.index == len(frame) - 1
    frame.loc[missing, "target"] = np.nan
    frame.loc[missing, "label_evaluable"] = False
    frame.loc[missing, "label_available_at"] = pd.NaT
    result, receipt = _run(frame, components)
    assert result.calibrated_probability.between(0, 1).all()
    assert result.calibrated_quantile.notna().all()
    assert receipt["scores"]["calibrated_probability"]["label_evaluable_rows"] == 599
    assert receipt["scores"]["calibrated_quantile"]["unknown_label_rows"] == 1
    assert "isotonic" in receipt["folds"][0]["calibration_model"]
    json.dumps(receipt, allow_nan=False)


def test_top_n_is_fixed_before_unknown_labels_without_promoting_lower_names():
    n = 22
    frame = pd.DataFrame(
        {
            "trading_date": [pd.Timestamp("2025-01-01")] * n,
            "symbol": [f"S{i:02d}" for i in range(n)],
            "target": np.arange(n, dtype=float) / 100,
            "label_evaluable": [False] + [True] * (n - 1),
        }
    )
    frame.loc[0, "target"] = np.nan
    values = -np.arange(n, dtype=float)
    scores = score_population_predictions(
        frame,
        {"rank": (values, "ranking"), "return": (values / 100, "regression")},
        threshold=-0.08,
        alpha=0.1,
    )
    for item in scores.values():
        assert item["label_evaluable_rows"] == 21
        assert item["top_10"]["daily"][0]["selected_symbols"] == frame.symbol[:10].tolist()
        assert item["top_10"]["daily"][0]["label_evaluable_rows"] == 9
        assert item["top_10"]["mean_target"] is None
        assert item["top_20"]["mean_target"] is None
        ic = item["scores"]["rank_ic_on_label_evaluable_subset"]
        assert ic["input_rows"] == 21 and ic["excluded_rows"] == 0
        assert not any(k.startswith("top_") for k in ic["metrics"])
    assert scores["return"]["scores"]["return_errors"]["rows"] == 21


@pytest.mark.parametrize("bad", ["missing", "order", "nan", "infinity", "snapshot", "fold"])
def test_component_domain_must_match_without_silent_intersection(bad):
    frame, components = _inputs()
    data = components[0].predictions
    if bad == "missing":
        data.drop(index=data.index[-1], inplace=True)
    elif bad == "order":
        data.iloc[[0, 1]] = data.iloc[[1, 0]].to_numpy()
    elif bad in ("nan", "infinity"):
        data.loc[0, "prediction"] = np.nan if bad == "nan" else np.inf
    elif bad == "snapshot":
        data.loc[0, "data_snapshot_id"] = "another-snapshot"
    else:
        data.loc[0, "fold"] += 1
    with pytest.raises(ValueError, match=r"component keys|nonfinite"):
        _run(frame, components)


def test_feature_abstention_must_be_explicit_and_cannot_use_fake_prediction():
    frame, components = _inputs()
    eligible = frame.copy()
    eligible.loc[len(frame)] = frame.iloc[-1]
    eligible.loc[len(frame), "symbol"] = "Z"
    with pytest.raises(ValueError, match="abstentions require explicit reasons"):
        _run(frame, components, eligible)
    with pytest.raises(ValueError, match="belong to the independent"):
        _run(frame, components, frame.iloc[:-1])


@pytest.mark.parametrize("bad", ["holdout", "future_features", "naive", "early_label", "mask"])
def test_new_path_does_not_relax_holdout_or_point_in_time_rules(bad):
    frame, _ = _inputs()
    if bad == "holdout":
        frame.loc[0, "label_end"] = pd.Timestamp("2026-01-01")
    elif bad == "future_features":
        frame.loc[0, "available_at"] += pd.Timedelta(seconds=1)
    elif bad == "naive":
        frame["as_of"] = frame.as_of.dt.tz_localize(None)
    elif bad == "early_label":
        frame.loc[0, "label_available_at"] = frame.as_of.iloc[0]
    else:
        frame.loc[0, "target"] = np.nan
    with pytest.raises(ValueError):
        validate_population_panel(frame, horizon=20, holdout_start="2026-01-01")


def test_unreceived_labels_cannot_enter_weights_or_calibration(monkeypatch):
    frame, components = _inputs(tasks=("regression",))
    delayed = frame.symbol.eq("D") & (frame.index < 300)
    frame.loc[delayed, "label_available_at"] = pd.Timestamp("2025-12-01", tz="UTC")
    seen = []
    original = module.fit_simplex

    def spy(matrix, target, mask, **kwargs):
        assert not (mask & delayed.to_numpy()).any()
        seen.append(mask.copy())
        return original(matrix, target, mask, **kwargs)

    monkeypatch.setattr(module, "fit_simplex", spy)
    first, receipt = _run(frame, components)
    changed = frame.copy()
    changed.loc[delayed, "target"] += 1000
    second, other = _run(changed, components)
    # Unknown-at-fit outcomes do not enter rank targets, affine maps, or simplex loss.
    assert len(seen) == 12
    for a, b in zip(receipt["folds"], other["folds"], strict=True):
        assert a["models"] == b["models"]
        assert a["calibration_model"] == b["calibration_model"]
    assert first.weighted_rank.equals(second.weighted_rank)


@pytest.mark.parametrize("horizon,dates", [(5, 177), (20, 140)])
def test_short_independent_history_cannot_relax_twenty_calibration_dates(horizon, dates):
    frame, components = _inputs(horizon)
    frame = frame.iloc[: dates * 4].copy()
    short = [
        PopulationComponent(
            c.component_id, c.task, c.source_id, c.predictions.iloc[: len(frame)].copy()
        )
        for c in components
    ]
    if horizon == 20:
        with pytest.raises(ValueError, match="at least 20 eligible dates"):
            _run(frame, short)
    else:
        # Its shorter horizon can leave twenty eligible dates; do not assume both fail.
        _, receipt = _run(frame, short)
        assert all(f["calibration"]["dates"] >= 20 for f in receipt["folds"])


def test_canonical_arithmetic_matches_mobile_ties_and_declared_order_exactly():
    raw = [[1e16, 2.0, 2.0, 3.0, -1e16], [7.0, 7.0, 1.0, 4.0, 0.0], [2.0, 1.0, 3.0, 3.0, 4.0]]
    matrix = np.column_stack([average_percentile(c) for c in raw])
    weights = [0.123456789, 0.276543211, 0.6]
    expected = [
        sum(w * c[i] for w, c in zip(weights, [average_percentile(v) for v in raw], strict=True))
        for i in range(len(raw[0]))
    ]
    assert population_combine(matrix, weights).tolist() == expected
    assert population_combine(matrix[[0, 1]], weights).tolist() == expected[:2]
    with pytest.raises(ValueError, match="invalid population composition"):
        population_combine(matrix, [0.2, 0.2, 0.2])


def test_legacy_identity_and_strict_validation_are_unchanged():
    assert module.VERSION == "daily-forward-crossfit-v1"
    frame, _ = _inputs()
    original = copy.deepcopy(frame)
    frame.loc[0, "label_evaluable"] = False
    frame.loc[0, "target"] = np.nan
    validate_population_panel(frame, horizon=20, holdout_start="2026-01-01")
    with pytest.raises(ValueError, match="missing or duplicate"):
        module.validate_panel(frame, holdout_start="2026-01-01")
    assert original.target.notna().all()

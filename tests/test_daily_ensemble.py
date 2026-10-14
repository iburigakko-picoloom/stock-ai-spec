from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import minimize
from sklearn.isotonic import IsotonicRegression
from typer.testing import CliRunner

from stock_ai.cli import app
from stock_ai.ml import daily_ensemble as module
from stock_ai.ml.daily_ensemble import (
    TASKS,
    crossfit_panel,
    fit_calibration,
    fit_simplex,
    forward_splits,
    run_daily_ensemble,
    validate_panel,
)


@pytest.mark.parametrize("batch_rows", [1, 7, 4096])
def test_simplex_matches_direct_constrained_residual_optimizer(batch_rows):
    rng = np.random.default_rng(29)
    x = rng.normal(size=(397, 6)) * 0.04 + 0.07
    x[:, 4] = x[:, 3]  # Collinearity: compare predictions, not unidentifiable weights.
    x[:, 5] = 0.02
    y = x @ np.array([0.4, 0.3, 0.1, 0.1, 0.1, 0]) + rng.normal(0, 0.003, len(x))
    mask = np.arange(len(x)) < 300
    model = fit_simplex(x, y, mask, batch_rows=batch_rows)
    ref = minimize(
        lambda w: np.mean((x[mask] @ w - y[mask]) ** 2),
        np.full(6, 1 / 6),
        method="SLSQP",
        bounds=[(0, 1)] * 6,
        constraints={"type": "eq", "fun": lambda w: w.sum() - 1},
        options={"ftol": 1e-15, "maxiter": 1000},
    )
    assert ref.success and model["converged"]
    np.testing.assert_allclose(x @ model["weights"], x @ ref.x, atol=3e-7)
    assert model["mse"] == pytest.approx(np.mean((x[mask] @ model["weights"] - y[mask]) ** 2))
    assert model["normalized_dual_gap"] <= 2e-6


def test_simplex_constants_and_failure_are_explicit():
    x, y, mask = np.ones((40, 3)), np.ones(40), np.ones(40, dtype=bool)
    assert fit_simplex(x, y, mask)["mse"] == 0
    with pytest.raises(ValueError, match="invalid simplex"):
        fit_simplex(x, y, ~mask)
    x[:, 0] = np.linspace(0, 3, len(x))
    with pytest.raises(ValueError, match="optimizer failed"):
        fit_simplex(x, x[:, 0], mask, max_iterations=1)
    with pytest.raises(ValueError, match="invalid simplex"):
        fit_simplex(x, y, mask, batch_rows=0)
    x[0, 0] = np.nan
    with pytest.raises(ValueError, match="invalid simplex"):
        fit_simplex(x, y, mask)


def _panel(horizon=20):
    rng = np.random.default_rng(43)
    days = pd.bdate_range("2023-01-02", periods=300)
    frame = pd.DataFrame(
        {"trading_date": np.repeat(days, 4), "symbol": ["A", "B", "C", "D"] * len(days)}
    )
    frame["as_of"] = (
        frame.trading_date + pd.Timedelta(days=1, hours=11, minutes=30)
    ).dt.tz_localize("Asia/Tokyo")
    frame["available_at"] = frame.as_of
    frame["label_end"] = frame.trading_date.map(lambda d: d + pd.offsets.BDay(horizon + 1))
    frame["label_available_at"] = (frame.label_end + pd.Timedelta(hours=16)).dt.tz_localize(
        "Asia/Tokyo"
    )
    frame["target"] = rng.normal(0.004, 0.08, len(frame))
    frame["fold"] = np.repeat(np.arange(len(days)) // 20 + 1, 4)
    signal = 0.3 * frame.target.to_numpy()
    matrices = {
        "regression": signal[:, None] + rng.normal(0, 0.02, (len(frame), 3)),
        "ranking": signal[:, None] + rng.normal(0, 0.02, (len(frame), 3)),
        "large_loss": rng.uniform(0.04, 0.25, (len(frame), 3)),
        "quantile": rng.normal(-0.1, 0.03, (len(frame), 3)),
    }
    return frame, matrices


def _crossfit(frame, matrices, horizon=20):
    return crossfit_panel(
        frame,
        matrices,
        ["a", "b", "c"],
        horizon=horizon,
        threshold=-0.08,
        alpha=0.1,
        holdout_start="2026-01-01",
        batch_rows=71,
    )


@pytest.mark.parametrize("horizon", [5, 20])
def test_forward_fit_calibration_evaluation_are_disjoint_mature_and_embargoed(horizon):
    frame, _ = _panel(horizon)
    frame = validate_panel(frame, holdout_start="2026-01-01")
    covered = np.zeros(len(frame), dtype=bool)
    for fit, cal, evaluate, audit in forward_splits(frame, horizon=horizon):
        assert not (fit & cal | fit & evaluate | cal & evaluate).any()
        assert not (covered & evaluate).any()
        covered |= evaluate
        for mask, cutoff in ((fit, audit["weight_fit_cutoff"]), (cal, audit["calibration_cutoff"])):
            assert (frame.loc[mask, "label_available_at"] < pd.Timestamp(cutoff)).all()
        assert frame.loc[fit, "label_end"].max() < frame.loc[cal, "trading_date"].min()
        assert frame.loc[cal, "label_end"].max() < frame.loc[evaluate, "trading_date"].min()
        assert audit["embargo_observed_dates"] == horizon
        assert audit["fit"]["dates"] >= 20 and audit["calibration"]["dates"] >= 20
    assert covered.sum() == len(frame) // 2


@pytest.mark.parametrize(
    "change",
    [
        "naive",
        "missing_time",
        "future_feature",
        "early_receipt",
        "holdout",
        "duplicate",
        "unsorted",
        "inconsistent_cutoff",
    ],
)
def test_panel_rejects_bad_timing_keys_and_holdout(change):
    frame, _ = _panel()
    if change == "naive":
        frame["as_of"] = frame.as_of.dt.tz_localize(None)
    elif change == "missing_time":
        frame.loc[0, "label_available_at"] = pd.NaT
    elif change == "future_feature":
        frame.loc[0, "available_at"] += pd.Timedelta(seconds=1)
    elif change == "early_receipt":
        frame.loc[0, "label_available_at"] = frame.as_of.iloc[0]
    elif change == "holdout":
        frame.loc[0, "label_end"] = pd.Timestamp("2026-01-01")
    elif change == "duplicate":
        frame.loc[1, "symbol"] = "A"
    elif change == "unsorted":
        frame = frame.iloc[::-1].reset_index(drop=True)
    else:
        frame.loc[0, "as_of"] += pd.Timedelta(seconds=1)
    with pytest.raises(ValueError):
        validate_panel(frame, holdout_start="2026-01-01")


def test_short_history_invalid_matrix_and_risk_are_refused():
    frame, matrices = _panel()
    with pytest.raises(ValueError, match="insufficient dates"):
        _crossfit(frame.iloc[:80], {t: m[:80] for t, m in matrices.items()})
    with pytest.raises(ValueError, match="at least 20"):
        _crossfit(frame.iloc[:600], {t: m[:600] for t, m in matrices.items()})
    matrices["large_loss"][0, 0] = 1.1
    with pytest.raises(ValueError, match="invalid aligned"):
        _crossfit(frame, matrices)
    with pytest.raises(ValueError, match="only 5d and 20d"):
        forward_splits(frame, horizon=1)


def test_calibration_replays_isotonic_quantile_offset_and_return_units():
    rank = np.linspace(-1, 1, 201)
    probability = np.linspace(0, 1, len(rank))
    target = 0.012 + 0.05 * rank + 0.08 * np.sin(np.arange(len(rank)))
    q = np.full(len(rank), -0.09)
    model = fit_calibration(rank, probability, q, target, threshold=-0.08, alpha=0.1)
    raw = IsotonicRegression(out_of_bounds="clip").fit(probability, target <= -0.08)
    probe = np.linspace(-0.1, 1.1, 333)
    calibrated = np.interp(probe, model["isotonic"]["x"], model["isotonic"]["y"])
    np.testing.assert_allclose(calibrated, raw.predict(probe))
    assert (np.diff(calibrated) >= 0).all()
    slope, intercept = np.polyfit(rank, target, 1)
    assert model["rank_to_return"]["slope"] == pytest.approx(slope)
    assert model["rank_to_return"]["intercept"] == pytest.approx(intercept)
    assert model["quantile_offset"] == pytest.approx(np.quantile(target - q, 0.1))
    residual = target - (slope * rank + intercept)
    assert model["return_residual"]["rmse"] == pytest.approx(np.sqrt(np.mean(residual**2)))
    constant = fit_calibration(rank, probability, q, np.ones(len(rank)), threshold=-0.08, alpha=0.1)
    assert constant["isotonic"]["single_class"] and constant["isotonic"]["y"] == [0.0, 0.0]
    reverse = fit_calibration(rank, probability, q, -rank, threshold=-0.08, alpha=0.1)
    assert reverse["rank_to_return"]["slope"] == 0


def test_crossfit_replay_same_cohort_and_rank_mse_is_not_return_mse():
    frame, matrices = _panel()
    output, audit = _crossfit(frame, matrices)
    assert len(output) == 600 and audit["burn_in_rows"] == 600
    assert set(output.meta_fold) == {1, 2, 3}
    assert not output.duplicated(["trading_date", "symbol"]).any()
    for fold in audit["folds"]:
        part = output.loc[output.meta_fold == fold["meta_fold"]]
        source = frame.trading_date.isin(part.trading_date)
        weights = fold["models"]["return"]["weights"]
        np.testing.assert_allclose(part.weighted_return, matrices["regression"][source] @ weights)
        assert min(weights) >= 0 and sum(weights) == pytest.approx(1)
        model = fold["calibration_model"]
        np.testing.assert_allclose(
            part.calibrated_quantile, part.uniform_quantile + model["quantile_offset"]
        )
        np.testing.assert_allclose(
            part.calibrated_probability,
            np.interp(part.weighted_probability, model["isotonic"]["x"], model["isotonic"]["y"]),
        )
    for metric in audit["scores"]["ranking"].values():
        assert metric["prediction_units"] == "rank_score"
        assert "mean_squared_error" not in metric["metrics"]
        assert metric["input_rows"] == 600
    assert audit["scores"]["regression"]["weighted_return"]["input_rows"] == 600
    assert audit["scores"]["large_loss"]["calibrated_probability"]["rows"] == 600
    json.dumps(audit, allow_nan=False)


def test_future_outcomes_and_unreceived_peer_labels_cannot_change_earlier_models(monkeypatch):
    # Metrics are tested separately. This test isolates all training/calibration and predictions.
    monkeypatch.setattr(module, "score_ensemble", lambda *args, **kwargs: {})
    frame, matrices = _panel()
    frame.loc[0, "label_available_at"] = pd.Timestamp("2025-12-01", tz="Asia/Tokyo")
    before, a = _crossfit(frame, matrices)
    modified = frame.copy()
    modified.loc[0, "target"] = -5  # An unreceived peer must not alter another row's rank target.
    modified.loc[modified.trading_date == modified.trading_date.max(), "target"] = 3
    after, b = _crossfit(modified, matrices)
    for left, right in zip(a["folds"], b["folds"], strict=True):
        assert left["models"] == right["models"]
        assert left["calibration_model"] == right["calibration_model"]
    pd.testing.assert_frame_equal(before.drop(columns="target"), after.drop(columns="target"))
    changed = {t: m.copy() for t, m in matrices.items()}
    changed["regression"][-4:] *= 10
    last, _ = _crossfit(frame, changed)
    pd.testing.assert_frame_equal(before.iloc[:-4], last.iloc[:-4])


@pytest.fixture(scope="module")
def authentic_ensemble(tmp_path_factory, request):
    import tests.test_daily_baselines as fixtures

    template = fixtures._dataset()
    frame = pd.concat([template] * 5, ignore_index=True)
    frame["trading_date"] = np.repeat(pd.bdate_range("2023-01-02", periods=750), 3)
    frame["as_of"] = (
        frame.trading_date + pd.Timedelta(days=1, hours=11, minutes=30)
    ).dt.tz_localize("Asia/Tokyo")
    frame["available_at"] = frame.as_of
    for horizon in (1, 5, 20):
        ends = frame.trading_date.map(lambda d, h=horizon: d + pd.offsets.BDay(h + 1))
        frame[f"label_end_date_{horizon}d"] = ends
        frame[f"label_available_at_{horizon}d"] = (ends + pd.Timedelta(hours=16)).dt.tz_localize(
            "Asia/Tokyo"
        )
    # Scope the factory override; no global fixture mutation survives setup.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fixtures, "_dataset", lambda: frame)
        return fixtures.authentic.__wrapped__(tmp_path_factory, request)[0]


def test_authenticated_end_to_end_cli_and_original_sources_unchanged(authentic_ensemble, tmp_path):
    request = authentic_ensemble
    result = CliRunner().invoke(
        app,
        [
            "research",
            "crossfit-daily-ensemble",
            "--feature-selection",
            str(request["feature_selection_path"]),
            "--candidate-campaign",
            str(request["campaign_paths"][0]),
            "--dataset",
            str(request["dataset_path"]),
            "--output-root",
            str(tmp_path / "ensemble"),
            "--batch-rows",
            "71",
        ],
    )
    assert result.exit_code == 0, result.output
    path = next((tmp_path / "ensemble" / "receipts").glob("*.json"))
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == "daily-forward-crossfit-v1"
    assert receipt["holdout_scored"] is False and receipt["adoption_eligible"] is False
    for horizon in receipt["results"]:
        assert len(horizon["candidate_order"]) == 9 and len(horizon["folds"]) == 3
        output = pd.read_parquet(horizon["oof_path"])
        assert not output.symbol.str.startswith("PROTECTED").any()
        assert output.trading_date.max() < pd.Timestamp(receipt["locked_holdout_start"])
        assert len(output) == horizon["evaluation_rows"]
        for task in TASKS:
            assert all(f"{task}__{name}" in output for name in horizon["candidate_order"])
    for source, digest in receipt["input_byte_sha256"].items():
        assert module._file_sha256(Path(source)) == digest
    states = [
        json.loads(p.read_text())["status"] for p in (tmp_path / "ensemble" / "runs").glob("*.json")
    ]
    assert sorted(states) == ["STARTED", "SUCCEEDED"]


def test_authentication_rejects_duplicate_campaign_and_cli_preserves_failure(
    authentic_ensemble, tmp_path
):
    request = {**authentic_ensemble, "campaign_paths": authentic_ensemble["campaign_paths"] * 2}
    with pytest.raises(ValueError, match="duplicate ensemble candidate"):
        run_daily_ensemble(**request, output_root=tmp_path / "duplicate")
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    result = CliRunner().invoke(
        app,
        [
            "research",
            "crossfit-daily-ensemble",
            "--feature-selection",
            str(bad),
            "--candidate-campaign",
            str(bad),
            "--dataset",
            str(bad),
            "--output-root",
            str(tmp_path / "failure"),
        ],
    )
    assert result.exit_code == 2
    states = [
        json.loads(p.read_text())["status"] for p in (tmp_path / "failure" / "runs").glob("*.json")
    ]
    assert sorted(states) == ["FAILED", "STARTED"]


@pytest.mark.parametrize("change,error", [("as_of", "candidate/task keys"),
                                        ("naive", "timezone-aware"),
                                        ("target", "source keys/targets"),
                                        ("incomplete", "matrix is incomplete")])
def test_aligned_sources_cannot_bypass_timing_or_dataset_identity(
    authentic_ensemble, tmp_path, monkeypatch, change, error
):
    original = module.load_advanced_research_run

    def altered(path):
        report, frame = original(path)
        if change == "as_of":
            frame.loc[frame.index[0], "as_of"] += pd.Timedelta(seconds=1)
        elif change == "naive":
            frame["as_of"] = frame.as_of.dt.tz_localize(None)
        elif change == "target":
            # Mutate every task/candidate consistently; source projection must still reject it.
            selected = (frame.symbol == "A") & (frame.trading_date == frame.trading_date.min())
            frame.loc[selected, "target"] += 0.1
        return report, frame

    monkeypatch.setattr(module, "load_advanced_research_run", altered)
    request = dict(authentic_ensemble)
    if change == "incomplete":
        request["campaign_paths"] = ()
    with pytest.raises(ValueError, match=error):
        run_daily_ensemble(**request, output_root=tmp_path / change)

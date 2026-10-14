import duckdb
import numpy as np
import pandas as pd
import pytest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from stock_ai.ml.daily_baselines import _rule_metrics, evaluate_baseline_folds, fit_streamed_ridge
from stock_ai.ml.daily_simple_baselines import (
    RULE_FEATURES,
    RULES,
    fit_streamed_elastic_net,
    fixed_rule_scores,
)
from tests.test_daily_baselines import authentic as authentic


@pytest.mark.parametrize("block", [1, 31, 1024])
def test_full_data_objective_matches_independent_sklearn(block):
    rng = np.random.default_rng(17)
    x = rng.normal(size=(501, 6))
    x[:, 1] += 100_000_000
    x[:, 2] = 7
    x[:, 3] = np.nan
    x[::3, 4] = np.nan
    y = 0.03 * x[:, 0] + 0.02 * (x[:, 1] - 100_000_000) + rng.normal(0, 0.01, len(x))
    medians = np.array(
        [np.nanmedian(x[:, i]) if np.isfinite(x[:, i]).any() else 0 for i in range(x.shape[1])]
    )

    def batches():
        return ((x[i : i + block], y[i : i + block]) for i in range(0, len(x), block))

    transform = fit_streamed_ridge(batches(), medians)
    fitted = fit_streamed_elastic_net(batches(), transform)
    baseline = make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
        StandardScaler(),
        ElasticNet(alpha=0.001, l1_ratio=0.5, tol=1e-12, max_iter=50000),
    ).fit(x, y)
    future = x[:50].copy()
    future[0, 0] = np.nan
    np.testing.assert_allclose(
        fitted.predict(future, transform), baseline.predict(future), atol=2e-8, rtol=2e-8
    )
    coef = baseline[-1].coef_
    objective = (
        np.mean((baseline.predict(x) - y) ** 2) / 2
        + 0.0005 * np.abs(coef).sum()
        + 0.00025 * (coef @ coef)
    )
    assert abs(fitted.objective - objective) < 1e-10
    assert fitted.kkt_residual <= 1e-9
    assert fitted.objective_gap_bound <= 1e-12
    assert fitted.receipt()["rows"] == len(x)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"alpha": 0},
        {"alpha": float("inf")},
        {"l1_ratio": 0},
        {"l1_ratio": 1},
        {"l1_ratio": float("nan")},
        {"tolerance": 0},
        {"max_iter": 0},
    ],
)
def test_invalid_configuration(kwargs):
    x = np.arange(60, dtype=float).reshape(20, 3)
    y = np.sin(x[:, 0])
    transform = fit_streamed_ridge([(x, y)], np.median(x, axis=0))
    with pytest.raises(ValueError, match="configuration"):
        fit_streamed_elastic_net([(x, y)], transform, **kwargs)


def test_empty_invalid_inputs_and_nonconvergence():
    rng = np.random.default_rng(3)
    x = rng.normal(size=(100, 4))
    y = 0.1 * x[:, 0] + 0.2 * x[:, 1]
    transform = fit_streamed_ridge([(x, y)], np.median(x, axis=0))
    for batches in [
        [],
        [(x[:2], y[:2])],
        [(x, y[:2])],
        [(x, np.full(len(x), np.inf))],
        [(x[:, 0], y)],
        [(np.full_like(x, np.inf), y)],
    ]:
        with pytest.raises(ValueError):
            fit_streamed_elastic_net(batches, transform)
    with pytest.raises(ValueError, match="converge"):
        fit_streamed_elastic_net([(x, y)], transform, max_iter=1, tolerance=1e-14)


def test_constant_targets_and_empty_columns():
    x = np.full((40, 2), np.nan)
    y = np.full(40, 0.01)
    transform = fit_streamed_ridge([(x, y)], np.zeros(2))
    fitted = fit_streamed_elastic_net([(x, y)], transform)
    assert not fitted.coefficient.any()
    np.testing.assert_allclose(fitted.predict(x, transform), y, atol=1e-15)


def universe():
    frame = pd.DataFrame(
        {
            "trading_date": pd.to_datetime(["2026-01-01"] * 4),
            "as_of": pd.to_datetime(["2026-01-01T02:30:00Z"] * 4),
            "symbol": ["A", "B", "C", "D"],
        }
    )
    frame["available_at"] = frame.as_of
    for col in RULE_FEATURES:
        frame[col] = [1.0, 1.0, 3.0, np.nan]
    return frame


def test_rules_midrank_missing_constant_and_singleton():
    frame = universe()
    result, audit = fixed_rule_scores(frame)
    for name in ["momentum_revision_rank", "equal_weight_rule_rank"]:
        np.testing.assert_allclose(result[name], [-0.5, -0.5, 1, 0])
    assert audit["universe_rows"] == 4 and not audit["universe_uses_labels"]
    assert audit["feature_coverage"][RULE_FEATURES[0]]["neutral_missing_rows"] == 1
    for values in [[1, 1, 1, 1], [np.nan] * 4, [1, np.nan, np.nan, np.nan]]:
        for col in RULE_FEATURES:
            frame[col] = values
        assert fixed_rule_scores(frame)[0].equal_weight_rule_rank.eq(0).all()


def test_rules_do_not_depend_on_labels_or_future_dates_and_are_order_invariant():
    frame = universe()
    before = fixed_rule_scores(frame)[0]
    frame["target_return_20d"] = [np.nan, 999, -999, 0]
    pd.testing.assert_frame_equal(before, fixed_rule_scores(frame)[0])
    future = frame.copy()
    for col in ["trading_date", "as_of", "available_at"]:
        future[col] += pd.Timedelta(days=1)
    for col in RULE_FEATURES:
        future[col] = [10, 50, -3, 2]
    combined = fixed_rule_scores(pd.concat([frame, future], ignore_index=True))[0]
    pd.testing.assert_frame_equal(before, combined.iloc[:4])
    shuffled = fixed_rule_scores(frame.sample(frac=1, random_state=7))[0].sort_values("symbol")
    pd.testing.assert_frame_equal(before.reset_index(drop=True), shuffled.reset_index(drop=True))


@pytest.mark.parametrize(
    "case", ["duplicate", "late", "mixed_cutoff", "infinite", "missing_column", "null_date"]
)
def test_rule_invalid_universe(case):
    frame = universe()
    if case == "duplicate":
        frame.loc[1, "symbol"] = "A"
    if case == "late":
        frame.loc[0, "available_at"] += pd.Timedelta(minutes=1)
    if case == "mixed_cutoff":
        frame.loc[0, "as_of"] += pd.Timedelta(minutes=1)
    if case == "infinite":
        frame.loc[0, RULE_FEATURES[0]] = np.inf
    if case == "missing_column":
        frame = frame.drop(columns=RULE_FEATURES[0])
    if case == "null_date":
        frame.loc[0, "trading_date"] = pd.NaT
    with pytest.raises(ValueError):
        fixed_rule_scores(frame)


def evaluate(frame, report, reference):
    with duckdb.connect(config={"threads": 1}) as connection:
        connection.register("source", frame)
        return evaluate_baseline_folds(connection, report, reference, batch_rows=41)


def test_new_baselines_cover_same_rows_and_replay(authentic):
    _, frame, report, reference = authentic
    result, folds = evaluate(frame, report, reference)
    assert len(result) == len(reference)
    assert np.isfinite(result[["elastic_net_v0", *RULES]]).all().all()
    for fold in folds:
        assert fold["elastic_net"]["rows"] == fold["training_rows"]
        assert fold["elastic_net"]["kkt_residual"] <= 1e-9
        assert not fold["rule_universe"]["universe_uses_labels"]
        assert all("mse" not in value for value in fold["rule_scores"].values())
    assert set(_rule_metrics(result)) == set(RULES)


def test_unscored_peers_are_ranked_before_joining_labels(authentic):
    _, frame, report, reference = authentic
    before, _ = evaluate(frame, report, reference)
    scoring_day = before.trading_date.min()
    peer = frame.loc[frame.trading_date == scoring_day].iloc[:1].copy()
    peer["symbol"] = "UNSCORED"
    for name in RULE_FEATURES:
        peer[name] = -1000
    for horizon in [1, 5, 20]:
        peer[f"target_return_{horizon}d"] = np.nan
        peer[f"label_status_{horizon}d"] = "UNAVAILABLE"
    changed = pd.concat([frame, peer], ignore_index=True)
    after, _ = evaluate(changed, report, reference)
    assert not before.equal_weight_rule_rank.equals(after.equal_weight_rule_rank)
    pd.testing.assert_series_equal(before.elastic_net_v0, after.elastic_net_v0)
    assert not after.symbol.eq("UNSCORED").any()
    direct, _ = fixed_rule_scores(changed.loc[changed.trading_date == scoring_day])
    actual = after.loc[after.trading_date == scoring_day].set_index("symbol")
    np.testing.assert_allclose(
        actual.equal_weight_rule_rank,
        direct.set_index("symbol").loc[actual.index].equal_weight_rule_rank,
    )


def test_late_unscored_peer_is_not_silently_discarded(authentic):
    _, frame, report, reference = authentic
    day = pd.to_datetime(reference.trading_date).min()
    peer = frame.loc[frame.trading_date == day].iloc[:1].copy()
    peer["symbol"] = "LATE"
    peer["available_at"] = pd.to_datetime(peer.as_of, utc=True) + pd.Timedelta(days=1)
    for horizon in [1, 5, 20]:
        peer[f"target_return_{horizon}d"] = np.nan
        peer[f"label_status_{horizon}d"] = "UNAVAILABLE"
    with pytest.raises(ValueError, match="cutoffs"):
        evaluate(pd.concat([frame, peer], ignore_index=True), report, reference)


def test_future_targets_cannot_change_fitted_elastic_or_past_rule_scores(authentic):
    _, frame, report, reference = authentic
    before, old_folds = evaluate(frame, report, reference)
    day = before.trading_date.max()
    modified, new_reference = frame.copy(), reference.copy()
    horizon = report.config.horizons[0]
    modified.loc[modified.trading_date == day, f"target_return_{horizon}d"] += 1
    new_reference.loc[new_reference.trading_date == day, "target"] += 1
    after, new_folds = evaluate(modified, report, new_reference)
    assert [f["elastic_net"] for f in old_folds] == [f["elastic_net"] for f in new_folds]
    for name in ("elastic_net_v0", *RULES):
        pd.testing.assert_series_equal(before[name], after[name])


def test_overflowing_training_statistics_fail_without_false_convergence():
    x = np.arange(40, dtype=float).reshape(20, 2)
    y = x[:, 0] / 10
    transform = fit_streamed_ridge([(x, y)], np.median(x, axis=0))
    with np.errstate(over="ignore", invalid="ignore"):
        with pytest.raises(ValueError, match="sufficient statistics"):
            fit_streamed_elastic_net([(np.full_like(x, 1e200), y)], transform)

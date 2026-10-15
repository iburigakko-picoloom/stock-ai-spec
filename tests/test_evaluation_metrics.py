from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from stock_ai.cli import app
from stock_ai.ml.advanced import summarize_oof_predictions
from stock_ai.ml.evaluation_metrics import (
    LOG_LOSS_EPSILON,
    evaluate_probabilities,
    evaluate_quantiles,
    evaluate_ranking_panel,
)
from stock_ai.ml.research_metrics import evaluate_cross_sectional_predictions


def panel(target: list[float], prediction: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trading_date": ["2026-01-05"] * len(target),
            "symbol": [f"S{index:03d}" for index in range(len(target))],
            "target": target,
            "prediction": prediction,
        }
    )


def test_negative_return_ranking_uses_grades_and_top_set_overlap() -> None:
    result = evaluate_ranking_panel(panel([-6, -5, -4, -3, -2, -1], [6, 5, 4, 3, 2, 1]))
    assert result.metrics is not None
    metric = result.metrics
    # Average-percentile grades: 0,1,2,3,4,4. Gains: 0,1,3,7,15,15.
    discounts = [1 / math.log2(position + 2) for position in range(6)]
    actual5 = sum(gain * d for gain, d in zip([0, 1, 3, 7, 15], discounts[:5], strict=True))
    ideal5 = sum(gain * d for gain, d in zip([15, 15, 7, 3, 1], discounts[:5], strict=True))
    assert metric.ndcg_at_5 == pytest.approx(actual5 / ideal5)
    assert metric.ndcg_at_10 == pytest.approx((actual5 + 15 * discounts[5]) / ideal5)
    assert metric.ndcg_at_20 == metric.ndcg_at_10
    assert metric.precision_at_5 == pytest.approx(4 / 5)
    assert metric.precision_at_10 == metric.precision_at_20 == 1
    assert metric.top_5_mean_target == -4
    assert metric.mean_daily_rank_ic == pytest.approx(-1)
    assert metric.rank_icir is None
    # All outcomes are losses, yet set-overlap Precision is nonzero: not a win rate.
    assert all(value < 0 for value in [-6, -5, -4, -3, -2, -1])


def test_perfect_negative_return_ranking_and_ties_are_row_order_invariant() -> None:
    data = panel([-6, -5, -4, -3, -2, -1], [-6, -5, -4, -3, -2, -1])
    perfect = evaluate_ranking_panel(data).metrics
    assert perfect is not None
    assert perfect.ndcg_at_5 == perfect.precision_at_5 == 1
    data["prediction"] = 0
    data.index = [0] * len(data)  # Caller indexes are not model row identities.
    tied = evaluate_ranking_panel(data)
    assert tied == evaluate_ranking_panel(data.iloc[::-1])
    assert tied.metrics is not None and tied.metrics.mean_daily_rank_ic is None
    assert tied.metrics.precision_at_5 == pytest.approx(4 / 5)
    data["target"] = [0, 0, 0, 0, 1, 1]
    assert evaluate_ranking_panel(data) == evaluate_ranking_panel(data.iloc[::-1])


@pytest.mark.parametrize("count", [1, 2, 3])
def test_minimum_cross_section_is_explicit(count: int) -> None:
    values = list(range(count))
    data = panel(values, values)
    result = evaluate_ranking_panel(data)
    assert result.metrics is not None
    assert result.metrics.mean_daily_rank_ic == (None if count < 3 else pytest.approx(1))
    assert result.metrics.precision_at_5 == (None if count < 2 else 1)
    if count == 2:
        historical = evaluate_cross_sectional_predictions(
            dates=data.trading_date, target=data.target, prediction=data.prediction
        )
        assert historical.mean_daily_rank_ic == pytest.approx(1)  # Historical policy unchanged.


def test_equal_date_and_row_weighted_ic_are_separate() -> None:
    first = panel([1, 2, 3], [1, 2, 3])
    second = panel([1, 2, 3, 4, 5, 6], [6, 5, 4, 3, 2, 1])
    second["trading_date"] = "2026-01-06"
    result = evaluate_ranking_panel(pd.concat([first, second]))
    assert result.metrics is not None
    assert result.metrics.mean_daily_rank_ic == pytest.approx(0)
    assert result.metrics.rank_ic_standard_deviation == pytest.approx(math.sqrt(2))
    assert result.metrics.rank_icir == pytest.approx(0)
    assert result.row_weighted_rank_ic == pytest.approx(-1 / 3)


@pytest.mark.parametrize(
    "target,prediction",
    [
        ([1, 1, 1], [1, 2, 3]),
        ([1, 2, 3], [1, 1, 1]),
        ([float("nan")] * 3, [1, 2, 3]),
        ([1, 2, 3], [float("inf")] * 3),
    ],
)
def test_degenerate_and_nonfinite_sections_never_become_zero_ic(target, prediction) -> None:
    result = evaluate_ranking_panel(panel(target, prediction))
    assert result.daily_ic[0][2] is None
    assert result.row_weighted_rank_ic is None
    if result.excluded_rows:
        assert result.metrics is None and result.excluded_rows == 3
    else:
        assert result.metrics is not None and result.metrics.mean_daily_rank_ic is None


def test_partial_missing_rows_and_empty_dates_remain_visible() -> None:
    data = panel([1, 2, 3, 4], [1, 2, 3, float("nan")])
    empty_day = panel([1], [float("inf")])
    empty_day["trading_date"] = "2026-01-06"
    result = evaluate_ranking_panel(pd.concat([data, empty_day]))
    assert result.input_rows == 5 and result.excluded_rows == 2
    assert result.daily_ic == (("2026-01-05", 3, pytest.approx(1)), ("2026-01-06", 0, None))


@pytest.mark.parametrize("mutation", ["empty", "duplicate", "date", "time", "symbol", "blank"])
def test_bad_ranking_keys_are_rejected(mutation: str) -> None:
    data = panel([1, 2, 3], [1, 2, 3])
    if mutation == "empty":
        data = data.iloc[:0]
    elif mutation == "duplicate":
        data = pd.concat([data, data.iloc[:1]])
    elif mutation == "date":
        data.loc[0, "trading_date"] = None
    elif mutation == "time":
        data["trading_date"] = "2026-01-05 11:30"
    elif mutation == "blank":
        data["trading_date"] = ""
    else:
        data.loc[0, "symbol"] = " "
    with pytest.raises(ValueError):
        evaluate_ranking_panel(data)


@pytest.mark.parametrize("correct", [True, False])
def test_probability_endpoints_have_raw_brier_and_fixed_float64_log_clip(correct: bool) -> None:
    prediction = [0, 1] if correct else [1, 0]
    result = evaluate_probabilities([0, 1], prediction)
    eps = LOG_LOSS_EPSILON
    expected = (
        -(math.log(1 - eps) + math.log1p(-eps)) / 2
        if correct
        else (-(math.log(eps) + math.log1p(-(1 - eps))) / 2)
    )
    assert result.brier_score == (0 if correct else 1)
    assert result.log_loss == pytest.approx(expected, rel=1e-12)
    assert result.expected_calibration_error == (0 if correct else 1)
    assert result == evaluate_probabilities(
        np.array([0, 1]), np.array(prediction, dtype=np.float32)
    )
    assert sum(item.count for item in result.calibration_bins) == 2


@pytest.mark.parametrize("probability,brier,ece", [(0.25, 0.1875, 0), (0.9, 0.61, 0.65)])
def test_base_rate_and_overconfidence_hand_values(probability: float, brier: float, ece: float):
    result = evaluate_probabilities([0, 0, 0, 1], [probability] * 4)
    assert result.base_rate == 0.25
    assert result.brier_score == pytest.approx(brier)
    assert result.expected_calibration_error == pytest.approx(ece)
    assert result.log_loss == pytest.approx(
        -0.75 * math.log(1 - probability) - 0.25 * math.log(probability)
    )


@pytest.mark.parametrize(
    "event,probability",
    [
        ([], []),
        ([0], [0, 1]),
        ([0, 2], [0, 1]),
        ([0], [-0.1]),
        ([1], [1.1]),
        ([float("nan")], [0.1]),
        ([0], [float("inf")]),
        ([[0]], [[0.1]]),
    ],
)
def test_invalid_probabilities_are_not_silently_clipped(event, probability) -> None:
    with pytest.raises(ValueError):
        evaluate_probabilities(event, probability)


def test_quantile_pinball_and_strict_inclusive_coverage_hand_values() -> None:
    result = evaluate_quantiles([-2, 0, 2], [0.1, 0.5, 0.9], [[-1, 0, 1]] * 3)
    assert result.crossing_check_available and result.crossed_rows == 0
    assert [item.pinball_loss for item in result.scores] == pytest.approx([1.3 / 3, 2 / 3, 1.3 / 3])
    assert [item.strictly_below_rate for item in result.scores] == pytest.approx(
        [1 / 3, 1 / 3, 2 / 3]
    )
    assert [item.at_or_below_rate for item in result.scores] == pytest.approx([1 / 3, 2 / 3, 2 / 3])


def test_crossing_quantiles_are_detected_without_repairing_predictions() -> None:
    values = [[2, 1], [0, 1], [0, 0]]
    result = evaluate_quantiles([0, 0, 0], [0.1, 0.9], values)
    assert result.crossed_rows == 1
    assert result.scores[0].pinball_loss == pytest.approx(1.8 / 3)
    assert values == [[2, 1], [0, 1], [0, 0]]
    single = evaluate_quantiles([0], [0.1], [[0]])
    assert not single.crossing_check_available and single.crossed_rows == 0
    assert single.scores[0].strictly_below_rate == 0
    assert single.scores[0].at_or_below_rate == 1


@pytest.mark.parametrize(
    "levels,prediction",
    [
        ([0.9, 0.1], [[0, 1]]),
        ([0.1, 0.1], [[0, 1]]),
        ([0], [[0]]),
        ([1], [[0]]),
        ([0.1], [[float("nan")]]),
        ([0.1], [0]),
        ([], [[]]),
        ([float("nan")], [[0]]),
    ],
)
def test_invalid_quantile_contracts_are_rejected(levels, prediction) -> None:
    with pytest.raises(ValueError):
        evaluate_quantiles([0], levels, prediction)


def test_historical_report_probability_and_quantile_conventions_remain_reproducible() -> None:
    data = panel([-0.08, 0], [1, 0]).assign(
        horizon=20,
        model_family="lightgbm",
        task="large_loss",
        seed=17,
        fold=1,
    )
    old = summarize_oof_predictions(data, quantile_alpha=0.1, large_loss_threshold=-0.08)
    eps = LOG_LOSS_EPSILON
    # The historical sklearn binary scorer evaluates both class probabilities;
    # their floating-point complements add rounding at roughly 1e-24 absolute.
    assert old.brier_score == pytest.approx(((1 - (1 - eps)) ** 2 + eps**2) / 2, abs=1e-24)
    assert old.log_loss == pytest.approx(-math.log(1 - eps))
    # The event includes an outcome exactly equal to the frozen threshold.
    new = evaluate_probabilities([1, 0], [1, 0])
    assert new.brier_score == 0 and new.log_loss == pytest.approx(old.log_loss)
    data = panel([-2, 0, 2], [-1, -1, -1]).assign(
        horizon=20,
        model_family="lightgbm",
        task="quantile",
        seed=17,
        fold=1,
    )
    old = summarize_oof_predictions(data, quantile_alpha=0.1, large_loss_threshold=-0.08)
    assert old.pinball_loss == pytest.approx(1.3 / 3)
    assert old.lower_tail_rate == pytest.approx(1 / 3)


def test_cli_explicitly_requests_development_scoring(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "input.json"
    source.write_text("{}", encoding="utf-8")
    calls = []

    def audit(**kwargs):
        calls.append(kwargs)
        return {"status": "PASS", "adoption_eligible": False}

    monkeypatch.setattr("stock_ai.cli.audit_candidate_campaigns", audit)
    result = CliRunner().invoke(
        app,
        [
            "research",
            "audit-candidates",
            "--feature-selection",
            str(source),
            "--candidate-campaign",
            str(source),
            "--score-development",
            "--audit-root",
            str(tmp_path / "audit"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls[0]["score_development"] is True
    assert len(list((tmp_path / "audit").glob("*.json"))) == 1

"""Return calibration cannot be inferred from a correct ordering."""

import pytest

from stock_ai.ml.evaluation_metrics import evaluate_return_errors


def test_correct_order_with_wrong_scale_is_worse_than_zero_return():
    result = evaluate_return_errors([-0.1, 0.1], [-1, 1])
    assert result["mae"] == pytest.approx(0.9)
    assert result["rmse"] == pytest.approx(0.9)
    assert result["zero_return_baseline_rmse"] == pytest.approx(0.1)
    assert result["mse_skill_vs_zero"] == pytest.approx(-80)
    assert result["is_execution_return"] is False


def test_signed_bias_and_identical_row_baseline():
    result = evaluate_return_errors([0, 0.2], [0.1, 0.3])
    assert result["mae"] == pytest.approx(0.1)
    assert result["mean_error"] == pytest.approx(0.1)
    assert result["mse_skill_vs_zero"] == pytest.approx(0.5)
    assert result["mae_skill_vs_zero"] == pytest.approx(0)


def test_constant_zero_target_has_undefined_skill():
    result = evaluate_return_errors([0, 0], [0, 0])
    assert result["rmse"] == 0
    assert result["mse_skill_vs_zero"] is None
    assert result["mae_skill_vs_zero"] is None


@pytest.mark.parametrize("target,prediction", [([], []), ([0], [1, 2]), ([0], [float("nan")])])
def test_invalid_pairs_are_rejected(target, prediction):
    with pytest.raises(ValueError):
        evaluate_return_errors(target, prediction)

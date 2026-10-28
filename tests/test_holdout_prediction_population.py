"""Future unavailable exits must not remove symbols before inference/ranking."""

import json

import numpy as np
import pandas as pd
import pytest

import stock_ai.ml.holdout as module
from stock_ai.cli import _holdout_component_audit_row
from stock_ai.ml.selection import write_development_selection
from tests.test_locked_holdout import _production_fixture, _selection_fixture


@pytest.mark.parametrize("all_exit_labels", [False, True])
def test_final_predictions_keep_delisted_exits_and_report_unavailable_labels(
    tmp_path, monkeypatch, all_exit_labels
):
    build, dataset_id, build_id = _production_fixture(
        tmp_path, missing_exit_labels=True, all_exit_labels=all_exit_labels
    )
    selection = _selection_fixture(build_id=build_id, dataset_id=dataset_id)
    path = write_development_selection(selection, tmp_path / "selections")

    def predict(training, prediction_frame, **kwargs):
        # Test values depend only on symbol. Unknown targets never enter inference.
        score = prediction_frame.symbol.map({"A": -0.02, "B": 0.01, "C": 0.03}).to_numpy()
        if kwargs["task"] == "large_loss":
            return np.full(len(score), 0.2)
        return score - 0.05 if kwargs["task"] == "quantile" else score

    monkeypatch.setattr(module, "fit_predict_frozen_model", predict)
    result = module.evaluate_locked_holdout(
        selection_path=path, build_manifest_path=build, evaluation_root=tmp_path / "holdout",
        evaluator_code_commit="synthetic-population-v2",
    )
    assert result.report.schema_version == "locked-holdout-report-v2"
    assert result.report.adoption_eligible is False
    assert module.load_locked_holdout_report(result.report_path) == result.report
    assert result.report.label_coverage is not None
    for coverage in result.report.label_coverage:
        assert coverage.prediction_rows == 30
        missing = 0 if coverage.horizon == 1 else 30 if all_exit_labels else 10
        assert coverage.evaluated_rows == 30 - missing
        assert coverage.unavailable_rows == missing
    ledger_path = tmp_path / "holdout" / selection.selection_id / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))["ledger"]
    for state in ledger["components"]:
        frame = pd.read_parquet(state["prediction_path"])
        assert len(frame) == 30
        assert set(frame.symbol) == {"A", "B", "C"}
        assert np.isfinite(frame.prediction).all()
    for component in result.report.component_results:
        if all_exit_labels and component.component.horizon != 1:
            assert component.metrics is None
            assert _holdout_component_audit_row(component)["status"] == "NO_EVALUABLE_LABELS"
        else:
            assert component.metrics is not None
            assert component.metrics.rows == (30 if component.component.horizon == 1 else 20)


def test_coverage_counts_cannot_hide_unavailable_targets():
    with pytest.raises(ValueError, match="coverage counts"):
        module.HoldoutLabelCoverage(
            horizon=5, prediction_rows=3, evaluated_rows=2, unavailable_rows=1,
            unavailable_status_counts=(),
        )


def test_label_mask_does_not_treat_nan_or_unverified_label_as_observed():
    frame = pd.DataFrame({"target_return_5d": [0.1, np.nan, 0.2],
                          "label_status_5d": ["AVAILABLE", "AVAILABLE", "UNKNOWN"]})
    assert module._evaluable_labels(frame, 5).tolist() == [True, False, False]
    coverage = module._label_coverage(frame, 5)
    assert coverage.unavailable_status_counts == (
        ("AVAILABLE_WITHOUT_FINITE_TARGET", 1), ("UNKNOWN", 1),
    )


def test_rank_ensemble_keeps_unlabelled_peer_in_prediction_normalization():
    horizon = _selection_fixture(build_id="a" * 64, dataset_id="b" * 64).horizons[1]
    day = pd.Timestamp("2025-03-03")
    frame = pd.DataFrame({"symbol": ["A", "B", "C"], "trading_date": [day] * 3,
                          "prediction": [1.0, 2.0, 3.0]})
    predictions = {f"h5:{name}": frame for name in horizon.ensemble.component_names}
    labels = frame.assign(target_return_5d=[0.1, 0.2, np.nan],
                          label_status_5d=["AVAILABLE", "AVAILABLE", "DELISTED_NO_EXIT_PRICE"])
    result = module._evaluate_holdout_ensemble(horizon, predictions=predictions, holdout=labels)
    # Full peer ranks (-1/3, 1/3, 1); valid target ranks (0, 1).
    # Dropping C before ranking would incorrectly yield a perfect zero error.
    assert result.rows == 2
    assert result.mean_squared_error_rank_space == pytest.approx(5 / 18)
    empty = labels.assign(target_return_5d=np.nan, label_status_5d="DELISTED_NO_EXIT_PRICE")
    result = module._evaluate_holdout_ensemble(horizon, predictions=predictions, holdout=empty)
    assert result.rows == 0
    assert result.mean_squared_error_rank_space is None
    assert result.empirical_coverage_80 is None

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import stock_ai.ml.advanced as advanced
from stock_ai.ml.checkpoint import ResearchCheckpointStore


def population():
    dates = pd.bdate_range("2020-01-01", periods=40)
    frame = pd.DataFrame([
        {"symbol": symbol, "trading_date": day,
         "as_of": pd.Timestamp(day).tz_localize("UTC") + pd.Timedelta(hours=2),
         "feature": i + j / 3, "target": (i+j)/100,
         "label_end": day + pd.offsets.BDay(5)}
        for i, day in enumerate(dates) for j, symbol in enumerate(("1111", "2222"))
    ])
    config = advanced.AdvancedResearchConfig(
        horizons=(5,), model_families=("lightgbm",), seeds=(17,),
        initial_train_periods=20, validation_periods=5, step_periods=5,
        estimator_count=5, run_ablations=False, run_diagnostics=False,
    )
    return frame, config


def run(frame, config, **kwargs):
    return advanced.generate_oof_predictions(
        frame, feature_names=("feature",), target_column="target",
        label_end_column="label_end", horizon=5, family="lightgbm",
        task="regression", seed=17, parameters={}, config=config, **kwargs,
    )


def test_unknown_exit_label_stays_in_prediction_population(monkeypatch):
    frame, config = population()
    inference = frame.copy()
    # This issuer's future delisting cannot remove it from this day's ranking.
    gap = (inference.symbol == "2222") & (inference.trading_date == frame.trading_date.max())
    inference.loc[gap, ["target", "label_end"]] = [np.nan, pd.NaT]
    trained = []

    def fit(**kwargs):
        trained.append(kwargs["train_target"].to_numpy().copy())
        assert np.isfinite(trained[-1]).all()
        return kwargs["validation_x"].iloc[:, 0].to_numpy(dtype=float)

    monkeypatch.setattr(advanced, "_fit_predict", fit)
    old = run(frame, config)
    old_training = [x.copy() for x in trained]
    trained.clear()
    recovered = run(frame, config, inference_frame=inference)
    assert len(old) == len(recovered)
    assert recovered.target.isna().sum() == 1
    assert recovered.loc[recovered.target.isna(), "symbol"].tolist() == ["2222"]
    assert recovered.prediction.notna().all()
    np.testing.assert_array_equal(old.prediction, recovered.prediction)
    for left, right in zip(old_training, trained, strict=True):
        np.testing.assert_array_equal(left, right)


def test_inference_without_any_outcomes_and_missing_features(monkeypatch):
    frame, config = population()
    inference = frame.drop(columns=["target", "label_end"])
    monkeypatch.setattr(advanced, "_fit_predict", lambda **kw: np.zeros(len(kw["validation_x"])))
    result = run(frame, config, inference_frame=inference, fold_numbers=frozenset({2}))
    assert set(result.fold) == {2}
    assert result.target.isna().all() and result.label_end.isna().all()
    assert len(result) == 10  # No absent issuer or feature row is fabricated.
    with pytest.raises(ValueError, match="missing columns: feature"):
        run(frame, config, inference_frame=inference.drop(columns="feature"))
    with pytest.raises(ValueError, match="duplicate symbol/date"):
        run(frame, config, inference_frame=pd.concat([inference, inference.iloc[:1]]))


def test_expanded_fold_never_reuses_original_checkpoint(monkeypatch, tmp_path: Path):
    frame, config = population()
    calls = []
    def fit(**kwargs):
        calls.append(len(kwargs["validation_x"]))
        return np.zeros(calls[-1])
    monkeypatch.setattr(advanced, "_fit_predict", fit)
    store = ResearchCheckpointStore(tmp_path, provenance={"fixture": "population-recovery"})
    try:
        run(frame, config, checkpoint_store=store, fold_numbers=frozenset({2}))
        inference = frame.copy()
        inference.loc[inference.index[-1], "target"] = np.nan
        run(frame, config, checkpoint_store=store, fold_numbers=frozenset({2}),
            inference_frame=inference)
        run(frame, config, checkpoint_store=store, fold_numbers=frozenset({2}),
            inference_frame=inference)
        assert calls == [10, 10]
    finally:
        store.close()


def test_gap_only_patch_and_nonexistent_fold_are_rejected(monkeypatch):
    frame, config = population()
    monkeypatch.setattr(advanced, "_fit_predict", lambda **kw: np.zeros(len(kw["validation_x"])))
    with pytest.raises(ValueError, match="whole original validation fold"):
        run(frame, config, inference_frame=frame.iloc[-1:], fold_numbers=frozenset({2}))
    with pytest.raises(ValueError, match="requested folds"):
        run(frame, config, inference_frame=frame, fold_numbers=frozenset({2, 999}))


def test_columnwise_projection_preserves_preprocessing_values_and_order():
    frame, _ = population()
    frame['unused_text'] = 'not a numeric feature'
    expected = advanced._finite_numeric(frame.loc[:, ['feature']])
    actual = advanced._finite_numeric(frame, ('feature',))
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)

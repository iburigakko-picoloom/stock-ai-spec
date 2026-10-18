"""Synthetic-only checks of the frozen-fit to private portable-head bridge."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from mobile.pc import export_model as exporter
from mobile.python.portable_model import predict

from stock_ai.ml import advanced
from stock_ai.ml.advanced import AdvancedResearchConfig, fit_predict_frozen_model


@pytest.fixture
def inputs():
    index = np.arange(64, dtype=float)
    # Deliberately unsorted input and correlated/empty features exercise the
    # same train-only sorting, clipping, imputation and pruning as frozen fits.
    frame = pd.DataFrame({
        "symbol": ["TEST_ONLY"] * 64,
        "trading_date": pd.date_range("2020-01-01", periods=64),
        "a": np.sin(index), "b": index / 64,
        "duplicate": np.sin(index), "empty": np.nan,
        "target": .15 * np.sin(index / 5) - .03,
    }).iloc[::-1].copy()
    names = ("a", "b", "duplicate", "empty")
    probes = frame.iloc[:8].loc[:, list(names)].copy()
    probes.iloc[0, 0] = np.nan
    probes.iloc[1, 0] = np.inf
    probes.iloc[2, 1] = -np.inf
    probes.iloc[3, 0] = -100
    probes.iloc[4, 1] = 100
    probes["unused_future_outcome"] = "DO_NOT_READ"
    return frame, probes, names


def options(names, family="lightgbm", task="regression", horizon=5):
    config = AdvancedResearchConfig(
        horizons=(horizon,), model_families=(family,), seeds=(17,),
        estimator_count=5, run_ablations=False, run_diagnostics=False,
    )
    return dict(feature_names=names, target_column="target", horizon=horizon,
                family=family, task=task, seed=17, parameters={}, config=config)


@pytest.mark.parametrize("family", ["lightgbm", "xgboost", "catboost"])
@pytest.mark.parametrize("task", ["regression", "quantile", "large_loss"])
def test_same_frozen_fit_exports_once_without_refitting_or_touching_inputs(
    inputs, family, task, monkeypatch,
):
    training, probes, names = inputs
    original_training, original_probes = training.copy(deep=True), probes.copy(deep=True)
    args = options(names, family, task, 20 if task != "regression" else 5)
    native_fit = advanced._fit_predict
    processor_fit = advanced.FoldPreprocessor.fit
    export = exporter.export_model
    counts = dict(fits=0, processors=0, exports=0)

    def fit(**kwargs):
        counts["fits"] += 1
        assert list(kwargs["validation_x"].columns) == ["a", "b"]
        return native_fit(**kwargs)

    def process(self, frame):
        counts["processors"] += 1
        assert "unused_future_outcome" not in frame
        return processor_fit(self, frame)

    def capture(estimator, processor, family, *, task):
        counts["exports"] += 1
        return export(estimator, processor, family, task=task)

    monkeypatch.setattr(advanced, "_fit_predict", fit)
    monkeypatch.setattr(advanced.FoldPreprocessor, "fit", process)
    monkeypatch.setattr(exporter, "export_model", capture)
    result = exporter.fit_export_frozen_model(training, probes, **args)
    assert counts == dict(fits=1, processors=1, exports=1)
    proof = result["parity"]
    assert proof["status"] == "PASS" and proof["rows"] == 8
    assert proof["config_hash"] == args["config"].config_hash
    for key in ("retrained_for_export", "model_adopted", "policy_modified",
                "persisted", "selection_authenticated"):
        assert proof[key] is False
    np.testing.assert_allclose(predict(result["model"], probes.to_dict(orient="records")),
                               result["native_predictions"], rtol=1e-6, atol=1e-7)
    # Existing no-export path must produce the same predictions with the same
    # frozen settings, rather than a new estimator/configuration for packaging.
    expected = fit_predict_frozen_model(training, probes, **args)
    np.testing.assert_array_equal(result["native_predictions"], expected)
    assert counts == dict(fits=2, processors=2, exports=1)
    pd.testing.assert_frame_equal(training, original_training)
    pd.testing.assert_frame_equal(probes, original_probes)


def test_export_parity_mismatch_is_rejected_without_repair(inputs, monkeypatch):
    training, probes, names = inputs
    original = exporter.export_model

    def broken(*args, **kwargs):
        value = original(*args, **kwargs)
        value["base_score"] += 100
        return value

    monkeypatch.setattr(exporter, "export_model", broken)
    with pytest.raises(ValueError, match="prediction mismatch"):
        exporter.fit_export_frozen_model(training, probes, **options(names))


def test_single_class_probability_does_not_invent_a_fitted_estimator(inputs):
    training, probes, names = inputs
    training["target"] = .01
    args = options(names, task="large_loss", horizon=20)
    # Preserve the existing constant-probability prediction shortcut.
    np.testing.assert_array_equal(fit_predict_frozen_model(training, probes, **args),
                                  np.zeros(len(probes)))
    with pytest.raises(ValueError, match="constant-class export is unsupported"):
        exporter.fit_export_frozen_model(training, probes, **args)


@pytest.mark.parametrize("changed,error", [
    ({"horizon": 1}, "daily 5d/20d"),
    ({"task": "ranking"}, "non-ranking"),
    ({"seed": 29}, "frozen model identity"),
    ({"family": "xgboost"}, "frozen model identity"),
])
def test_incompatible_identity_rejected_before_any_fit(inputs, monkeypatch, changed, error):
    training, probes, names = inputs

    def forbidden(**kwargs):
        pytest.fail("Unexpected model fit")

    monkeypatch.setattr(advanced, "_fit_predict", forbidden)
    with pytest.raises(ValueError, match=error):
        exporter.fit_export_frozen_model(training, probes, **(options(names) | changed))


def test_other_label_family_rejected_before_fit(inputs, monkeypatch):
    training, probes, names = inputs
    args = options(names)
    args["config"] = args["config"].model_copy(update={"target_family": "topix_excess"})
    monkeypatch.setattr(advanced, "_fit_predict", lambda **kwargs: pytest.fail("Unexpected fit"))
    with pytest.raises(ValueError, match="absolute-return"):
        exporter.fit_export_frozen_model(training, probes, **args)


@pytest.mark.parametrize("rows", [0, 1001])
def test_bounded_probe_rows_reject_before_fit(inputs, monkeypatch, rows):
    training, probes, names = inputs
    probes = probes.iloc[np.arange(rows) % len(probes)].copy()
    monkeypatch.setattr(advanced, "_fit_predict", lambda **kwargs: pytest.fail("Unexpected fit"))
    with pytest.raises(ValueError, match=r"1\.\.1000"):
        exporter.fit_export_frozen_model(training, probes, **options(names))


def test_sink_failure_is_propagated_without_retry(inputs):
    training, probes, names = inputs
    calls = []

    def failed(estimator, processor):
        calls.append(estimator)
        raise RuntimeError("TEST_ONLY_EXPORT_WRITE_FAILED")

    with pytest.raises(RuntimeError, match="EXPORT_WRITE_FAILED"):
        fit_predict_frozen_model(training, probes, **options(names), fitted_model_sink=failed)
    assert len(calls) == 1


def test_four_captured_heads_package_and_probe_without_self_approval(inputs):
    import hashlib

    from mobile.pc.package_bundle import package
    from mobile.python.model_bundle import approved, parity

    from stock_ai.operations.daily import canonical_json
    from tests.test_mobile_bundles import SELECTION, fixture_bundle

    training, probes, names = inputs
    selection = {
        **SELECTION,
        "horizons": [{"horizon": h, "feature_names": list(names)} for h in (5, 20)],
    }
    heads, expected = [], []
    for horizon, task in ((5, "regression"), (20, "regression"),
                          (20, "quantile"), (20, "large_loss")):
        result = exporter.fit_export_frozen_model(
            training, probes, **options(names, task=task, horizon=horizon),
        )
        content = canonical_json(result["model"])
        heads.append({"horizon": horizon, "task": task,
                      "model_id": f"TEST_ONLY_{horizon}_{task}", "content": content,
                      "sha256": hashlib.sha256(content.encode()).hexdigest()})
        expected.append(result["native_predictions"])
    metadata = fixture_bundle().model_dump(mode="json", exclude={"bundle_id", "heads"})
    content, proposal = package(metadata, heads, selection)
    values = probes.loc[:, list(names)].to_dict(orient="records")
    result = parity(content, {"5": values, "20": values}, selection)
    for head, native in zip(result["heads"], expected, strict=True):
        np.testing.assert_allclose(head["values"], native, rtol=1e-6, atol=1e-7)
    assert proposal["distribution_review"] == "pending"
    assert proposal["pc_parity_evidence_sha256"] is None
    assert proposal["device_parity_evidence_sha256"] is None
    assert result["model_adopted"] is False and result["persisted"] is False
    with pytest.raises(ValueError, match="MODEL_BUNDLE_NOT_REVIEWED"):
        approved(content, {"approved_bundles": []}, selection)

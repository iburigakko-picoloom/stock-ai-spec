import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest
from stock_ai.features import V2_EXTENDED_MANIFEST
from stock_ai.ml import advanced
from tests.test_advanced_research import (
    _config,
    _production_dataset,
    _research_features,
)

from stock_runtime_memory import AdaptiveMemoryPolicy


def test_resource_wait_resumes_same_inputs(tmp_path):
    values = iter([int(0.8 * 2**30), int(0.8 * 2**30), 4 * 2**30])
    sleeps = []
    policy = AdaptiveMemoryPolicy(
        tmp_path / "audit.jsonl",
        available=lambda: next(values),
        sleep=lambda seconds: sleeps.append(seconds),
        counters=lambda: (0, 0),
    )
    frame = pd.DataFrame(np.zeros((100, 51), dtype="float32"))
    policy.wait(frame, frame, "lightgbm", "regression")
    assert sleeps == [60]
    logs = [json.loads(line) for line in policy.path.read_text().splitlines()]
    assert [record["passed"] for record in logs] == [False, True]
    assert logs[-1]["required_gib"] > 1.5


def test_admission_uses_dimensions_family_and_observed_increment(tmp_path):
    policy = AdaptiveMemoryPolicy(tmp_path / "audit.jsonl")
    frame = pd.DataFrame(np.zeros((10, 51), dtype="float32"))
    size, light = policy.requirement(frame, frame, "lightgbm", "regression")
    _, cat = policy.requirement(frame, frame, "catboost", "regression")
    assert cat > light >= 1.5
    policy.observed["lightgbm", "regression"] = (size, 2 * 2**30)
    assert policy.requirement(frame, frame, "lightgbm", "regression")[1] >= 3.75


@pytest.mark.parametrize("family", ["lightgbm", "xgboost", "catboost"])
def test_inline_policy_preserves_all_native_scientific_outputs(tmp_path, monkeypatch, family):
    import catboost
    import lightgbm
    import xgboost

    config = _config(model_families=(family,))
    args = {
        "data_snapshot_id": "a" * 64,
        "created_at": datetime(2026, 8, 24, 12, tzinfo=UTC),
        "code_commit": "runtime-policy-fixture",
        "config": config,
        "feature_snapshot_id": "b" * 64,
        "feature_manifest_hash": V2_EXTENDED_MANIFEST.manifest_hash,
        "feature_names": _research_features(),
    }
    baseline = advanced.run_advanced_research(_production_dataset(), **args)
    monkeypatch.setattr(advanced, "check_fit_headroom", advanced.check_fit_headroom)
    monkeypatch.setattr(advanced, "_fit_predict", advanced._fit_predict)
    for cls in (
        lightgbm.LGBMModel,
        xgboost.XGBModel,
        xgboost.XGBClassifier,
        xgboost.XGBRanker,
        catboost.CatBoostRegressor,
        catboost.CatBoostClassifier,
        catboost.CatBoostRanker,
    ):
        monkeypatch.setattr(cls, "fit", cls.fit)
    policy = AdaptiveMemoryPolicy(
        tmp_path / "audit.jsonl", available=lambda: 8 * 2**30, counters=lambda: (100, 100)
    )
    policy.install()
    changed = advanced.run_advanced_research(_production_dataset(), **args)
    pdt.assert_frame_equal(baseline.oof_predictions, changed.oof_predictions, check_exact=True)
    reports = [json.loads(run.report.model_dump_json()) for run in (baseline, changed)]
    for report in reports:
        for tuning in report["tuning_results"]:
            for trial in tuning["trials"]:
                trial["duration_seconds"] = None
    assert reports[0] == reports[1]
    assert "model_fit_iteration_memory_audit" in policy.path.read_text()


def test_actual_emergency_aborts_model_without_success(tmp_path, monkeypatch):
    import lightgbm
    from tests.test_advanced_research import _small_model_frame

    from stock_runtime_memory import MemorySafetyStop

    monkeypatch.setattr(advanced, "check_fit_headroom", advanced.check_fit_headroom)
    monkeypatch.setattr(advanced, "_fit_predict", advanced._fit_predict)
    import catboost
    import xgboost

    for cls in (
        lightgbm.LGBMModel,
        xgboost.XGBModel,
        xgboost.XGBClassifier,
        xgboost.XGBRanker,
        catboost.CatBoostRegressor,
        catboost.CatBoostClassifier,
        catboost.CatBoostRanker,
    ):
        monkeypatch.setattr(cls, "fit", cls.fit)
    policy = AdaptiveMemoryPolicy(
        tmp_path / "audit.jsonl", available=lambda: int(0.4 * 2**30), counters=lambda: (100, 100)
    )
    policy.install()
    frame = _small_model_frame()
    with pytest.raises(MemorySafetyStop, match="emergency"):
        advanced._fit_predict(
            family="lightgbm",
            task="regression",
            train_x=frame[["f1", "f2"]],
            validation_x=frame[["f1", "f2"]],
            train_target=frame["target"],
            train_dates=frame["trading_date"],
            seed=17,
            parameters={},
            config=_config(model_families=("lightgbm",)),
        )
    assert policy.emergency

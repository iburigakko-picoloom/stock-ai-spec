from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from catboost import CatBoostClassifier, CatBoostRegressor
from lightgbm import LGBMClassifier, LGBMRegressor
from mobile.pc.export_model import export_model
from mobile.python.portable_model import predict
from xgboost import XGBClassifier, XGBRegressor

from stock_ai.ml.advanced import FoldPreprocessor


@pytest.mark.parametrize("family", ["lightgbm", "xgboost", "catboost"])
@pytest.mark.parametrize("task", ["regression", "large_loss"])
def test_native_pc_prediction_matches_data_only_mobile_trees(family, task):
    index = np.arange(48, dtype=float)
    frame = pd.DataFrame({"a": np.sin(index), "b": index / 48})
    processor = FoldPreprocessor(
        ("a", "b"), lower_quantile=0.01, upper_quantile=0.99, correlation_threshold=0.95
    ).fit(frame)
    transformed = processor.transform(frame)
    regression = np.sin(index / 5) + index / 100
    target = (
        (regression > np.median(regression)).astype(int) if task == "large_loss" else regression
    )
    classification = task == "large_loss"
    factories = {
        "lightgbm": lambda: (LGBMClassifier if classification else LGBMRegressor)(
            n_estimators=5, num_leaves=4, min_child_samples=2, n_jobs=1, verbosity=-1
        ),
        "xgboost": lambda: (XGBClassifier if classification else XGBRegressor)(
            n_estimators=5, max_depth=2, n_jobs=1
        ),
        "catboost": lambda: (CatBoostClassifier if classification else CatBoostRegressor)(
            iterations=5, depth=2, thread_count=1, verbose=False, allow_writing_files=False
        ),
    }
    estimator = factories[family]()
    estimator.fit(transformed, target)
    original = (
        estimator.predict_proba(transformed)[:, 1]
        if classification
        else estimator.predict(transformed)
    )
    model = export_model(estimator, processor, family, task=task)
    calculated = predict(model, frame.to_dict(orient="records"))
    np.testing.assert_allclose(calculated, original, rtol=1e-6, atol=1e-7)
    assert model["research_only"] is True

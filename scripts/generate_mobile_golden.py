"""Synthetic PC-reference vectors only; never package these in the APK."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor
from lightgbm import LGBMClassifier, LGBMRegressor
from mobile.pc.export_model import export_model
from xgboost import XGBClassifier, XGBRegressor

from stock_ai.features import V2_EXTENDED_MANIFEST, FeatureEngine
from stock_ai.fixtures import market_fixture
from stock_ai.ml.advanced import FoldPreprocessor

root = Path(__file__).resolve().parents[1]
daily, market, sector, financials = market_fixture(270)
selection = json.loads(
    next((root / "artifacts/selections/goal3-features").glob("*/*.json")).read_text()
)["feature_selection"]
as_of = daily.available_at.max()
result = FeatureEngine(V2_EXTENDED_MANIFEST).latest_snapshot(
    daily, market, sector, financials=financials, as_of=as_of
)
inputs = {
    name: json.loads(frame.to_json(orient="records", date_format="iso"))
    for name, frame in [
        ("daily", daily),
        ("market", market),
        ("sector", sector),
        ("financials", financials),
    ]
}
inputs["as_of"] = as_of.isoformat()
expected = {
    str(item["horizon"]): json.loads(
        result[["symbol", "available_at", *item["feature_names"]]].to_json(
            orient="records", date_format="iso"
        )
    )
    for item in selection["horizons"]
}
destination = root / ".demo-artifacts/android/mobile-golden.json"
destination.parent.mkdir(parents=True, exist_ok=True)
index = np.arange(48, dtype=float)
model_frame = pd.DataFrame({"a": np.sin(index), "b": index / 48})
processor = FoldPreprocessor(
    ("a", "b"), lower_quantile=0.01, upper_quantile=0.99, correlation_threshold=0.95
).fit(model_frame)
transformed = processor.transform(model_frame)
regression = np.sin(index / 5) + index / 100
vectors = []
for task in ("regression", "large_loss"):
    classification = task == "large_loss"
    target = (regression > np.median(regression)).astype(int) if classification else regression
    estimators = {
        "lightgbm": (LGBMClassifier if classification else LGBMRegressor)(
            n_estimators=5, num_leaves=4, min_child_samples=2, n_jobs=1, verbosity=-1
        ),
        "xgboost": (XGBClassifier if classification else XGBRegressor)(
            n_estimators=5, max_depth=2, n_jobs=1
        ),
        "catboost": (CatBoostClassifier if classification else CatBoostRegressor)(
            iterations=5, depth=2, thread_count=1, verbose=False, allow_writing_files=False
        ),
    }
    for family, estimator in estimators.items():
        estimator.fit(transformed, target)
        reference = (
            estimator.predict_proba(transformed)[:, 1]
            if classification
            else estimator.predict(transformed)
        )
        vectors.append(
            {
                "family": family,
                "task": task,
                "model": export_model(estimator, processor, family, task=task),
                "rows": model_frame.to_dict(orient="records"),
                "expected": reference.tolist(),
            }
        )
destination.write_text(
    json.dumps(
        {"inputs": inputs, "expected": expected, "models": vectors},
        ensure_ascii=False,
        allow_nan=False,
    ),
    encoding="utf-8",
)
print(
    json.dumps(
        {
            "synthetic_only": True,
            "feature_columns": [41, 51],
            "symbols": len(result),
            "output": str(destination),
        }
    )
)

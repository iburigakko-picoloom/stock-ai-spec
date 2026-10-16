"""Synthetic PC-reference vectors only; never package these in the APK."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor
from lightgbm import LGBMClassifier, LGBMRegressor
from mobile.pc.export_model import export_model
from mobile.python.model_bundle import ModelBundle, encoded
from tests.test_bounded_decision import large_scenario, propose
from xgboost import XGBClassifier, XGBRegressor

from stock_ai.features import V2_EXTENDED_MANIFEST, FeatureEngine
from stock_ai.fixtures import market_fixture
from stock_ai.ml.advanced import FoldPreprocessor
from stock_ai.operations.daily import OwnerAdoptionReview, canonical_json

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
for task in ("regression", "large_loss", "quantile"):
    classification = task == "large_loss"
    quantile = task == "quantile"
    target = (regression > np.median(regression)).astype(int) if classification else regression
    estimators = {
        "lightgbm": (LGBMClassifier if classification else LGBMRegressor)(
            n_estimators=5, num_leaves=4, min_child_samples=2, n_jobs=1, verbosity=-1,
            **({"objective": "quantile", "alpha": .1} if quantile else {})
        ),
        "xgboost": (XGBClassifier if classification else XGBRegressor)(
            n_estimators=5, max_depth=2, n_jobs=1,
            **({"objective": "reg:quantileerror", "quantile_alpha": .1} if quantile else {})
        ),
        "catboost": (CatBoostClassifier if classification else CatBoostRegressor)(
            iterations=5, depth=2, thread_count=1, verbose=False, allow_writing_files=False,
            **({"loss_function": "Quantile:alpha=0.1"} if quantile else {})
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
# Rebind only synthetic test features to the actual frozen selection. This
# fixture is never an approval pin or an APK asset.
heads, bundle_rows, bundle_expected = [], {}, []
for horizon, task in ((5, "regression"), (20, "regression"), (20, "quantile"),
                      (20, "large_loss")):
    vector = next(x for x in vectors if x["family"] == "lightgbm" and x["task"] == task)
    names = next(x["feature_names"][:2] for x in selection["horizons"]
                 if x["horizon"] == horizon)
    rename = dict(zip(("a", "b"), names, strict=True))
    model = deepcopy(vector["model"])
    processor_value = model["preprocessor"]
    processor_value["retained"] = [rename[x] for x in processor_value["retained"]]
    for field in ("lower", "upper", "median"):
        processor_value[field] = {rename[k]: v for k, v in processor_value[field].items()}
    content = canonical_json(model)
    heads.append({"horizon": horizon, "task": task, "model_id": f"synthetic-{horizon}-{task}",
                  "sha256": hashlib.sha256(content.encode()).hexdigest(), "content": content})
    bundle_rows[str(horizon)] = [{rename[k]: v for k, v in row.items()}
                                 for row in vector["rows"]]
    bundle_expected.append({"horizon": horizon, "task": task, "values": vector["expected"]})
review = OwnerAdoptionReview.create(
    selection_id="c" * 64, holdout_report_id="d" * 64, evaluator_receipt_id="e" * 64,
    decision_policy_hash="f" * 64, reviewed_at=datetime.fromisoformat("2026-02-02T07:00:00Z"),
    decision="continue_paper", unresolved_gates=("synthetic-test-only",),
    acknowledged_limitations=("Never use fixture values as market data",),
    note="Synthetic offline parity fixture",
)
bundle = ModelBundle.create(
    created_at="2026-02-02T08:00:00Z", trained_at="2026-02-01T00:00:00Z",
    training_data_cutoff="2026-01-30T00:00:00Z",
    feature_selection_id=selection["feature_selection_id"],
    feature_manifest_hash=selection["feature_manifest_hash"], selection_id="c" * 64,
    adoption_review=review, calibration={"method": "received_past_only_20d_residual_rmse",
    "residual_rmse": .02, "rows": 40, "dates": 20,
    "latest_label_available_at": "2026-02-01T00:00:00Z", "fitted_at": "2026-02-01T01:00:00Z",
    "source_evidence_sha256": "1" * 64},
    large_loss_threshold=-.08, downside_quantile_alpha=.1, heads=heads,
)
bundle_content = encoded(bundle)
bounded_state, bounded_candidates, _, bounded_engine = large_scenario(with_costs=True)
bounded_expected = propose(bounded_engine, bounded_state, bounded_candidates)
bounded_fixture = {
    "synthetic_only": True, "portfolio": bounded_state.model_dump(mode="json"),
    "candidates": [x.model_dump(mode="json") for x in bounded_candidates],
    "config": bounded_engine.config.model_dump(mode="json"),
    "cost_policy": bounded_engine.cost_engine.policy.model_dump(mode="json"),
    "tax_policy": bounded_engine.tax_engine.policy.model_dump(mode="json"),
    "generated_at": bounded_expected.generated_at.isoformat(),
    "model_bundle_version": bounded_expected.model_bundle_version,
    "expected": bounded_expected.model_dump(mode="json"),
}
destination.write_text(
    json.dumps(
        {"inputs": inputs, "expected": expected, "models": vectors,
         "bundle": {"content": bundle_content, "rows": bundle_rows,
                    "bundle_id": bundle.bundle_id,
                    "sha256": hashlib.sha256(bundle_content.encode()).hexdigest(),
                    "expected": bundle_expected}, "bounded": bounded_fixture},
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

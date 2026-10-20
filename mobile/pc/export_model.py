"""Export fitted scalar GBDTs; never refit or imply adoption/distribution approval."""

from __future__ import annotations

import json
import math
import struct
import tempfile
from pathlib import Path


def fit_export_frozen_model(
    training, prediction_frame, *, feature_names, target_column, horizon,
    family, task, seed, parameters, config,
) -> dict:
    """Capture an explicitly configured fit and verify its data-only export.

    Callers still own the frozen selection, authorized training-frame boundary,
    resource guard and private output storage. No file, policy or approval is
    created here. Probe rows contain features only, never evaluation outcomes.
    """
    import numpy as np
    from mobile.python.portable_model import predict

    from stock_ai.ml.advanced import fit_predict_frozen_model

    if horizon not in (5, 20) or task not in ("regression", "quantile", "large_loss"):
        raise ValueError("Mobile export requires a daily 5d/20d non-ranking head")
    if config.target_family != "return":
        raise ValueError("Mobile bundle requires the absolute-return label contract")
    if not 1 <= len(prediction_frame) <= 1000:
        raise ValueError("Use 1..1000 feature-only parity probe rows")
    # Project before fitting so held-out target/outcome columns never reach an
    # export consumer. The caller's order, missing values and inputs stay intact.
    probes = prediction_frame.loc[:, list(feature_names)].copy()
    captured = []

    def retain(estimator, processor):
        captured.append(export_model(estimator, processor, family, task=task))

    native = fit_predict_frozen_model(
        training, probes, feature_names=feature_names, target_column=target_column,
        horizon=horizon, family=family, task=task, seed=seed, parameters=parameters,
        config=config, fitted_model_sink=retain,
    )
    if len(captured) != 1:
        raise ValueError("No unique fitted estimator; constant-class export is unsupported")
    portable = captured[0]
    calculated = np.asarray(predict(portable, probes.to_dict(orient="records")), dtype=float)
    # Same fixed tolerance as the existing native/portable regression tests.
    # A mismatch aborts; do not repair weights or change the comparison tolerance.
    if calculated.shape != native.shape or not np.allclose(
        calculated, native, rtol=1e-6, atol=1e-7, equal_nan=False,
    ):
        raise ValueError("Fitted native/portable prediction mismatch")
    return {
        "model": portable,
        "native_predictions": native.tolist(),
        "parity": {
            "status": "PASS", "rows": len(probes), "rtol": 1e-6, "atol": 1e-7,
            "maximum_absolute_error": float(np.max(np.abs(calculated - native))),
            "horizon": horizon, "family": family, "task": task, "seed": seed,
            "config_hash": config.config_hash, "ordered_features": list(feature_names),
            "retained_features": portable["preprocessor"]["retained"],
            "retrained_for_export": False, "research_only": True,
            "selection_authenticated": False, "model_adopted": False,
            "policy_modified": False, "persisted": False,
        },
    }


def export_model(estimator, processor, family: str, *, task: str = "regression") -> dict:
    if task not in ("regression", "ranking", "quantile", "large_loss"):
        raise ValueError("Unsupported task")
    names = list(processor.retained_features)
    result = {
        "schema_version": "stockai-portable-tree-v1",
        "family": family,
        "task": task,
        "preprocessor": {
            "retained": names,
            **{
                key: {
                    name: None
                    if not math.isfinite(float(getattr(processor, "_" + attribute)[name]))
                    else float(getattr(processor, "_" + attribute)[name])
                    for name in names
                }
                for key, attribute in [("lower", "lower"), ("upper", "upper"), ("median", "median")]
            },
        },
        "base_score": 0.0,
        "link": "sigmoid" if task == "large_loss" else "identity",
        "research_only": True,
    }

    def split(
        index, threshold, left, right, *, operator="<=", missing_left=True, missing_zero=False
    ):
        return {
            "feature": index,
            "threshold": float(threshold),
            "operator": operator,
            "missing_left": missing_left,
            "missing_zero": missing_zero,
            "left": left,
            "right": right,
        }

    if family == "lightgbm":
        native = estimator.booster_.dump_model()

        def convert(node):
            if "leaf_value" in node:
                return {"leaf": node["leaf_value"]}
            if node["decision_type"] != "<=":
                raise ValueError("Categorical LightGBM requires a separately validated adapter")
            return split(
                node["split_feature"],
                node["threshold"],
                convert(node["left_child"]),
                convert(node["right_child"]),
                missing_left=node["default_left"],
                missing_zero=node.get("missing_type") == "Zero",
            )

        result["trees"] = [convert(tree["tree_structure"]) for tree in native["tree_info"]]
    elif family == "xgboost":
        booster = estimator.get_booster()
        config = json.loads(booster.save_config())["learner"]["learner_model_param"]
        raw = json.loads(config["base_score"])
        if isinstance(raw, list):
            if len(raw) != 1:
                raise ValueError("Only scalar XGBoost models are supported")
            raw = raw[0]
        result["base_score"] = (
            math.log(float(raw) / (1 - float(raw))) if task == "large_loss" else float(raw)
        )

        def convert(node):
            if "leaf" in node:
                return {"leaf": node["leaf"]}
            feature = node["split"]
            index = names.index(feature) if feature in names else int(feature.removeprefix("f"))
            children = {item["nodeid"]: item for item in node["children"]}
            return split(
                index,
                # XGBoost stores cuts as float32. Its text dump rounds decimal
                # digits; comparing that decimal as float64 misroutes equality.
                struct.unpack("<f", struct.pack("<f", node["split_condition"]))[0],
                convert(children[node["yes"]]),
                convert(children[node["no"]]),
                operator="<",
                missing_left=node["missing"] == node["yes"],
            )

        result["trees"] = [
            convert(json.loads(tree)) for tree in booster.get_dump(dump_format="json")
        ]
    elif family == "catboost":
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            estimator.save_model(str(path), format="json")
            native = json.loads(path.read_text())
        if "oblivious_trees" not in native:
            raise ValueError("Only symmetric CatBoost trees are supported")
        mapping = {
            item["feature_index"]: item["flat_feature_index"]
            for item in native["features_info"]["float_features"]
        }
        result["scale"], bias = native["scale_and_bias"]
        if len(bias) != 1:
            raise ValueError("Only scalar CatBoost models are supported")
        result["bias"] = bias[0]

        def convert(tree, depth=0, mask=0):
            splits = tree.get("splits") or []
            if len(tree["leaf_values"]) != 2 ** len(splits):
                raise ValueError("Unsupported CatBoost output dimensions")
            if depth == len(splits):
                return {"leaf": tree["leaf_values"][mask]}
            node = splits[depth]
            if node["split_type"] != "FloatFeature":
                raise ValueError(
                    "Categorical/text CatBoost requires a separately validated adapter"
                )
            return split(
                mapping[node["float_feature_index"]],
                node["border"],
                convert(tree, depth + 1, mask),
                convert(tree, depth + 1, mask | (1 << depth)),
            )

        result["trees"] = [convert(tree) for tree in native["oblivious_trees"]]
    else:
        raise ValueError("Unsupported model family")
    return result

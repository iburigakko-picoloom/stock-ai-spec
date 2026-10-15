"""Export fitted scalar GBDTs; never refit or imply adoption/distribution approval."""

from __future__ import annotations

import json
import math
import struct
import tempfile
from pathlib import Path


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

"""Data-only scalar tree evaluation. No pickle, executable model code or training."""

from __future__ import annotations

import math
import struct


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def validate(model: dict) -> None:
    """Validate every tree even when an import/parity request has no input rows."""
    if model["schema_version"] != "stockai-portable-tree-v1":
        raise ValueError("Unsupported portable model")
    if model["task"] not in ("regression", "ranking", "quantile", "large_loss"):
        raise ValueError("Unsupported model task")
    if model["family"] not in ("lightgbm", "xgboost", "catboost"):
        raise ValueError("Unsupported model family")
    processor = model["preprocessor"]
    names = processor["retained"]
    if (not isinstance(names, list) or not names or len(names) > 1000
            or any(not isinstance(name, str) or not name for name in names)
            or len(names) != len(set(names)) or not isinstance(model["trees"], list)
            or len(model["trees"]) > 100000):
        raise ValueError("Model exceeds inference limits")
    def finite(value):
        return (not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(value))
    for key in ("lower", "upper", "median"):
        if not isinstance(processor[key], dict) or set(processor[key]) != set(names):
            raise ValueError("Preprocessor feature mismatch")
        if any(not finite(value) and not (key != "median" and value is None)
               for value in processor[key].values()):
            raise ValueError("Invalid preprocessor value")
    for name in names:
        low, high = processor["lower"][name], processor["upper"][name]
        if low is not None and high is not None and low > high:
            raise ValueError("Invalid clipping interval")
    if any(not finite(model.get(key, default))
           for key, default in (("base_score", None), ("scale", 1), ("bias", 0))):
        raise ValueError("Invalid model transform")
    if model["link"] != ("sigmoid" if model["task"] == "large_loss" else "identity"):
        raise ValueError("Model task/output transform mismatch")
    count = 0
    for tree in model["trees"]:
        stack = [(tree, 0)]
        while stack:
            node, depth = stack.pop()
            count += 1
            if depth > 256 or count > 2_000_000 or not isinstance(node, dict):
                raise ValueError("Model tree limit exceeded")
            if "leaf" in node:
                if set(node) != {"leaf"} or not finite(node["leaf"]):
                    raise ValueError("Invalid model leaf")
                continue
            required = {"feature", "threshold", "operator", "missing_left", "left", "right"}
            if not required <= set(node) or set(node) - required - {"missing_zero"}:
                raise ValueError("Invalid split fields")
            if (type(node["feature"]) is not int or not 0 <= node["feature"] < len(names)
                    or not finite(node["threshold"]) or node["operator"] not in ("<=", "<")
                    or type(node["missing_left"]) is not bool
                    or type(node.get("missing_zero", False)) is not bool):
                raise ValueError("Invalid model split")
            stack.extend(((node["left"], depth + 1), (node["right"], depth + 1)))


def predict(model: dict, rows: list[dict]) -> list[float]:
    validate(model)
    processor = model["preprocessor"]
    names = processor["retained"]
    output = []
    for row in rows:
        values = []
        for name in names:
            original = row.get(name)
            value = math.nan if original is None else f32(original)
            if not math.isfinite(value):
                value = processor["median"][name]
            else:
                lower, upper = processor["lower"][name], processor["upper"][name]
                if lower is not None:
                    value = max(value, lower)
                if upper is not None:
                    value = min(value, upper)
            values.append(f32(value))
        score = float(model["base_score"])
        for tree in model["trees"]:
            node = tree
            depth = 0
            while "leaf" not in node:
                depth += 1
                if depth > 256:
                    raise ValueError("Model depth limit exceeded")
                value = values[node["feature"]]
                missing = not math.isfinite(value) or (
                    node.get("missing_zero", False) and value == 0
                )
                if missing:
                    left = node["missing_left"]
                elif node["operator"] == "<=":
                    left = value <= node["threshold"]
                elif node["operator"] == "<":
                    left = value < node["threshold"]
                else:
                    raise ValueError("Unsupported split operator")
                node = node["left"] if left else node["right"]
            score += float(node["leaf"])
        score = score * model.get("scale", 1.0) + model.get("bias", 0.0)
        if model["link"] == "sigmoid":
            score = (
                (1 / (1 + math.exp(-score)))
                if score >= 0
                else (math.exp(score) / (1 + math.exp(score)))
            )
        elif model["link"] != "identity":
            raise ValueError("Unsupported output transform")
        if not math.isfinite(score):
            raise ValueError("Nonfinite model output")
        output.append(score)
    return output

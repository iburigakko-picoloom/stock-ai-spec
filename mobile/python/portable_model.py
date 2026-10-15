"""Data-only scalar tree evaluation. No pickle, executable model code or training."""

from __future__ import annotations

import math
import struct


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def predict(model: dict, rows: list[dict]) -> list[float]:
    if model["schema_version"] != "stockai-portable-tree-v1":
        raise ValueError("Unsupported portable model")
    processor = model["preprocessor"]
    names = processor["retained"]
    if not names or len(names) > 1000 or len(model["trees"]) > 100000:
        raise ValueError("Model exceeds inference limits")
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

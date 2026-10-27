"""Audit saved development risk diagnostics; do not fit or open holdout data."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".demo-artifacts/completion-20261021/p250-task-metrics"
RECEIPT_SHA = "2d8e2c887b6d293a742f7249e18861f4b00ac95788f28030f425af3f4fe47e0f"
CSV_SHA = "04aeff326b9f805961622ab3f287270be8708b4f0eb4b1621df61c1e70bcac95"


def checked(path: Path, expected: str) -> bytes:
    value = path.read_bytes()
    if hashlib.sha256(value).hexdigest() != expected:
        raise ValueError(f"Saved risk source changed: {path.name}")
    return value


def same(csv_row, column, value):
    number = float(csv_row[column])
    if not math.isfinite(number) or not math.isclose(number, value, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(f"Saved risk score mismatch: {column}")


def main() -> None:
    receipt = json.loads(checked(ROOT / "comparison-receipt-v1.json", RECEIPT_SHA))
    csv_text = checked(ROOT / "task-comparison-v2.csv", CSV_SHA).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    if len(rows) != 72 or receipt["strict_pit_authenticated"] or receipt["adoption_eligible"]:
        raise ValueError("Unexpected source coverage or evaluation scope")
    evidence = []
    for family in ("catboost", "lightgbm", "xgboost"):
        for seed in (17, 29, 43):
            component = f"h20-{family}-s{seed}"
            sources = [item for item in receipt["candidate_results"] if component in item["path"]]
            if len(sources) != 1:
                raise ValueError("Risk candidate source is missing or ambiguous")
            result = json.loads(
                checked(ROOT / "attempt-001" / component / "result.json", sources[0]["sha256"])
            )
            if (result["horizon"], result["family"], result["seed"], result["population_id"]) != (
                20, family, seed, receipt["population_id"]
            ):
                raise ValueError("Risk candidate identity differs")
            pair = {}
            for task in ("large_loss", "quantile"):
                task_rows = [item for item in result["tasks"] if item["task"] == task]
                exports = [
                    item for item in rows if item["component"] == component and item["task"] == task
                ]
                if len(task_rows) != 1 or len(exports) != 1:
                    raise ValueError("Risk task coverage differs")
                original, exported = task_rows[0], exports[0]
                if [original["cohort_keys_sha256"], original["cohort_targets_sha256"],
                        original["label_evaluable_rows"]] != receipt["cohorts"]["20"]:
                    raise ValueError("Risk cohort differs")
                if original["calibration"] != "RAW_NO_REFIT":
                    raise ValueError("Unexpected calibration")
                scores = original["scores"]
                folds = original["fold_metrics"]
                if [part["fold"] for part in folds] != [3, 4, 5]:
                    raise ValueError("Risk fold coverage differs")
                if sum(part["metrics"]["scores"]["rows"] for part in folds) != scores["rows"]:
                    raise ValueError("Risk fold row count differs")
                if task == "large_loss":
                    if original["event_definition"] != {"operator": "<=", "threshold": -0.08}:
                        raise ValueError("Risk event differs")
                    for name in ("base_rate", "mean_probability", "brier_score", "log_loss"):
                        same(exported, name, scores[name])
                    rate = scores["base_rate"]
                    pair[task] = {name: scores[name] for name in (
                        "base_rate", "mean_probability", "brier_score", "log_loss"
                    )}
                    pair[task]["hindsight_constant_brier"] = rate * (1 - rate)
                    pair[task]["folds"] = [
                        {"fold": part["fold"], **{name: part["metrics"]["scores"][name]
                         for name in ("rows", "base_rate", "mean_probability", "brier_score")}}
                        for part in folds
                    ]
                    for name in ("base_rate", "mean_probability", "brier_score"):
                        weighted = sum(part[name] * part["rows"] for part in pair[task]["folds"])
                        if not math.isclose(weighted / scores["rows"], scores[name], abs_tol=1e-12):
                            raise ValueError("Risk fold weighted score differs")
                else:
                    if original["quantile_alpha"] != 0.1 or len(scores["scores"]) != 1:
                        raise ValueError("Risk quantile differs")
                    quantile = scores["scores"][0]
                    for name in ("alpha", "pinball_loss", "strictly_below_rate"):
                        same(exported, name, quantile[name])
                    pair[task] = {**quantile, "folds": [
                        {"fold": part["fold"], "rows": part["metrics"]["scores"]["rows"],
                         **part["metrics"]["scores"]["scores"][0]} for part in folds
                    ]}
                    if any(part["alpha"] != quantile["alpha"] for part in pair[task]["folds"]):
                        raise ValueError("Risk fold quantile definition differs")
                    for name in ("pinball_loss", "strictly_below_rate"):
                        weighted = sum(part[name] * part["rows"] for part in pair[task]["folds"])
                        if not math.isclose(
                            weighted / scores["rows"], quantile[name], abs_tol=1e-12
                        ):
                            raise ValueError("Risk fold weighted quantile differs")
                pair[task]["missing_predictions_on_P"] = original["missing_predictions_on_P"]
            evidence.append({"family": family, "seed": seed, **pair})
    print(json.dumps({
        "scope": "conditional development diagnostics; not final holdout or adoption",
        "event": "20-session return <= -8%", "rows": receipt["cohorts"]["20"][2],
        "constant_baseline": "same evaluation cohort base rate; hindsight diagnostic only",
        "candidates": evidence,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Summarize saved development diagnostics; never open or evaluate holdout data.

The private inputs must already exist under .demo-artifacts/completion-20261021.
This script verifies their recorded hashes and checks the selected rows against
the underlying per-model diagnostics. It does not re-run predictions or claim
point-in-time validity for the historical sources.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".demo-artifacts/completion-20261021"
HASHES = {
    "p250-task-metrics/comparison-receipt-v1.json": (
        "2d8e2c887b6d293a742f7249e18861f4b00ac95788f28030f425af3f4fe47e0f"
    ),
    "p250-task-metrics/task-comparison-v2.csv": (
        "04aeff326b9f805961622ab3f287270be8708b4f0eb4b1621df61c1e70bcac95"
    ),
    "conditional-nav-v1/comparison-receipt-v1.json": (
        "c1ccc75607a6950d6416c2a3709dd27953a5ba3e486b8d3e0e0147609abc9b52"
    ),
    "conditional-nav-v1/comparison-v1.csv": (
        "bb68cd8659765424a410d7799a3169d5c456f4ca3d892dccc67cd9702fdd7b04"
    ),
}
MODELS = (
    (5, "catboost", "regression"),
    (20, "catboost", "regression"),
    (20, "lightgbm", "ranking"),
)
SEEDS = (17, 29, 43)


def verified(path: Path, digest: str) -> bytes:
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(f"Source hash mismatch: {path.name}")
    return content


def same(left: float, right: float) -> None:
    if not (
        math.isfinite(left)
        and math.isfinite(right)
        and math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
    ):
        raise ValueError("Saved metric and independently recomputed metric differ")


def main() -> None:
    files = {name: verified(ROOT / name, digest) for name, digest in HASHES.items()}
    metrics_receipt = json.loads(files["p250-task-metrics/comparison-receipt-v1.json"])
    nav_receipt = json.loads(files["conditional-nav-v1/comparison-receipt-v1.json"])
    csv_rows = list(
        csv.DictReader(
            files["p250-task-metrics/task-comparison-v2.csv"].decode("utf-8-sig").splitlines()
        )
    )
    nav_rows = list(
        csv.DictReader(
            files["conditional-nav-v1/comparison-v1.csv"].decode("utf-8-sig").splitlines()
        )
    )
    if len(csv_rows) != 72 or len(nav_rows) != 96 or nav_receipt["complete_cases"] != 96:
        raise ValueError("Unexpected source coverage")
    if (
        metrics_receipt["strict_pit_authenticated"]
        or nav_receipt["adoption_eligible"]
        or nav_receipt["real_holdout_opened"]
    ):
        raise ValueError("Unexpected evaluation scope")
    output = []
    for horizon, family, task in MODELS:
        seeds = []
        for seed in SEEDS:
            component = f"h{horizon}-{family}-s{seed}"
            evidence = [x for x in metrics_receipt["candidate_results"] if component in x["path"]]
            if len(evidence) != 1:
                raise ValueError(f"Ambiguous evidence: {component}")
            path = ROOT / "p250-task-metrics/attempt-001" / component / "result.json"
            result = json.loads(verified(path, evidence[0]["sha256"]))
            if (result["horizon"], result["family"], result["seed"], result["population_id"]) != (
                horizon,
                family,
                seed,
                metrics_receipt["population_id"],
            ):
                raise ValueError(f"Wrong model or population: {component}")
            task_rows = [x for x in result["tasks"] if x["task"] == task]
            exported = [x for x in csv_rows if x["component"] == component and x["task"] == task]
            if len(task_rows) != 1 or len(exported) != 1:
                raise ValueError(f"Wrong task coverage: {component}")
            model = task_rows[0]
            cohort = metrics_receipt["cohorts"][str(horizon)]
            if [
                model["cohort_keys_sha256"],
                model["cohort_targets_sha256"],
                model["label_evaluable_rows"],
            ] != cohort:
                raise ValueError(f"Cohort differs: {component}")
            score = model["scores"]["rank_ic_on_label_evaluable_subset"]
            days = score["daily_ic"]
            values = [row["rank_ic"] for row in days if row["rank_ic"] is not None]
            if (
                len(values) != score["valid_IC_dates"]
                or len(days) != score["eligible_evaluation_dates"]
            ):
                raise ValueError(f"Invalid date counts: {component}")
            same(statistics.mean(values), score["metrics"]["mean_daily_rank_ic"])
            same(float(exported[0]["mean_daily_rank_ic"]), score["metrics"]["mean_daily_rank_ic"])
            folds = []
            for fold in model["fold_metrics"]:
                ic = fold["metrics"]["scores"]["rank_ic_on_label_evaluable_subset"]
                fold_values = [
                    row["rank_ic"] for row in ic["daily_ic"] if row["rank_ic"] is not None
                ]
                same(statistics.mean(fold_values), ic["metrics"]["mean_daily_rank_ic"])
                folds.append(
                    {
                        "fold": fold["fold"],
                        "days": len(fold_values),
                        "mean_ic": statistics.mean(fold_values),
                    }
                )
            errors = model["scores"].get("return_errors")
            if errors:
                for key in ("mae", "rmse", "mean_error", "mse_skill_vs_zero"):
                    same(float(exported[0][key]), errors[key])
                same(errors["mean_prediction"] - errors["mean_realized"], errors["mean_error"])
                same(errors["rmse"] ** 2, errors["mean_squared_error"])
                same(
                    1 - errors["mean_squared_error"] / errors["zero_return_baseline_rmse"] ** 2,
                    errors["mse_skill_vs_zero"],
                )
            seeds.append(
                {
                    "seed": seed,
                    "rows": model["label_evaluable_rows"],
                    "predictable_rows": model["predictable_rows"],
                    "unknown_labels": model["unknown_label_rows"],
                    "missing_predictions_on_P": model["missing_predictions_on_P"],
                    "dates": len(days),
                    "first_date": days[0]["trading_date"],
                    "last_date": days[-1]["trading_date"],
                    "mean_ic": statistics.mean(values),
                    "negative_days": sum(value < 0 for value in values),
                    "folds": folds,
                    "return_errors": errors,
                }
            )
        comparisons = []
        strategy = f"{task}__{family}_s17"
        for bps in (20, 40):
            rows = [
                x
                for x in nav_rows
                if (x["horizon"], x["bps"], x["strategy"]) == (str(horizon), str(bps), strategy)
            ]
            originals = [
                x
                for x in nav_receipt["selected_diagnostics"]
                if (x["horizon"], x["bps"], x["strategy"]) == (horizon, bps, strategy)
            ]
            if len(rows) != 1 or len(originals) != 1:
                raise ValueError(f"Wrong NAV coverage: {strategy}, {bps}")
            baselines = [
                x
                for x in nav_rows
                if (x["horizon"], x["bps"], x["strategy"])
                == (str(horizon), str(bps), "momentum_20d")
            ]
            if len(baselines) != 1:
                raise ValueError(f"Wrong momentum coverage: {horizon}, {bps}")
            same(
                float(rows[0]["ending_nav_yen"]) / float(rows[0]["initial_nav_yen"]) - 1,
                float(rows[0]["net_return"]),
            )
            same(
                float(rows[0]["net_return"]) - float(baselines[0]["net_return"]),
                float(rows[0]["return_minus_momentum"]),
            )
            same(
                float(rows[0]["maximum_drawdown"]) - float(baselines[0]["maximum_drawdown"]),
                float(rows[0]["MDD_minus_momentum"]),
            )
            for key in (
                "net_return",
                "maximum_drawdown",
                "return_minus_momentum",
                "MDD_minus_momentum",
            ):
                same(float(rows[0][key]), float(originals[0][key]))
            comparisons.append(
                {
                    key: rows[0][key]
                    for key in (
                        "bps",
                        "net_return",
                        "maximum_drawdown",
                        "return_minus_momentum",
                        "MDD_minus_momentum",
                    )
                }
            )
        output.append(
            {
                "horizon": horizon,
                "family": family,
                "task": task,
                "seeds": seeds,
                "conditional_nav_seed17": comparisons,
            }
        )
    print(
        json.dumps(
            {
                "scope": "development label-evaluable and conditional NAV; "
                "not strict PIT or holdout",
                "sources_sha256": HASHES,
                "models": output,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

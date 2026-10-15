"""Development artifact audit and independent evaluator checks; never opens holdout data."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from stock_ai.ml.advanced import AdvancedResearchReport, load_advanced_research_run
from stock_ai.ml.campaign import CampaignBatchStatus, load_campaign_manifest
from stock_ai.ml.selection import (
    _authenticate_batch_report,
    load_development_feature_selection,
)

EVALUATOR_VERSION = "daily-evaluation-audit-v1"
COST_SCENARIOS_BPS = (10, 20, 30, 50)


def rank_ic(prediction: Sequence[float], target: Sequence[float]) -> float | None:
    """Average-tie Spearman IC; missing/constant/small sections have no IC."""
    if len(prediction) != len(target):
        raise ValueError("prediction and target lengths differ")
    frame = pd.DataFrame({"p": prediction, "y": target}).replace([np.inf, -np.inf], np.nan)
    frame = frame.dropna()
    if len(frame) < 3 or frame.p.nunique() < 2 or frame.y.nunique() < 2:
        return None
    return float(frame.p.rank(method="average").corr(frame.y.rank(method="average")))


def audit_training_labels(
    train: pd.DataFrame, validation: pd.DataFrame, *, cutoff: datetime
) -> tuple[str, ...]:
    """Audit actual label intervals and receipt time, not an assumed horizon gap.

    Both frames require prediction_date, label_start and label_end. Training also
    requires label_available_at. Intervals are closed; labels received at cutoff
    are not available for fitting immediately before that prediction.
    """
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("cutoff must be timezone-aware")
    parsed: list[tuple[pd.Series, pd.Series]] = []
    for frame in (train, validation):
        for column in ("label_start", "label_end"):
            if frame[column].isna().any() or any(
                pd.Timestamp(value).tzinfo is None for value in frame[column]
            ):
                raise ValueError("label intervals require aware, nonmissing timestamps")
        starts = pd.to_datetime(frame.label_start, utc=True)
        ends = pd.to_datetime(frame.label_end, utc=True)
        if (starts > ends).any():
            raise ValueError("reversed label interval")
        parsed.append((starts, ends))
    if train.label_available_at.isna().any() or any(
        pd.Timestamp(value).tzinfo is None for value in train.label_available_at
    ):
        raise ValueError("label availability requires aware, nonmissing timestamps")
    issues: list[str] = []
    if (pd.to_datetime(train.label_available_at, utc=True) >= cutoff).any():
        issues.append("IMMATURE_TRAINING_LABEL")
    if set(train.prediction_date) & set(validation.prediction_date):
        issues.append("SPLIT_DATE_GROUP")
    starts, ends = parsed[0]
    validation_starts, validation_ends = parsed[1]
    # Merge validation intervals first: inexpensive even for a full stock universe.
    merged: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for start, end in sorted(set(zip(validation_starts, validation_ends, strict=True))):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    if any(((starts <= end) & (ends >= start)).any() for start, end in merged):
        issues.append("OVERLAPPING_LABEL_INTERVAL")
    return tuple(issues)


def validate_development_oof(frame: pd.DataFrame, report: AdvancedResearchReport) -> None:
    """Refuse duplicate keys, altered identities, incomplete tasks or holdout rows."""
    key = ["symbol", "trading_date", "horizon", "model_family", "task", "seed"]
    required = {*key, "label_end", "target", "prediction", "fold"}
    if missing := required - set(frame):
        raise ValueError(f"missing OOF columns: {sorted(missing)}")
    if frame.empty or frame[list(required)].isna().any().any():
        raise ValueError("OOF is empty or contains missing required values")
    if frame.duplicated(key).any():
        raise ValueError("duplicate OOF model-row identity")
    if not np.isfinite(frame[["target", "prediction"]].to_numpy(dtype=float)).all():
        raise ValueError("nonfinite OOF target or prediction")
    expected = {
        "horizon": set(report.config.horizons),
        "model_family": set(report.config.model_families),
        "seed": set(report.config.seeds),
        "task": {"regression", "ranking", "quantile", "large_loss"},
    }
    for column, values in expected.items():
        if set(frame[column]) != values:
            raise ValueError(f"OOF {column} differs from declared matrix")
    boundary = pd.Timestamp(report.locked_holdout_start)
    dates, ends = pd.to_datetime(frame.trading_date), pd.to_datetime(frame.label_end)
    if (dates >= boundary).any() or (ends >= boundary).any() or (ends < dates).any():
        raise ValueError("OOF crosses locked holdout or has reversed labels")
    loss = frame.loc[frame.task == "large_loss", "prediction"]
    if ((loss < 0) | (loss > 1)).any():
        raise ValueError("large-loss probabilities outside [0,1]")
    reference: pd.DataFrame | None = None
    for _, part in frame.groupby("task", sort=True):
        aligned = part.sort_values(["trading_date", "symbol"])[
            ["symbol", "trading_date", "target", "label_end", "fold"]
        ].reset_index(drop=True)
        if reference is not None and not aligned.equals(reference):
            raise ValueError("task OOF keys/targets/folds do not align")
        reference = aligned
    for stage in report.stage_boundaries:
        if dates.min() < pd.Timestamp(stage.model_evaluation_start):
            raise ValueError("tuning observations entered model evaluation")


def audit_candidate_campaigns(
    *,
    feature_selection_path: Path,
    candidate_campaign_paths: Sequence[Path],
    score_development: bool = False,
) -> dict[str, Any]:
    """Authenticate one report at a time, retaining every failure in an audit receipt.

    This does not select a model, infer significance, read labels outside the OOF,
    or claim that report declarations constitute a complete holdout-access audit.
    """
    features = load_development_feature_selection(feature_selection_path)
    expected = {
        (item.horizon, family, seed)
        for item in features.horizons
        for family in ("lightgbm", "xgboost", "catboost")
        for seed in features.seeds
    }
    seen: set[tuple[int, str, int | None]] = set()
    runs: list[dict[str, Any]] = []
    problems: list[str] = []
    reference_keys: dict[int, str] = {}
    features_by_horizon = {item.horizon: item.feature_names for item in features.horizons}
    for path in candidate_campaign_paths:
        manifest = load_campaign_manifest(path)
        if manifest.schema_version != "research-campaign-manifest-v2":
            raise ValueError("audit requires strict v2 manifests")
        for batch in manifest.batches:
            identity = (batch.horizon, batch.model_family, batch.seed)
            receipt: dict[str, Any] = {
                "campaign_id": manifest.campaign_id,
                "batch_id": batch.batch_id,
                "code_commit": manifest.code_commit,
                "horizon": batch.horizon,
                "family": batch.model_family,
                "seed": batch.seed,
                "report_id": batch.report_id,
                "status": "FAIL",
            }
            runs.append(receipt)
            try:
                if identity in seen:
                    raise ValueError("duplicate horizon/family/seed in campaign set")
                seen.add(identity)
                if batch.status is not CampaignBatchStatus.SUCCEEDED or batch.oof_path is None:
                    raise ValueError("candidate did not succeed")
                report, oof = load_advanced_research_run(Path(batch.oof_path))
                try:
                    _authenticate_batch_report(manifest, batch, report)
                    if manifest.build_id != features.build_id or report.config.run_ablations:
                        raise ValueError("candidate build or ablation role mismatch")
                    if (
                        report.feature_names != features_by_horizon[batch.horizon]
                        or report.data_snapshot_id != features.data_snapshot_id
                        or report.feature_snapshot_id != features.feature_snapshot_id
                        or report.feature_manifest_hash != features.feature_manifest_hash
                        or report.locked_holdout_start != features.locked_holdout_start
                        or report.config.holdout_periods != features.holdout_periods
                    ):
                        raise ValueError("candidate differs from frozen feature/data contract")
                    if score_development:
                        from stock_ai.ml.evaluation_metrics import evaluate_development_tasks

                        receipt["development_metrics"] = evaluate_development_tasks(oof, report)
                    else:
                        validate_development_oof(oof, report)
                    aligned = (
                        oof.loc[oof.task == "regression"]
                        .sort_values(["trading_date", "symbol"])[
                            ["symbol", "trading_date", "target", "label_end"]
                        ]
                        .reset_index(drop=True)
                    )
                    digest = hashlib.sha256(
                        pd.util.hash_pandas_object(aligned, index=False).to_numpy().tobytes()
                    ).hexdigest()
                    if reference_keys.setdefault(batch.horizon, digest) != digest:
                        raise ValueError("candidate cross-model OOF keys/targets differ")
                    receipt.update(
                        status="PASS",
                        rows=len(oof),
                        aligned_keys_hash=digest,
                        logical_oof_hash=report.oof_sha256,
                        holdout_access_declared=report.locked_holdout_accessed,
                        cost_evaluation_status=report.cost_evaluation_status.value,
                        original_cost_scenarios_bps=report.cost_scenarios_bps,
                        adoption_blocking_reasons=report.adoption_blocking_reasons,
                        metrics=[item.model_dump(mode="json") for item in report.model_metrics],
                    )
                finally:
                    del oof
            except (ValueError, RuntimeError, OSError, KeyError) as exc:
                receipt["error"] = str(exc)
                problems.append(f"{batch.batch_id}: {exc}")
    if seen != expected:
        problems.append("candidate matrix differs from frozen horizons/families/seeds")
    return {
        "schema_version": "daily-evaluation-audit-v2" if score_development else EVALUATOR_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "feature_selection_id": features.feature_selection_id,
        "status": "FAIL" if problems else "PASS",
        "runs": runs,
        "problems": problems,
        "locked_holdout_opened_by_audit": False,
        "holdout_access_history_status": "DECLARATIONS_ONLY_NOT_FULL_ACCESS_AUDIT",
        "training_label_availability_status": "REQUIRES_SOURCE_INTERVAL_AUDIT",
        "cost_scenarios_bps": COST_SCENARIOS_BPS,
        "confidence_intervals": "DIAGNOSTIC_ONLY_NOT_CALIBRATED",
        "adoption_eligible": False,
    }


def write_audit_receipt(receipt: dict[str, Any], root: Path) -> Path:
    encoded = json.dumps(receipt, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
    identity = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{identity}.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded + "\n")
    return path

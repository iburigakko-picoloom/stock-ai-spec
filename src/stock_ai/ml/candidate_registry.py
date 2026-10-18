"""Read-only registry of the existing daily candidates; never fits a model."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

from stock_ai.ml.advanced import AdvancedResearchReport, _authenticate_advanced_research_bundle
from stock_ai.ml.campaign import (
    CampaignBatchStatus,
    ResearchCampaignManifest,
    load_campaign_manifest,
)
from stock_ai.ml.checkpoint import (
    _authenticate_metadata,
    checkpoint_id_for_provenance,
    stable_hash,
)
from stock_ai.ml.selection import _authenticate_batch_report, load_development_feature_selection


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _training_intervals(
    manifest: ResearchCampaignManifest,
    report: AdvancedResearchReport,
    pinned: dict[str, str],
) -> dict[str, Any]:
    if manifest.checkpoint_root is None:
        return {"status": "MISSING_LINKED_CHECKPOINT", "folds": []}
    provenance = {
        "data_snapshot_id": report.data_snapshot_id,
        "feature_snapshot_id": report.feature_snapshot_id,
        "feature_manifest_hash": report.feature_manifest_hash,
        "feature_names": list(report.feature_names),
        "code_commit": report.code_commit,
        "config": report.config.model_dump(mode="json"),
        "config_hash": report.config_hash,
        "locked_holdout_accessed": False,
    }
    identity = checkpoint_id_for_provenance(provenance)
    root = Path(manifest.checkpoint_root) / identity
    namespace = root / "manifest.json"
    if not namespace.is_file():
        return {"status": "MISSING_LINKED_CHECKPOINT", "folds": []}
    payload = json.loads(namespace.read_text(encoding="utf-8"))
    _authenticate_metadata(payload, description="registry checkpoint namespace")
    if payload["checkpoint_id"] != identity or payload["provenance"] != provenance:
        raise ValueError("registry checkpoint provenance differs from report")
    pinned[str(namespace)] = file_sha256(namespace)
    folds = []
    expected = {(x.task, x.fold, x.validation_start, x.validation_end) for x in report.fold_results}
    observed = set()
    for path in sorted((root / "folds").glob("*/manifest.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        _authenticate_metadata(payload, description="registry fold")
        evidence = payload["evidence"]
        unit = stable_hash(
            {
                "schema_version": "advanced-research-fold-v1",
                "checkpoint_id": identity,
                "evidence": evidence,
            }
        )
        if (
            payload["checkpoint_id"] != identity
            or payload["unit_id"] != unit
            or path.parent.name != unit
        ):
            raise ValueError("registry fold identity mismatch")
        if evidence["checkpoint_scope"] != "outer-model-evaluation":
            continue
        if (
            evidence["config_hash"] != report.config_hash
            or tuple(evidence["feature_names"]) != report.feature_names
        ):
            raise ValueError("registry fold config/features mismatch")
        start, end = evidence["validation_start"][:10], evidence["validation_end"][:10]
        key = evidence["task"], evidence["fold"], start, end
        if key not in expected or evidence["train_end"] >= evidence["validation_start"]:
            raise ValueError("registry fold training/validation interval mismatch")
        pinned[str(path)] = file_sha256(path)
        parquet = path.parent / "oof.parquet"
        digest = file_sha256(parquet)
        if digest != payload["parquet_sha256"]:
            raise ValueError("registry fold Parquet hash mismatch")
        pinned[str(parquet)] = digest
        observed.add(key)
        folds.append(
            {
                k: evidence[k]
                for k in (
                    "task",
                    "fold",
                    "train_start",
                    "train_end",
                    "train_rows",
                    "validation_start",
                    "validation_end",
                    "validation_rows",
                    "train_indices_sha256",
                    "validation_indices_sha256",
                )
            }
        )
    return {
        "status": "PINNED_INTERVALS" if observed == expected else "PARTIAL_PINNED_INTERVALS",
        "folds": folds,
        "source_training_rows_reaudited": False,
        "fitted_preprocessor_or_model_serialized_by_checkpoint": False,
    }


def build_candidate_registry(
    feature_selection_path: Path,
    campaign_paths: Sequence[Path],
) -> dict[str, Any]:
    """Keep failed/pending history and one authenticated success per identity.

    Authentication pins report/Parquet bytes and existing campaign/build/feature
    contracts. It does not re-score OOF, open a dataset, or certify access history.
    """
    started = perf_counter()
    paths = [feature_selection_path, *campaign_paths]
    pinned = {str(p): file_sha256(p) for p in paths}
    features = load_development_feature_selection(feature_selection_path)
    feature_names = {h.horizon: h.feature_names for h in features.horizons}
    if set(feature_names) != {5, 20} or set(features.seeds) != {17, 29, 43}:
        raise ValueError("daily registry requires the frozen 5d/20d three-seed contract")
    expected = [
        (h, f, s)
        for h in (5, 20)
        for f in ("lightgbm", "xgboost", "catboost")
        for s in features.seeds
    ]
    rows: dict[tuple[int, str, int | None], dict[str, Any]] = {
        key: {
            "horizon": key[0],
            "family": key[1],
            "seed": key[2],
            "attempts": [],
            "authenticated_reports": {},
            "status": "MISSING",
            "problems": [],
        }
        for key in expected
    }
    for path in campaign_paths:
        manifest = load_campaign_manifest(path)
        for batch in manifest.batches:
            key = batch.horizon, batch.model_family, batch.seed
            if key not in rows:
                raise ValueError("campaign contains a candidate outside the frozen matrix")
            row = rows[key]
            row["attempts"].append(
                {
                    "campaign_path": str(path),
                    "campaign_id": manifest.campaign_id,
                    "batch_id": batch.batch_id,
                    "status": batch.status.value,
                    "attempts": batch.attempts,
                    "last_error": batch.last_error,
                    "code_commit": manifest.code_commit,
                    "report_id": batch.report_id,
                }
            )
            if batch.status is not CampaignBatchStatus.SUCCEEDED:
                continue
            try:
                if batch.oof_path is None:
                    raise ValueError("successful candidate has no saved OOF")
                parquet, report, parquet_sha = _authenticate_advanced_research_bundle(
                    Path(batch.oof_path),
                )
                _authenticate_batch_report(manifest, batch, report)
                if (
                    manifest.build_id != features.build_id
                    or report.data_snapshot_id != features.data_snapshot_id
                    or report.feature_snapshot_id != features.feature_snapshot_id
                    or report.feature_manifest_hash != features.feature_manifest_hash
                    or report.feature_names != feature_names[batch.horizon]
                    or report.locked_holdout_start != features.locked_holdout_start
                    or report.config.run_ablations
                ):
                    raise ValueError("candidate differs from the frozen feature/data contract")
                metadata = parquet.parent / f"{report.report_id}.json"
                pinned[str(metadata)] = file_sha256(metadata)
                # Bundle authentication already streamed the large Parquet hash.
                pinned[str(parquet)] = parquet_sha
                row["authenticated_reports"][report.report_id] = {
                    "report_id": report.report_id,
                    "report_path": str(metadata),
                    "report_file_sha256": pinned[str(metadata)],
                    "oof_path": str(parquet),
                    "oof_file_sha256": parquet_sha,
                    "oof_logical_sha256": report.oof_sha256,
                    "oof_rows": report.oof_rows,
                    "data_snapshot_id": report.data_snapshot_id,
                    "feature_snapshot_id": report.feature_snapshot_id,
                    "ordered_features": report.feature_names,
                    "preprocessing_version": report.preprocessing_version,
                    "preprocessing_config": {
                        name: getattr(report.config, name)
                        for name in (
                            "clip_lower_quantile",
                            "clip_upper_quantile",
                            "correlation_threshold",
                        )
                    },
                    "code_commit": report.code_commit,
                    "library_versions": dict(report.library_versions),
                    "tuning": [x.model_dump(mode="json") for x in report.tuning_results],
                    "stage_boundaries": [
                        x.model_dump(mode="json") for x in report.stage_boundaries
                    ],
                    "validation_folds": [x.model_dump(mode="json") for x in report.fold_results],
                    "training_intervals": _training_intervals(manifest, report, pinned),
                    "saved_inference_model_status": "NOT_LINKED_BY_REPORT_OR_OOF_CONTRACT",
                    "required_training": "ONLY_MISSING_FINAL_INFERENCE_REFIT_AFTER_SELECTION",
                    "holdout_access_declared": report.locked_holdout_accessed,
                    "holdout_access_history_status": "DECLARATIONS_ONLY_NOT_FULL_ACCESS_AUDIT",
                    "historical_revision_policy": report.historical_revision_policy,
                    "cost_evaluation_status": report.cost_evaluation_status.value,
                    "adoption_blocking_reasons": report.adoption_blocking_reasons,
                    "original_metrics": [x.model_dump(mode="json") for x in report.model_metrics],
                }
            except (ValueError, RuntimeError, OSError) as exc:
                row["problems"].append(str(exc))
    for row in rows.values():
        reports = row["authenticated_reports"]
        row["status"] = (
            "AUTHENTICATED_OOF"
            if len(reports) == 1 and not row["problems"]
            else "HOLD_AMBIGUOUS_OR_INVALID"
            if reports or row["problems"]
            else "MISSING_AUTHENTICATED_SUCCESS"
        )
    # Recheck everything: a running data job must not change inputs mid-audit.
    if any(file_sha256(Path(p)) != digest for p, digest in pinned.items()):
        raise RuntimeError("registry inputs changed during audit")
    return {
        "schema_version": "daily-candidate-registry-v1",
        "research_only": True,
        "adoption_eligible": False,
        "feature_selection_id": features.feature_selection_id,
        "locked_holdout_start": features.locked_holdout_start,
        "holdout_opened": False,
        "training_performed": False,
        "status": "AUTHENTICATED_OOF"
        if all(r["status"] == "AUTHENTICATED_OOF" for r in rows.values())
        else "HOLD",
        "candidates": list(rows.values()),
        "pinned_files": pinned,
        "performance_recomputed": False,
        "training_models_certified": False,
        "implementation_sha256": {
            name: file_sha256(Path(__file__).with_name(name))
            for name in (
                "candidate_registry.py",
                "advanced.py",
                "campaign.py",
                "selection.py",
                "checkpoint.py",
            )
        },
        "elapsed_seconds": perf_counter() - started,
    }

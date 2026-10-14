"""Read-only audit of the frozen 18-candidate daily campaign and source label times.

Run from the repository root with PYTHONPATH=src. Does not compute performance on
holdout observations, select parameters, create checkpoint stores, or mutate runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd

from stock_ai.ml.advanced import AdvancedResearchReport, _frame_hash
from stock_ai.ml.campaign import load_campaign_manifest
from stock_ai.ml.checkpoint import (
    _authenticate_metadata,
    checkpoint_id_for_provenance,
    read_checkpoint_status,
)
from stock_ai.ml.selection import load_development_feature_selection
from stock_ai.ml.validation import PurgedExpandingWindowSplitter


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit_checkpoints(campaign_paths: list[Path], native_sources: Path) -> list[dict[str, object]]:
    results = []
    for campaign_path in campaign_paths:
        campaign = load_campaign_manifest(campaign_path)
        namespaces = list(Path(campaign.checkpoint_root).glob("*/manifest.json"))
        for batch in campaign.batches:
            matches = []
            for marker in namespaces:
                namespace = json.loads(marker.read_text(encoding="utf-8"))
                provenance = namespace["provenance"]
                if (
                    provenance["config_hash"] == batch.config_hash
                    and provenance["code_commit"] == campaign.code_commit
                ):
                    matches.append(marker.parent)
            if len(matches) != 1:
                raise ValueError(f"{batch.batch_id}: exact native namespace is not unique")
            directory = matches[0]
            status = read_checkpoint_status(directory)
            provenance = status["provenance"]
            if checkpoint_id_for_provenance(provenance) != directory.name:
                raise ValueError("checkpoint namespace content identity mismatch")
            verified = 0
            imported = []
            for unit_id, unit in status["units"].items():
                if unit["status"] != "SUCCEEDED":
                    continue
                artifact = directory / "folds" / unit_id
                metadata = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
                _authenticate_metadata(metadata, description="fold checkpoint")
                if (
                    metadata["checkpoint_id"] != directory.name
                    or metadata["unit_id"] != unit_id
                    or metadata["evidence"] != unit["evidence"]
                ):
                    raise ValueError("fold identity/evidence mismatch")
                parquet = artifact / "oof.parquet"
                if sha(parquet) != metadata["parquet_sha256"]:
                    raise ValueError("fold byte identity mismatch")
                frame = pd.read_parquet(parquet)
                if (
                    len(frame) != metadata["rows"]
                    or list(frame) != metadata["columns"]
                    or _frame_hash(frame) != metadata["frame_sha256"]
                ):
                    raise ValueError("fold logical identity mismatch")
                if "import_lineage" in metadata:
                    imported.append(
                        {
                            "lineage": metadata["import_lineage"],
                            "evidence": unit["evidence"],
                            "frame_sha256": metadata["frame_sha256"],
                        }
                    )
                del frame
                verified += 1
            if imported:
                # Authenticate historical recovery against its genuine archived source,
                # not the newer application under development. Do not rewrite any proof.
                source = native_sources / campaign.code_commit / "src"
                if not (source / "stock_ai/ml/checkpoint_import.py").is_file():
                    raise ValueError("archive the exact native commit before lineage audit")
                program = (
                    "import json,sys; from stock_ai.ml.checkpoint_import import "
                    "authenticate_fold_import_lineage as verify; p=json.load(sys.stdin); "
                    "[verify(i['lineage'], destination_provenance=p['provenance'], "
                    "evidence=i['evidence'], frame_sha256=i['frame_sha256']) "
                    "for i in p['items']]"
                )
                subprocess.run(
                    [sys.executable, "-c", program],
                    check=True,
                    text=True,
                    input=json.dumps({"provenance": provenance, "items": imported}),
                    env={**os.environ, "PYTHONPATH": str(source.resolve())},
                )
            results.append(
                {
                    "batch_id": batch.batch_id,
                    "checkpoint_id": directory.name,
                    "code_commit": campaign.code_commit,
                    "verified_successful_units": verified,
                    "unit_counts": status["unit_counts"],
                }
            )
            print(f"verified {batch.batch_id}: {verified} checkpoint units", flush=True)
    return results


def audit_label_times(
    dataset: Path, feature_selection_path: Path, campaign_paths: list[Path]
) -> list[dict[str, object]]:
    selection = load_development_feature_selection(feature_selection_path)
    metadata = json.loads(dataset.with_suffix(".json").read_text(encoding="utf-8"))
    _authenticate_metadata(metadata, description="production dataset")
    if (
        metadata["snapshot_id"] != selection.data_snapshot_id
        or sha(dataset) != metadata["parquet_sha256"]
    ):
        raise ValueError("source dataset differs from authenticated campaign snapshot")
    connection = duckdb.connect()
    results = []
    reports: dict[int, AdvancedResearchReport] = {}
    for campaign_path in campaign_paths:
        for batch in load_campaign_manifest(campaign_path).batches:
            if batch.oof_path is None or batch.report_id is None:
                raise ValueError("completed report is required")
            path = Path(batch.oof_path).parent / f"{batch.report_id}.json"
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            _authenticate_metadata(wrapper, description="advanced report")
            report = AdvancedResearchReport.model_validate(wrapper["report"])
            if report.data_snapshot_id != selection.data_snapshot_id:
                raise ValueError("report belongs to another dataset")
            prior = reports.get(batch.horizon)
            fields = ("initial_train_periods", "validation_periods", "step_periods")
            if prior and (
                any(getattr(prior.config, k) != getattr(report.config, k) for k in fields)
                or prior.stage_boundaries != report.stage_boundaries
            ):
                raise ValueError("candidate split contracts disagree")
            reports[batch.horizon] = report
    try:
        for horizon in (5, 20):
            report = reports[horizon]
            stage = report.stage_boundaries[0]
            # Predicate excludes the holdout before projecting any label or target.
            grouped = connection.execute(
                f"""
                SELECT trading_date, min(as_of) AS cutoff,
                       min(label_entry_date) AS entry,
                       max(label_end_date_{horizon}d) AS label_end,
                       max(label_available_at_{horizon}d) AS available,
                       count(*) AS rows
                FROM read_parquet(?)
                WHERE trading_date < CAST(? AS TIMESTAMP)
                  AND label_end_date_{horizon}d < CAST(? AS TIMESTAMP)
                  AND label_status_{horizon}d = 'AVAILABLE'
                  AND target_return_{horizon}d IS NOT NULL
                GROUP BY trading_date ORDER BY trading_date
            """,
                [str(dataset), selection.locked_holdout_start, selection.locked_holdout_start],
            ).df()
            splitter = PurgedExpandingWindowSplitter(
                initial_train_periods=report.config.initial_train_periods,
                validation_periods=report.config.validation_periods,
                step_periods=report.config.step_periods,
                embargo_periods=horizon,
                label_horizon_periods=horizon,
            )
            observed_outer = set()
            for fold in splitter.split(grouped, label_end_column="label_end"):
                train = grouped.iloc[list(fold.train_indices)]
                valid = grouped.iloc[list(fold.validation_indices)]
                cutoff = pd.to_datetime(valid.cutoff, utc=True).min()
                latest_available = pd.to_datetime(train.available, utc=True).max()
                if latest_available >= cutoff or train.available.isna().any():
                    raise ValueError(
                        f"{horizon}d fold {fold.fold_number}: immature training labels"
                    )
                if pd.to_datetime(train.label_end).max() >= pd.to_datetime(valid.entry).min():
                    raise ValueError("closed label intervals overlap")
                outer = valid.loc[valid.trading_date >= pd.Timestamp(stage.model_evaluation_start)]
                if not outer.empty:
                    observed_outer.add(
                        (
                            fold.fold_number,
                            str(outer.trading_date.min().date()),
                            str(outer.trading_date.max().date()),
                        )
                    )
                results.append(
                    {
                        "horizon": horizon,
                        "fold": fold.fold_number,
                        "training_rows": int(train.rows.sum()),
                        "validation_rows": int(valid.rows.sum()),
                        "cutoff": cutoff.isoformat(),
                        "latest_training_label_available": latest_available.isoformat(),
                        "status": "PASS",
                        "outer_evaluation_rows": int(outer.rows.sum()),
                    }
                )
            expected_outer = {
                (item.fold, item.validation_start, item.validation_end)
                for item in report.fold_results
            }
            if observed_outer != expected_outer:
                raise ValueError("reconstructed dates differ from actual candidate OOF folds")
            print(f"verified {horizon}d source label availability", flush=True)
    finally:
        connection.close()
    if sha(dataset) != metadata["parquet_sha256"]:
        raise ValueError("dataset changed during audit")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature-selection", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-sources", type=Path, required=True)
    args = parser.parse_args()
    receipt = {
        "schema_version": "daily-source-checkpoint-audit-v1",
        "checkpoint_results": audit_checkpoints(args.campaign, args.native_sources),
        "label_results": audit_label_times(args.dataset, args.feature_selection, args.campaign),
        "holdout_outcomes_evaluated": False,
        "limitation": (
            "Availability uses preserved single-vintage source declarations; "
            "historical receipt vintages remain incomplete."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

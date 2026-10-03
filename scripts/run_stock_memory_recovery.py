"""One explicitly planned CPU recovery; same config, no task/OS/provider changes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from stock_ai.cli import _advanced_experiment_record, _failed_advanced_experiment_record
from stock_ai.ml.advanced import (
    AdvancedResearchConfig,
    AdvancedResearchExecutionError,
    load_advanced_research_run,
    research_input_columns,
    run_advanced_research,
    write_advanced_research_run,
)
from stock_ai.ml.checkpoint import _file_sha256
from stock_ai.ml.checkpoint_import import authenticate_checkpoint_import_plan
from stock_ai.ml.experiments import ExperimentRegistry
from stock_ai.ml.production import (
    load_production_build_manifest,
    load_production_dataset_snapshot,
    load_production_feature_snapshot_metadata,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--worker-record", type=Path, required=True)
    parser.add_argument("--minimum-fit-headroom-gib", type=float, default=3.5)
    args = parser.parse_args()
    root = args.repository.resolve()
    assert Path.cwd().resolve() == root, "original relative snapshot paths require repository cwd"
    assert args.minimum_fit_headroom_gib >= 3.5
    assert os.environ.get("PANDAS_COPY_ON_WRITE") == "1"
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    provenance = plan["equivalence_proof"]["destination_provenance"]
    authenticate_checkpoint_import_plan(plan, provenance)
    pin = provenance["code_commit"]
    git = ["git", "-c", f"safe.directory={root}", "-C", str(root)]
    subprocess.run([*git, "cat-file", "-e", f"{pin}^{{commit}}"], check=True)
    assert (
        subprocess.run(
            [
                *git,
                "diff",
                "--quiet",
                pin,
                "--",
                "src",
                "scripts/run_stock_memory_recovery.py",
                "pyproject.toml",
                "uv.lock",
            ],
            check=False,
        ).returncode
        == 0
    )
    config = AdvancedResearchConfig.model_validate(provenance["config"])
    assert config.config_hash == provenance["config_hash"]
    assert (
        config.horizons == (5,) and config.model_families == ("catboost",) and config.seeds == (29,)
    )
    assert config.estimator_count == 300 and not config.run_ablations and config.run_diagnostics
    source = Path(plan["source_checkpoint_path"])
    source_before = {
        name: _file_sha256(source / name) for name in ("manifest.json", "progress.json")
    }
    selection_id = source.parent.name
    campaign_path = root / "artifacts/campaigns/goal3-candidates" / selection_id / "h5.json"
    campaign_before = _file_sha256(campaign_path)
    campaign = json.loads(campaign_path.read_text(encoding="utf-8-sig"))
    created_at = datetime.now(UTC)
    state = {
        "pid": os.getpid(),
        "started_at_utc": created_at.isoformat(),
        "code_commit": pin,
        "config_hash": config.config_hash,
        "config": config.model_dump(mode="json"),
        "minimum_fit_headroom_gib": args.minimum_fit_headroom_gib,
        "scratch_root": str(args.scratch_root.resolve()),
        "source_checkpoint": str(source),
        "worker_sha256": _file_sha256(Path(__file__)),
        "training_started": False,
        "new_model_fit_completion_verified": False,
    }

    def record(phase: str, **updates: object) -> None:
        state.update(updates, phase=phase, updated_at_utc=datetime.now(UTC).isoformat())
        args.worker_record.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"{state['updated_at_utc']} {phase}", flush=True)

    build = snapshot = run = v2 = None
    registry = ExperimentRegistry(root / "artifacts/experiments/advanced-memory-recovery.jsonl")
    record("AUTHENTICATING_INPUT")
    try:
        build = load_production_build_manifest(Path(campaign["build_manifest_path"]))
        assert build.v2_parquet_path is not None
        v2 = load_production_feature_snapshot_metadata(build.v2_parquet_path)
        assert v2.snapshot_id == provenance["feature_snapshot_id"]
        assert v2.manifest_hash == provenance["feature_manifest_hash"]
        snapshot, dataset = load_production_dataset_snapshot(
            build.dataset_parquet_path,
            columns=research_input_columns(config, tuple(provenance["feature_names"])),
        )
        assert snapshot.snapshot_id == provenance["data_snapshot_id"]
        record("INPUT_AUTHENTICATED", dataset_rows=len(dataset), input_columns=len(dataset.columns))
        record(
            "RESEARCH_PREPARATION",
            checkpoint_root=str(
                root / "artifacts/checkpoints/advanced-memory-recovery" / selection_id
            ),
        )
        run = run_advanced_research(
            dataset,
            data_snapshot_id=snapshot.snapshot_id,
            created_at=created_at,
            code_commit=pin,
            config=config,
            feature_snapshot_id=v2.snapshot_id,
            feature_manifest_hash=v2.manifest_hash,
            feature_names=tuple(provenance["feature_names"]),
            checkpoint_root=root / "artifacts/checkpoints/advanced-memory-recovery" / selection_id,
            checkpoint_import_plan=args.plan,
            memory_scratch_root=args.scratch_root,
            release_source_frame=True,
            minimum_fit_headroom_gib=args.minimum_fit_headroom_gib,
        )
        metadata, oof = write_advanced_research_run(
            run, root / "artifacts/reports/advanced-memory-recovery"
        )
        load_advanced_research_run(oof)
        registry.append(
            _advanced_experiment_record(
                run,
                experiment_id=f"advanced-memory-{uuid4()}",
                build_id=build.build_id,
                metadata_path=metadata,
                oof_path=oof,
            )
        )
        assert source_before == {name: _file_sha256(source / name) for name in source_before}
        assert campaign_before == _file_sha256(campaign_path)
        record(
            "COMPLETED",
            report_id=run.report.report_id,
            report_metadata=str(metadata),
            oof_path=str(oof),
            training_started=True,
            new_model_fit_completion_verified=True,
            source_checkpoint_unchanged=True,
            original_campaign_unchanged=True,
        )
        return 0
    except Exception as exc:
        execution = exc if isinstance(exc, AdvancedResearchExecutionError) else None
        registry.append(
            _failed_advanced_experiment_record(
                experiment_id=f"advanced-memory-{uuid4()}",
                created_at=created_at,
                code_commit=pin,
                config=config,
                raw_config=config.model_dump(mode="json"),
                data_snapshot_id=snapshot.snapshot_id
                if snapshot is not None
                else provenance["data_snapshot_id"],
                reason=f"{type(exc).__name__}: {str(exc)[:500]}",
                trial_contexts=execution.trial_contexts if execution is not None else (),
                fold_results=execution.fold_results if execution is not None else (),
                build_id=build.build_id if build is not None else None,
                feature_snapshot_id=v2.snapshot_id if v2 is not None else None,
            )
        )
        blocked = "before fit available physical RAM" in str(exc)
        record("BLOCKED_BEFORE_FIT" if blocked else "FAILED", error=f"{type(exc).__name__}: {exc}")
        print(state["error"], flush=True)
        return 2 if blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())

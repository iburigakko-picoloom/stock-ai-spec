"""One fresh seed43 research attempt using unchanged authenticated stock-ai code."""
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
import argparse
import hashlib
import json
import os
import subprocess

from stock_ai.cli import _advanced_experiment_record, _failed_advanced_experiment_record
from stock_ai.ml.advanced import (
    AdvancedResearchConfig, AdvancedResearchExecutionError, load_advanced_research_run,
    research_input_columns, run_advanced_research, write_advanced_research_run,
)
from stock_ai.ml.campaign import (
    CampaignBatchStatus, authenticate_batch_artifact, campaign_batch_checkpoint_path,
    load_campaign_manifest, write_campaign_manifest,
)
from stock_ai.ml.checkpoint import _file_sha256, checkpoint_id_for_provenance
from stock_ai.ml.experiments import ExperimentRegistry
from stock_ai.ml.production import (
    load_production_build_manifest, load_production_dataset_snapshot,
    load_production_feature_snapshot_metadata,
)
from stock_ai.ml.selection import _authenticate_batch_report

def stable(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), default=str).encode()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--worker-record', type=Path, required=True)
    parser.add_argument('--scratch-root', type=Path, required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    root = args.repository.resolve()
    assert Path.cwd().resolve() == root
    assert os.environ.get('PANDAS_COPY_ON_WRITE') == '1'
    manifest = load_campaign_manifest(args.campaign)
    link_path = args.campaign.parent/'continuation-link.json'
    link = json.loads(link_path.read_text(encoding='utf-8'))
    assert stable({key: value for key, value in link.items() if key != 'metadata_hash'}) == link['metadata_hash']
    assert link['continuation_source_pin'] == manifest.code_commit
    original_path = Path(link['original_campaign_path'])
    assert _file_sha256(original_path) == link['original_campaign_sha256']
    original = load_campaign_manifest(original_path)
    assert original.campaign_id == link['original_campaign_id']
    assert original.build_id == manifest.build_id
    batch = next(batch for batch in manifest.batches if batch.batch_id == 'h5-catboost-s43')
    expected = next(batch for batch in original.batches if batch.batch_id == 'h5-catboost-s43')
    assert expected.status is CampaignBatchStatus.PENDING and expected.attempts == 0
    assert batch.status is CampaignBatchStatus.PENDING and batch.attempts == 0
    assert batch.config_hash == expected.config_hash and batch.feature_names_hash == expected.feature_names_hash
    features = tuple(manifest.common_config['feature_names'])
    assert len(features) == 41 and features == tuple(original.common_config['feature_names'])
    assert {k: v for k, v in manifest.common_config.items() if k != 'seeds'} == {
        k: v for k, v in original.common_config.items() if k != 'seeds'}
    config = AdvancedResearchConfig.model_validate({
        **{key: value for key, value in manifest.common_config.items() if key != 'feature_names'},
        'horizons': (5,), 'model_families': ('catboost',), 'seeds': (43,),
    })
    assert config.config_hash == batch.config_hash
    assert config.estimator_count == 300 and not config.run_ablations and config.run_diagnostics
    assert config.tuning_trials == 20 and config.tuning_timeout_seconds == 900
    provenance = link['seed43_provenance']
    assert provenance['config'] == config.model_dump(mode='json') and provenance['config_hash'] == config.config_hash
    assert provenance['code_commit'] == manifest.code_commit and tuple(provenance['feature_names']) == features
    assert provenance['locked_holdout_accessed'] is False
    checkpoint = Path(manifest.checkpoint_root)/checkpoint_id_for_provenance(provenance)
    assert checkpoint == Path(link['seed43_checkpoint']) and not checkpoint.exists(), 'Fresh seed43 only; no automatic resume.'
    pin = manifest.code_commit
    git = ['git', '-c', f'safe.directory={root}', '-C', str(root)]
    subprocess.run([*git, 'cat-file', '-e', f'{pin}^{{commit}}'], check=True)
    assert subprocess.run([*git, 'diff', '--quiet', pin, '--', 'src', 'pyproject.toml', 'uv.lock']).returncode == 0
    assert not subprocess.check_output([*git, 'ls-files', '--others', '--exclude-standard', '--', 'src']).strip()
    if args.validate_only:
        print(json.dumps({'validated': True, 'no_fit_started': True, 'config_hash': config.config_hash,
                          'checkpoint_path': str(checkpoint), 'source_pin': pin, 'worker_sha256': _file_sha256(Path(__file__))}))
        return 0

    args.worker_record.parent.mkdir(parents=True, exist_ok=True)
    # Persistent exclusive intent ensures this continuation is attempted once.
    exclusive = os.open(args.campaign.parent/'seed43.single-attempt.lock', os.O_WRONLY|os.O_CREAT|os.O_EXCL)
    os.write(exclusive, str(os.getpid()).encode())
    os.close(exclusive)
    started = datetime.now(UTC)
    state = {'pid': os.getpid(), 'started_at_utc': started.isoformat(), 'code_commit': pin,
             'config_hash': config.config_hash, 'config': config.model_dump(mode='json'),
             'minimum_fit_headroom_gib': 3.5, 'checkpoint_path': str(checkpoint),
             'worker_sha256': _file_sha256(Path(__file__)), 'scientific_source_unchanged': True,
             'seed29_predictions_reused': False, 'training_started': False, 'error': None}
    def record(phase, **updates):
        state.update(updates, phase=phase, updated_at_utc=datetime.now(UTC).isoformat())
        temporary = args.worker_record.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, args.worker_record)
        print(f"{state['updated_at_utc']} {phase}", flush=True)

    build = snapshot = v2 = None
    registry = ExperimentRegistry(Path(manifest.experiment_registry))
    batch.status, batch.attempts = CampaignBatchStatus.RUNNING, 1
    batch.started_at, batch.child_pid = started, os.getpid()
    batch.log_path = str(args.worker_record.parent/'worker.stdout.log')
    write_campaign_manifest(manifest, args.campaign)
    record('AUTHENTICATING_INPUT')
    try:
        build = load_production_build_manifest(Path(manifest.build_manifest_path))
        assert build.build_id == manifest.build_id and build.v2_parquet_path is not None
        v2 = load_production_feature_snapshot_metadata(build.v2_parquet_path)
        snapshot, dataset = load_production_dataset_snapshot(
            build.dataset_parquet_path, columns=research_input_columns(config, features))
        assert snapshot.snapshot_id == build.dataset_snapshot_id and v2.snapshot_id == build.v2_snapshot_id
        assert snapshot.snapshot_id == provenance['data_snapshot_id'] and v2.snapshot_id == provenance['feature_snapshot_id']
        assert v2.manifest_hash == provenance['feature_manifest_hash']
        record('INPUT_AUTHENTICATED', dataset_rows=len(dataset), input_columns=len(dataset.columns))
        record('RESEARCH_PREPARATION')
        run = run_advanced_research(
            dataset, data_snapshot_id=snapshot.snapshot_id, created_at=started, code_commit=pin,
            config=config, feature_snapshot_id=v2.snapshot_id, feature_manifest_hash=v2.manifest_hash,
            feature_names=features, checkpoint_root=Path(manifest.checkpoint_root),
            memory_scratch_root=args.scratch_root, release_source_frame=True,
            minimum_fit_headroom_gib=3.5,
        )
        metadata, oof_path = write_advanced_research_run(run, Path(manifest.report_root))
        report, frame = load_advanced_research_run(oof_path)
        report_id, authenticated_path = authenticate_batch_artifact(batch, code_commit=pin, oof_path=oof_path)
        batch.report_id, batch.oof_path = report_id, authenticated_path
        _authenticate_batch_report(manifest, batch, report)
        assert not report.locked_holdout_accessed and not report.adoption_eligible
        del frame
        registry.append(_advanced_experiment_record(
            run, experiment_id=f'advanced-seed43-continuation-{uuid4()}', build_id=build.build_id,
            metadata_path=metadata, oof_path=oof_path))
        assert _file_sha256(original_path) == link['original_campaign_sha256']
        batch.status, batch.child_pid = CampaignBatchStatus.SUCCEEDED, None
        batch.completed_at, batch.last_error = datetime.now(UTC), None
        write_campaign_manifest(manifest, args.campaign)
        record('COMPLETED', report_id=report_id, report_metadata=str(metadata), oof_path=str(oof_path),
               training_started=True, new_model_fit_completion_verified=True,
               original_campaign_history_preserved=True, research_only=True)
        return 0
    except Exception as exc:
        execution = exc if isinstance(exc, AdvancedResearchExecutionError) else None
        reason = f'{type(exc).__name__}: {exc}'
        registry.append(_failed_advanced_experiment_record(
            experiment_id=f'advanced-seed43-continuation-{uuid4()}', created_at=started,
            code_commit=pin, config=config, raw_config=config.model_dump(mode='json'),
            data_snapshot_id=snapshot.snapshot_id if snapshot is not None else 'INPUT_NOT_AUTHENTICATED',
            reason=reason[:500], trial_contexts=execution.trial_contexts if execution else (),
            fold_results=execution.fold_results if execution else (),
            build_id=build.build_id if build is not None else None,
            feature_snapshot_id=v2.snapshot_id if v2 is not None else None))
        batch.status, batch.child_pid = CampaignBatchStatus.FAILED, None
        batch.completed_at, batch.last_error = datetime.now(UTC), reason[:500]
        write_campaign_manifest(manifest, args.campaign)
        blocked = 'before fit available physical RAM' in str(exc)
        record('BLOCKED_BEFORE_FIT' if blocked else 'FAILED', error=reason)
        return 2 if blocked else 1

if __name__ == '__main__':
    raise SystemExit(main())

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from stock_ai.ml.advanced import _frame_hash
from stock_ai.ml.campaign import CampaignBatchStatus, load_campaign_manifest, write_campaign_manifest
from stock_ai.ml.checkpoint import ResearchCheckpointStore

BASE = Path(__file__).resolve().parent
OUT = BASE / 'stock-h20-adaptive-resume-20261008'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    assert not OUT.exists()
    active = read(BASE / 'stock-active-runtime.json')
    worker = read(active['WorkerRecord'])
    old_receipt = read(Path(active['Runtime']).parent / 'plan-receipt.json')
    manifest = load_campaign_manifest(Path(active['CampaignManifest']))
    assert len(manifest.batches) == 9 and len(manifest.common_config['feature_names']) == 51
    assert manifest.batches[0].status is CampaignBatchStatus.FAILED
    assert all(b.status is CampaignBatchStatus.PENDING for b in manifest.batches[1:])
    cp = Path(worker['checkpoint_path'])
    progress = read(cp / 'progress.json')
    succeeded = [u for u in progress['units'].values() if u['status'] == 'SUCCEEDED']
    assert len(succeeded) == 7 and all(u['evidence']['checkpoint_scope'] == 'optuna-tuning' for u in succeeded)
    OUT.mkdir()
    before = OUT / 'before'
    before.mkdir()
    for name, path in {'active-runtime.json': BASE / 'stock-active-runtime.json',
        'campaign.json': Path(active['CampaignManifest']), 'worker.json': Path(active['WorkerRecord']),
        'worker.stdout.log': Path(active['Runtime']) / 'worker.stdout.log',
        'worker.stderr.log': Path(active['Runtime']) / 'worker.stderr.log',
        'advanced.jsonl': Path(active['ExperimentRegistry'])}.items():
        shutil.copy2(path, before / name)
    shutil.copytree(cp, before / 'checkpoint')
    original_hashes = {str(p.relative_to(cp)): sha(p) for p in cp.rglob('*') if p.is_file() and p.name != 'writer.lock'}
    prov = old_receipt['provenance_by_batch'][worker['batch_id']]['provenance']
    store = ResearchCheckpointStore(Path(active['CheckpointRoot']), provenance=prov)
    try:
        for unit in succeeded:
            frame = store.load_fold(unit['evidence'], frame_hash=_frame_hash)
            assert frame is not None
            del frame
    finally:
        store.close()
    assert all(sha(cp / name) == digest for name, digest in original_hashes.items())
    with sqlite3.connect((cp / 'optuna.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        trials = db.execute('SELECT state, datetime_start, datetime_complete FROM trials').fetchall()
    assert len(trials) == 7 and all(row[0] == 'COMPLETE' for row in trials)
    elapsed = sum((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
                  for _, start, end in trials)
    assert elapsed >= manifest.common_config['tuning_timeout_seconds']
    previous_checks = []
    for path in (Path(active['Runtime']) / 'scratch').rglob('*.fit-headroom.json'):
        previous_checks.extend(read(path))
    resident_drop = worker['before_candidate_available_gib'] - min(
        float(check['available_gib_before_unused_cleanup']) for check in previous_checks)
    receipt = {**old_receipt, 'original_runtime': active['Runtime'],
        'runtime_policy_sha256': sha(BASE / 'stock_runtime_memory.py'),
        'preparation_required_gib': 1.25 + resident_drop + .25,
        'reuse_tuning_for_batch': worker['batch_id'], 'authenticated_tuning_successes': 7,
        'prior_tuning_elapsed_seconds': elapsed, 'checkpoint_hashes_before': original_hashes,
        'no_new_tuning_budget': True, 'execution_policy': 'adaptive-input-and-observed-increment-v1',
        'os_reserve_gib': 1.25, 'emergency_os_available_gib': .5,
        'waiting_poll_seconds_in_learning_process': 60}
    (OUT / 'plan-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    source = (BASE / 'stock_h20_spill_retry_worker.py').read_text(encoding='utf-8')
    source = source.replace("OUT=BASE/'stock-h20-spill-retry-20261008'", "OUT=BASE/'stock-h20-adaptive-resume-20261008'")
    source = source.replace('import sys\n', 'import sys\nimport time\nfrom stock_runtime_memory import AdaptiveMemoryPolicy, MemorySafetyStop\n')
    source = source.replace("'minimum_fit_headroom_gib':3.5", "'minimum_fit_headroom_gib':None,'os_reserve_gib':1.25,'runtime_policy':'adaptive-input-and-observed-increment-v1'")
    source = source.replace("    record('STARTED')", "    assert _file_sha256(BASE/'stock_runtime_memory.py')==receipt['runtime_policy_sha256']\n    policy=AdaptiveMemoryPolicy(RUNTIME/'memory-policy.jsonl',notify=record)\n    policy.install()\n    record('STARTED',authenticated_reused_tuning_successes=receipt['authenticated_tuning_successes'])")
    start = source.index('        available=_available_physical_bytes()/1024**3')
    end = source.index('        started=datetime.now(UTC)', start)
    source = source[:start] + '''        available=_available_physical_bytes()/1024**3
        required=receipt['preparation_required_gib']
        while available<required:
            record('WAITING_PREPARATION_MEMORY',available_gib=available,required_gib=required)
            gc.collect()
            import pyarrow as pa
            pa.default_memory_pool().release_unused()
            time.sleep(60)
            available=_available_physical_bytes()/1024**3
        record('PREPARATION_ADMITTED',available_gib=available,required_gib=required)
''' + source[end:]
    source = source.replace('minimum_fit_headroom_gib=3.5,spill_development_during_tuning=True)',
        "minimum_fit_headroom_gib=0.0,spill_development_during_tuning=(batch.batch_id!=receipt['reuse_tuning_for_batch']))")
    source = source.replace("record('BLOCKED_BEFORE_FIT' if 'before fit available physical RAM' in str(exc) else 'FAILED',error=reason)",
        "record('ACTUAL_OS_MEMORY_EMERGENCY' if policy.emergency else 'FAILED',error=reason)")
    source = source.replace("if __name__=='__main__': raise SystemExit(main())", '''if __name__=='__main__':
    try:
        raise SystemExit(main())
    except MemorySafetyStop as exc:
        path=RUNTIME/'worker.json'
        state=read(path)
        state.update(phase='ACTUAL_OS_MEMORY_EMERGENCY',error=str(exc),updated_at_utc=datetime.now(UTC).isoformat())
        path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
        manifest=load_campaign_manifest(Path(state['campaign_path']))
        batch=next(b for b in manifest.batches if b.batch_id==state['batch_id'])
        batch.status=CampaignBatchStatus.FAILED; batch.child_pid=None; batch.last_error=str(exc)
        batch.completed_at=datetime.now(UTC)
        write_campaign_manifest(manifest,Path(state['campaign_path']))
        raise SystemExit(2)
''')
    import ast
    ast.parse(source)
    (BASE / 'stock_h20_adaptive_worker.py').write_text(source, encoding='utf-8')
    manifest.batches[0].status = CampaignBatchStatus.PENDING
    manifest.batches[0].child_pid = None
    write_campaign_manifest(manifest, Path(active['CampaignManifest']))
    print(json.dumps({'prepared_only': True, 'authenticated_reused_tuning': 7,
        'elapsed_prior_tuning_seconds': elapsed, 'new_tuning_budget': False,
        'preparation_required_gib': receipt['preparation_required_gib'], 'checkpoint_path': str(cp)}, ensure_ascii=False))


if __name__ == '__main__':
    main()

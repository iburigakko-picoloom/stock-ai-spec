import ast
import hashlib
import json
import shutil
from datetime import datetime, UTC
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / 'stock-h20-quantile-once-20261011'


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    assert not (OUT/'plan-receipt.json').exists()
    active=read(BASE/'stock-active-runtime.json')
    w=read(active['WorkerRecord'])
    assert w['phase']=='WAITING_FOR_MEMORY'
    assert (w['batch_id'],w['task'],w['fold'])==('h20-catboost-s17','quantile',5)
    cp=Path(w['checkpoint_path']); progress=read(cp/'progress.json')
    success=[u for u in progress['units'].values() if u['status']=='SUCCEEDED']
    assert len(success)==19
    assert len([u for u in success if u['evidence']['task']=='quantile'])==4
    manifest=read(active['CampaignManifest'])
    assert len([b for b in manifest['batches'] if b['status']=='SUCCEEDED'])==6
    assert len(manifest['common_config']['feature_names'])==51
    OUT.mkdir(exist_ok=True); before=OUT/'verified-before'; before.mkdir()
    paths={'active-runtime.json':BASE/'stock-active-runtime.json',
           'campaign.json':Path(active['CampaignManifest']),
           'worker-source.py':BASE/'stock_h20_adaptive_worker.py',
           'original-policy.py':BASE/'stock_runtime_memory.py',
           'old-plan.json':Path(active['Runtime']).parent/'plan-receipt.json'}
    for name,p in paths.items(): shutil.copy2(p,before/name)
    shutil.copytree(Path(active['Runtime']),before/'runtime',ignore=shutil.ignore_patterns('scratch'))
    # The live OS lock contains no scientific state and cannot be copied on Windows.
    shutil.copytree(cp,before/'checkpoint',ignore=shutil.ignore_patterns('writer.lock'))
    hashes={str(p.relative_to(cp)):sha(p) for p in cp.rglob('*')
            if p.is_file() and p.name!='writer.lock'}
    assert all(sha(before/'checkpoint'/n)==h for n,h in hashes.items())
    assert all(sha(cp/n)==h for n,h in hashes.items())
    for unit in success:
        fold=Path(unit['artifact']); fm=read(fold/'manifest.json')
        # Inspect native artifact metadata without loading model data.
        assert (fold/'oof.parquet').exists()
        assert fm
    receipt=read(before/'old-plan.json')
    receipt.update(runtime_policy_sha256=sha(BASE/'stock_quantile_once_policy.py'),
                   base_policy_sha256=sha(BASE/'stock_runtime_memory.py'),
                   reuse_tuning_for_batch='h20-catboost-s17',
                   authenticated_tuning_successes=5,
                   execution_policy='adaptive-plus-one-cat17-quantile-fold5',
                   original_runtime=active['Runtime'],
                   checkpoint_hashes_before=hashes,
                   authorized_override={'batch':'h20-catboost-s17','task':'quantile','fold':5,
                       'horizon':20,'scope':'outer-model-evaluation','factor':3.5,'once':True},
                   prepared_at_utc=datetime.now(UTC).isoformat())
    (OUT/'plan-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    source=(BASE/'stock_h20_adaptive_worker.py').read_text(encoding='utf-8')
    source=source.replace('from stock_runtime_memory import AdaptiveMemoryPolicy, MemorySafetyStop',
        'from stock_runtime_memory import MemorySafetyStop\nfrom stock_quantile_once_policy import QuantileOncePolicy as AdaptiveMemoryPolicy')
    source=source.replace("OUT=BASE/'stock-h20-adaptive-resume-20261008'", "OUT=BASE/'stock-h20-quantile-once-20261011'")
    source=source.replace("BASE/'stock_runtime_memory.py')==receipt['runtime_policy_sha256']",
        "BASE/'stock_quantile_once_policy.py')==receipt['runtime_policy_sha256']\n    assert _file_sha256(BASE/'stock_runtime_memory.py')==receipt['base_policy_sha256']")
    source=source.replace('        config=AdvancedResearchConfig.model_validate({',
        '        policy.batch_id=batch.batch_id\n        config=AdvancedResearchConfig.model_validate({')
    ast.parse(source)
    (BASE/'stock_h20_quantile_once_worker.py').write_text(source,encoding='utf-8')
    (OUT/'backup-verification.json').write_text(json.dumps({'at':datetime.now(UTC).isoformat(),
       'old_pid':w['pid'],'successful_units':19,'files_verified':len(hashes),
       'checkpoint':str(cp),'checkpoint_hashes':hashes,
       'original_policy_sha256':receipt['base_policy_sha256'],
       'no_campaign_mutation_yet':True},indent=2),encoding='utf-8')
    print(json.dumps({'prepared':True,'old_pid':w['pid'],'saved_successful_units':19,
                      'backup_files_verified':len(hashes),'output':str(OUT)}))


if __name__=='__main__':
    main()

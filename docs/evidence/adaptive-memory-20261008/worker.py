"""Single sequential D084 h20 worker; unchanged native research/checkpoint APIs."""
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
import gc
import json
import os
import subprocess
import sys
import time
from stock_runtime_memory import AdaptiveMemoryPolicy, MemorySafetyStop

from stock_ai.cli import _advanced_experiment_record, _failed_advanced_experiment_record
from stock_ai.ml.advanced import (AdvancedResearchConfig, AdvancedResearchExecutionError,
    load_advanced_research_run, research_input_columns, run_advanced_research, write_advanced_research_run)
from stock_ai.ml.campaign import CampaignBatchStatus, authenticate_batch_artifact, load_campaign_manifest, write_campaign_manifest
from stock_ai.ml.checkpoint import _file_sha256, checkpoint_id_for_provenance
from stock_ai.ml.experiments import ExperimentRegistry
from stock_ai.ml.memory import _available_physical_bytes
from stock_ai.ml.production import (load_production_build_manifest, load_production_dataset_snapshot,
    load_production_feature_snapshot_metadata)
from stock_ai.ml.selection import _authenticate_batch_report, load_development_feature_selection

ROOT=Path('C:/Users/manat/app/\u682aAI/stock-ai-spec')
BASE=Path(__file__).resolve().parent
OUT=BASE/'stock-h20-adaptive-resume-20261008'
RUNTIME=OUT/'runtime'
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def main():
    assert Path.cwd().resolve()==ROOT
    assert os.environ.get('PANDAS_COPY_ON_WRITE')=='1'
    receipt=read(OUT/'plan-receipt.json')
    launch=read(RUNTIME/'launch-receipt.json')
    assert _file_sha256(Path(__file__))==launch['worker_sha256']
    assert _file_sha256(OUT/'plan-receipt.json')==launch['plan_receipt_sha256']
    campaign_path=Path(receipt['campaign_path'])
    manifest=load_campaign_manifest(campaign_path)
    pin=receipt['source_pin']
    assert manifest.code_commit==pin and manifest.common_config==receipt['common_config']
    features=tuple(manifest.common_config['feature_names'])
    feature_plan=load_development_feature_selection(Path(receipt['feature_selection_path']))
    assert _file_sha256(Path(receipt['feature_selection_path']))==receipt['feature_selection_sha256']
    assert features==next(h.feature_names for h in feature_plan.horizons if h.horizon==20)
    assert len(features)==51 and len(manifest.batches)==9
    git=['git','-c',f'safe.directory={ROOT}','-C',str(ROOT)]
    assert subprocess.run([*git,'diff','--quiet',pin,'--','src','pyproject.toml','uv.lock']).returncode==0
    exclusive=os.open(RUNTIME/'worker.single-attempt.lock',os.O_WRONLY|os.O_CREAT|os.O_EXCL)
    os.write(exclusive,str(os.getpid()).encode()); os.close(exclusive)
    state={'pid':os.getpid(),'started_at_utc':datetime.now(UTC).isoformat(),'code_commit':pin,
           'campaign_path':str(campaign_path),'campaign_id':manifest.campaign_id,'feature_count':51,
           'minimum_fit_headroom_gib':None,'os_reserve_gib':1.25,'runtime_policy':'adaptive-input-and-observed-increment-v1','threads':1,'research_only':True,'error':None,
           'completed_batches':[],'worker_sha256':_file_sha256(Path(__file__))}
    def record(phase,**updates):
        state.update(updates,phase=phase,updated_at_utc=datetime.now(UTC).isoformat())
        path=RUNTIME/'worker.json'; tmp=path.with_suffix('.tmp')
        tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8'); os.replace(tmp,path)
        print(f'{state["updated_at_utc"]} {phase} {state.get("batch_id", "")}',flush=True)
    assert _file_sha256(BASE/'stock_runtime_memory.py')==receipt['runtime_policy_sha256']
    policy=AdaptiveMemoryPolicy(RUNTIME/'memory-policy.jsonl',notify=record)
    policy.install()
    record('STARTED',authenticated_reused_tuning_successes=receipt['authenticated_tuning_successes'])
    registry=ExperimentRegistry(Path(manifest.experiment_registry))
    for batch in manifest.batches:
        config=AdvancedResearchConfig.model_validate({
            **{k:v for k,v in manifest.common_config.items() if k!='feature_names'},
            'horizons':(20,),'model_families':(batch.model_family,),'seeds':(batch.seed,)})
        assert config.config_hash==batch.config_hash
        expected=receipt['provenance_by_batch'][batch.batch_id]
        checkpoint=Path(manifest.checkpoint_root)/checkpoint_id_for_provenance(expected['provenance'])
        assert checkpoint==Path(expected['checkpoint_path'])
        if batch.status is CampaignBatchStatus.SUCCEEDED:
            report,frame=load_advanced_research_run(Path(batch.oof_path))
            _authenticate_batch_report(manifest,batch,report)
            del report,frame; gc.collect()
            state['completed_batches'].append(batch.batch_id)
            record('REUSED_AUTHENTICATED_BATCH',batch_id=batch.batch_id)
            continue
        if batch.status is not CampaignBatchStatus.PENDING:
            record('STOPPED_REQUIRES_EXPLICIT_RESUME',batch_id=batch.batch_id,error='Prior non-PENDING state; no automatic retry.')
            return 2
        available=_available_physical_bytes()/1024**3
        required=receipt['preparation_required_gib']
        while available<required:
            record('WAITING_PREPARATION_MEMORY',available_gib=available,required_gib=required)
            gc.collect()
            import pyarrow as pa
            pa.default_memory_pool().release_unused()
            time.sleep(60)
            available=_available_physical_bytes()/1024**3
        record('PREPARATION_ADMITTED',available_gib=available,required_gib=required)
        started=datetime.now(UTC)
        batch.status=CampaignBatchStatus.RUNNING; batch.attempts+=1
        batch.started_at=started; batch.child_pid=os.getpid()
        batch.log_path=str(RUNTIME/'worker.stdout.log')
        write_campaign_manifest(manifest,campaign_path)
        scratch=RUNTIME/'scratch'/batch.batch_id
        record('AUTHENTICATING_INPUT',batch_id=batch.batch_id,model_family=batch.model_family,
               seed=batch.seed,checkpoint_path=str(checkpoint),config_hash=config.config_hash,
               before_candidate_available_gib=available)
        build=snapshot=v2=None
        try:
            build=load_production_build_manifest(Path(manifest.build_manifest_path))
            v2=load_production_feature_snapshot_metadata(build.v2_parquet_path)
            snapshot,dataset=load_production_dataset_snapshot(build.dataset_parquet_path,
                                      columns=research_input_columns(config,features))
            prov=expected['provenance']
            assert build.build_id==manifest.build_id and snapshot.snapshot_id==prov['data_snapshot_id']
            assert v2.snapshot_id==prov['feature_snapshot_id'] and v2.manifest_hash==prov['feature_manifest_hash']
            record('INPUT_AUTHENTICATED',dataset_rows=len(dataset),input_columns=len(dataset.columns))
            record('RESEARCH_PREPARATION')
            run=run_advanced_research(dataset,data_snapshot_id=snapshot.snapshot_id,created_at=started,
                code_commit=pin,config=config,feature_snapshot_id=v2.snapshot_id,feature_manifest_hash=v2.manifest_hash,
                feature_names=features,checkpoint_root=Path(manifest.checkpoint_root),memory_scratch_root=scratch,
                release_source_frame=True,minimum_fit_headroom_gib=0.0,spill_development_during_tuning=(batch.batch_id!=receipt['reuse_tuning_for_batch']))
            metadata,oof=write_advanced_research_run(run,Path(manifest.report_root))
            report,frame=load_advanced_research_run(oof)
            report_id,authenticated=authenticate_batch_artifact(batch,code_commit=pin,oof_path=oof)
            batch.report_id,batch.oof_path=report_id,authenticated
            _authenticate_batch_report(manifest,batch,report)
            assert not report.locked_holdout_accessed and not report.adoption_eligible
            registry.append(_advanced_experiment_record(run,experiment_id=f'advanced-h20-candidate-{uuid4()}',
                build_id=build.build_id,metadata_path=metadata,oof_path=oof))
            batch.status=CampaignBatchStatus.SUCCEEDED; batch.child_pid=None
            batch.completed_at=datetime.now(UTC); batch.last_error=None
            write_campaign_manifest(manifest,campaign_path)
            state['completed_batches'].append(batch.batch_id)
            record('BATCH_COMPLETED',report_id=report_id,report_metadata=str(metadata),oof_path=str(oof))
            del frame,report,run,dataset,snapshot,v2,build
            gc.collect()
        except Exception as exc:
            reason=f'{type(exc).__name__}: {exc}'
            execution=exc if isinstance(exc,AdvancedResearchExecutionError) else None
            registry.append(_failed_advanced_experiment_record(experiment_id=f'advanced-h20-candidate-{uuid4()}',
                created_at=started,code_commit=pin,config=config,raw_config=config.model_dump(mode='json'),
                data_snapshot_id=snapshot.snapshot_id if snapshot else 'INPUT_NOT_AUTHENTICATED',reason=reason[:500],
                trial_contexts=execution.trial_contexts if execution else (),fold_results=execution.fold_results if execution else (),
                build_id=build.build_id if build else None,feature_snapshot_id=v2.snapshot_id if v2 else None))
            batch.status=CampaignBatchStatus.FAILED; batch.child_pid=None
            batch.completed_at=datetime.now(UTC); batch.last_error=reason[:500]
            write_campaign_manifest(manifest,campaign_path)
            record('ACTUAL_OS_MEMORY_EMERGENCY' if policy.emergency else 'FAILED',error=reason)
            return 2
    record('COMPLETED',batch_id=None,all9_completed=True)
    return 0
if __name__=='__main__':
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


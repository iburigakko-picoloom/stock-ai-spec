"""Read-only D077 evidence audit; never trains or reads a holdout dataset."""
import json
from pathlib import Path

from stock_ai.ml.advanced import load_advanced_research_run
from stock_ai.ml.campaign import load_campaign_manifest

manifest = load_campaign_manifest(Path('artifacts/campaigns/goal3-screen-1d-v1.json'))
for batch in manifest.batches:
    assert batch.status == 'SUCCEEDED'
    path = Path(batch.oof_path)
    report, frame = load_advanced_research_run(path)
    assert report.report_id == batch.report_id
    assert report.config_hash == batch.config_hash
    assert report.code_commit == manifest.code_commit
    assert report.config.seeds == (batch.seed,)
    assert report.config.horizons == (1,)
    assert report.config.model_families == (batch.model_family,)
    assert not report.locked_holdout_accessed
    assert str(frame.trading_date.max())[:10] < str(report.locked_holdout_start)
    results = []
    for metric in report.model_metrics:
        if metric.task not in ('regression', 'ranking'):
            continue
        folds = [f.mean_daily_rank_ic for f in report.fold_results if f.task == metric.task]
        results.append({'task': metric.task, 'rank_ic': metric.mean_daily_rank_ic,
                        'positive_folds': sum(v is not None and v > 0 for v in folds),
                        'folds': len(folds)})
    print(json.dumps({'batch': batch.batch_id, 'report_id': report.report_id,
                      'authenticated': True, 'cost_status': report.cost_evaluation_status,
                      'metrics': results}), flush=True)
    del frame

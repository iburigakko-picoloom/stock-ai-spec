import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from stock_ai.ml.daily_baselines import BASELINES, _canonical, _scores
from stock_ai.ml.evaluation_metrics import evaluate_probabilities, evaluate_quantiles
from stock_ai.ml.production import _file_sha256

root = Path('artifacts/daily-ensemble')
paths = list((root / 'receipts').glob('*.json'))
assert len(paths) == 1, paths
path = paths[0]
receipt = json.loads(path.read_text(encoding='utf-8'))
assert hashlib.sha256(path.read_bytes().rstrip(b'\n')).hexdigest() == path.stem
assert receipt['holdout_scored'] is False and receipt['adoption_eligible'] is False
for name, digest in receipt['source_sha256'].items():
    assert _file_sha256(Path('src/stock_ai/ml') / name) == digest
baseline_path = Path('artifacts/daily-risk-baselines/receipts/76c4e566403571331f71b89c15d92475d82e94c82b78a1231be44166d356861d.json')
baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
summaries = []
for result in receipt['results']:
    oof_path = Path(result['oof_path'])
    assert _file_sha256(oof_path) == result['oof_byte_sha256']
    oof = pd.read_parquet(oof_path)
    prior = next(r for r in baseline['results'] if r['horizon'] == result['horizon'])
    assert _file_sha256(Path(prior['oof_path'])) == prior['oof_byte_sha256']
    original = pd.read_parquet(prior['oof_path'])
    matched = original.merge(oof[['trading_date', 'symbol']], on=['trading_date', 'symbol'], validate='one_to_one')
    matched = matched.sort_values(['trading_date', 'symbol']).reset_index(drop=True)
    assert _canonical(matched).equals(_canonical(oof))
    differences = {}
    for old, new in [('equal_weight_candidate_mean', 'uniform_return'),
                     ('equal_weight_large_loss', 'uniform_probability'),
                     ('equal_weight_quantile', 'uniform_quantile')]:
        difference = float(np.max(abs(matched[old] - oof[new])))
        assert difference <= 1e-14
        differences[new] = difference
    for fold in result['folds']:
        assert pd.Timestamp(fold['fit']['latest_label_available_at']) < pd.Timestamp(fold['weight_fit_cutoff'])
        assert pd.Timestamp(fold['calibration']['latest_label_available_at']) < pd.Timestamp(fold['calibration_cutoff'])
        assert fold['fit']['latest_label_end'] < fold['calibration']['start']
        assert fold['calibration']['latest_label_end'] < fold['evaluation']['start']
        for model in fold['models'].values():
            assert model['converged'] and model['normalized_dual_gap'] <= 2e-6
            assert min(model['weights']) >= 0 and abs(sum(model['weights']) - 1) < 1e-12
        part = oof.loc[oof.meta_fold == fold['meta_fold']]
        for task, weight, column in [('regression', 'return', 'weighted_return'),
                                     ('large_loss', 'probability', 'weighted_probability')]:
            matrix = part[[f'{task}__{name}' for name in result['candidate_order']]].to_numpy()
            np.testing.assert_allclose(matrix @ fold['models'][weight]['weights'], part[column], atol=1e-14)
        model = fold['calibration_model']
        np.testing.assert_allclose(np.interp(part.weighted_probability, model['isotonic']['x'], model['isotonic']['y']), part.calibrated_probability, atol=1e-14)
    variants = {}
    for name in ('uniform_return', 'weighted_return', 'rank_calibrated_return'):
        variants[name] = result['scores']['regression'][name]['metrics']
    for name in ('uniform_rank', 'weighted_rank'):
        variants[name] = result['scores']['ranking'][name]['metrics']
    for name in ('uniform_probability', 'weighted_probability', 'calibrated_probability'):
        variants[name] = result['scores']['large_loss'][name]
    for name in ('uniform_quantile', 'calibrated_quantile'):
        variants[name] = result['scores']['quantile'][name]
    baseline_scores = {name: _scores(matched.rename(columns={name: 'prediction'})) for name in BASELINES}
    for name in ('training_loss_rate', 'logistic_v0'):
        baseline_scores[name] = asdict(evaluate_probabilities(
            (matched.target <= result['large_loss_threshold']).astype(float).tolist(), matched[name].tolist()))
    baseline_scores['training_quantile'] = asdict(evaluate_quantiles(
        matched.target.tolist(), [result['quantile_alpha']], matched.training_quantile.to_numpy().reshape(-1, 1).tolist()))
    summaries.append({
        'horizon': result['horizon'], 'rows': len(oof), 'dates': int(oof.trading_date.nunique()),
        'start': str(oof.trading_date.min().date()), 'end': str(oof.trading_date.max().date()),
        'burn_in_rows': result['burn_in_rows'], 'variants': variants,
        'uncertainty': result['scores']['uncertainty'],
        'same_cohort_baselines': baseline_scores,
        'prior_baseline_exact_keys': True, 'prior_uniform_max_abs_difference': differences,
        'folds': [{k: v for k, v in f.items() if k != 'scores'} for f in result['folds']],
        'oof_path': str(oof_path), 'oof_byte_sha256': result['oof_byte_sha256'],
    })
output = {
    'source_commit': 'afa9a5fa4212ec7290d7e22f9e808d2fd0e808b9',
    'receipt_path': str(path), 'receipt_byte_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    'verification_source_sha256': _file_sha256(Path(__file__)),
    'prior_baseline_receipt': str(baseline_path),
    'research_only': True, 'holdout_scored': False, 'adoption_eligible': False,
    'results': summaries, 'limitations': receipt['limitations'],
}
evidence = Path('docs/evidence/daily-ensemble-20261015')
evidence.mkdir(parents=True, exist_ok=True)
(evidence / '.gitattributes').write_text('*.json -text\n', encoding='utf-8')
summary_text = json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
summary_path = evidence / 'summary.json'
if summary_path.exists():
    assert summary_path.read_text(encoding='utf-8') == summary_text, 'existing evidence differs'
else:
    summary_path.write_text(summary_text, encoding='utf-8')
print(json.dumps({'receipt': str(path), 'results': [{
    'horizon': r['horizon'], 'rows': r['rows'], 'dates': r['dates'], 'start': r['start'], 'end': r['end'],
    'return_mse': {n: r['variants'][n]['mean_squared_error'] for n in ('uniform_return', 'weighted_return', 'rank_calibrated_return')},
    'rank_ic': {n: r['variants'][n]['mean_daily_rank_ic'] for n in ('uniform_rank', 'weighted_rank')},
    'probability': {n: {k: r['variants'][n][k] for k in ('brier_score', 'log_loss', 'expected_calibration_error')} for n in ('uniform_probability', 'weighted_probability', 'calibrated_probability')},
    'quantile': {n: r['variants'][n]['scores'] for n in ('uniform_quantile', 'calibrated_quantile')},
    'uncertainty': r['uncertainty'], 'baseline_uniform_parity': r['prior_uniform_max_abs_difference'],
    'baseline_mse': {n: r['same_cohort_baselines'][n]['mse'] for n in BASELINES},
} for r in summaries]}, indent=2))

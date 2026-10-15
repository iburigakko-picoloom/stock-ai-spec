import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from stock_ai.ml.research_metrics import within_date_rank_standardize

receipt_path = Path('artifacts/daily-ensemble/receipts/6495e0f60c41d57db025c00fe366dd21f2da24e0142402c99b5e7d4ee76f9c4d.json')
receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
results = []
for result in receipt['results']:
    frame = pd.read_parquet(result['oof_path'])
    errors = []
    for fold in result['folds']:
        part = frame.loc[frame.meta_fold == fold['meta_fold']]
        rank_matrix = np.column_stack([within_date_rank_standardize(part[name], part.trading_date)
                                       for name in result['rank_component_order']])
        reconstructed = rank_matrix @ fold['models']['rank']['weights']
        np.testing.assert_allclose(reconstructed, part.weighted_rank, atol=1e-14)
        np.testing.assert_allclose(rank_matrix.mean(axis=1), part.uniform_rank, atol=1e-14)
        calibration = fold['calibration_model']
        mapping = calibration['rank_to_return']
        np.testing.assert_allclose(mapping['intercept'] + mapping['slope'] * reconstructed,
                                   part.rank_calibrated_return, atol=1e-14)
        np.testing.assert_allclose(part.uniform_quantile + calibration['quantile_offset'],
                                   part.calibrated_quantile, atol=1e-14)
        np.testing.assert_allclose(part.return_residual_rmse, calibration['return_residual']['rmse'])
        for q in ('80', '90'):
            np.testing.assert_allclose(part[f'return_absolute_q{q}'], calibration['return_residual'][f'absolute_q{q}'])
        errors.append(float(np.max(abs(reconstructed - part.weighted_rank))))
    results.append({'horizon': result['horizon'], 'folds': len(errors), 'rank_max_absolute_error': max(errors),
                    'rank_return_quantile_uncertainty_replay': 'PASS'})
output = {'source_commit': 'afa9a5fa4212ec7290d7e22f9e808d2fd0e808b9',
          'receipt_path': str(receipt_path), 'results': results,
          'verification_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
path = Path('docs/evidence/daily-ensemble-20261015/replay.json')
text = json.dumps(output, indent=2) + '\n'
if path.exists():
    assert path.read_text(encoding='utf-8') == text
else:
    path.write_text(text, encoding='utf-8')
print(text)

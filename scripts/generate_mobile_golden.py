"""Synthetic PC-reference vectors only; never package these in the APK."""
from __future__ import annotations

import json
from pathlib import Path

from stock_ai.features import FeatureEngine, V2_EXTENDED_MANIFEST
from stock_ai.fixtures import market_fixture

root = Path(__file__).resolve().parents[1]
daily, market, sector, financials = market_fixture(270)
selection = json.loads(next((root / 'artifacts/selections/goal3-features').glob('*/*.json')).read_text())['feature_selection']
as_of = daily.available_at.max()
result = FeatureEngine(V2_EXTENDED_MANIFEST).latest_snapshot(daily, market, sector, financials=financials, as_of=as_of)
inputs = {name: json.loads(frame.to_json(orient='records', date_format='iso'))
          for name, frame in [('daily', daily), ('market', market), ('sector', sector), ('financials', financials)]}
inputs['as_of'] = as_of.isoformat()
expected = {str(item['horizon']): json.loads(result[['symbol', 'available_at', *item['feature_names']]].to_json(orient='records', date_format='iso'))
            for item in selection['horizons']}
destination = root / '.demo-artifacts/android/mobile-golden.json'
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps({'inputs': inputs, 'expected': expected}, ensure_ascii=False, allow_nan=False), encoding='utf-8')
print(json.dumps({'synthetic_only': True, 'feature_columns': [41, 51], 'symbols': len(result), 'output': str(destination)}))

"""The PC FeatureEngine, with the exact frozen 41/51 column selections."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from stock_ai.features import FeatureEngine, V2_EXTENDED_MANIFEST


def calculate(payload: dict, selection: dict) -> dict:
    frames = {}
    for name in ('daily', 'market', 'sector', 'financials'):
        frame = pd.DataFrame.from_records(payload[name])
        for column in ('available_at',):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column], utc=True)
        if 'trading_date' in frame:
            frame['trading_date'] = pd.to_datetime(frame['trading_date'])
        frames[name] = frame
    result = FeatureEngine(V2_EXTENDED_MANIFEST).latest_snapshot(
        frames['daily'], frames['market'], frames['sector'], financials=frames['financials'],
        as_of=datetime.fromisoformat(payload['as_of']))
    output = {}
    for horizon in selection['horizons']:
        days, names = horizon['horizon'], horizon['feature_names']
        if (days, len(names)) not in ((5, 41), (20, 51)):
            raise ValueError('Unexpected frozen feature selection')
        output[str(days)] = json.loads(result[['symbol', 'available_at', *names]].to_json(orient='records', date_format='iso'))
    return {'as_of': payload['as_of'], 'features': output, 'research_only': True}


def bundled_selection() -> dict:
    return json.loads(Path('/stockai-code/feature-selection.json').read_text())

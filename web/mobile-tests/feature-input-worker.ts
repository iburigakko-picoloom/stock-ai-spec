/// <reference lib="webworker" />
// Synthetic initial-download parity only. Excluded from the APK entry points.
self.onmessage = async (event: MessageEvent<Record<string, unknown>>) => {
  try {
    const url = new URL("/python/pyodide.mjs", self.location.origin).href;
    const { loadPyodide } = await import(/* @vite-ignore */ url);
    const python = await loadPyodide({ indexURL: "/python/" });
    await python.loadPackage(["numpy", "pandas", "pydantic", "sqlite3", "tzdata", "fastapi", "httpx"]);
    python.unpackArchive(new Uint8Array(await (await fetch("/python/stock_ai.zip")).arrayBuffer()), "zip", { extractDir: "/stockai-code" });
    python.globals.set("fixture_json", JSON.stringify(event.data));
    const output = JSON.parse(String(await python.runPythonAsync(`
import sys, json, hashlib
from datetime import datetime
import pandas as pd
sys.path.insert(0, '/stockai-code')
from stock_ai.mobile import runtime, market, features, models
from stock_ai.data.contracts import DatasetName
fixture = json.loads(fixture_json)
assert fixture['synthetic_only'] is True
runtime.initialize(fixture['state'])
path = runtime.STATE / 'mobile.sqlite3'
before = hashlib.sha256(path.read_bytes()).hexdigest()
cutoff = datetime.fromisoformat(fixture['cutoff'])
records = market.feature_inputs(path, cutoff)
frames = market.feature_inputs(path, cutoff, True)
legacy_ids = []
keys = {'security_master':['effective_date','provider_code'],
        'daily_prices':['trading_date','provider_code'], 'trading_calendar':['trading_date'],
        'topix':['trading_date'], 'financial_summary':['disclosure_number']}
for name, _ in records['source_snapshot_ids']:
    source = market.SQLiteSource(path).point_in_time(DatasetName(name), cutoff)
    canonical = source.sort_values(keys[name]).reset_index(drop=True)
    schema = tuple((str(column), str(dtype)) for column, dtype in canonical.dtypes.items())
    metadata = json.dumps({'dataset':name, 'schema':schema}, sort_keys=True).encode()
    rows = pd.util.hash_pandas_object(canonical, index=False).to_numpy().tobytes()
    legacy_ids.append((name, hashlib.sha256(metadata + rows).hexdigest()))
assert legacy_ids == records['source_snapshot_ids']
source = market.SQLiteSource(path).point_in_time(DatasetName.DAILY_PRICES, cutoff)
closed = source.loc[
    source.provider_code.astype(str).str.fullmatch(r'[0-9A-Z]{4}0')
    & (pd.to_datetime(source.trading_date).dt.date < cutoff.date())]
latest_day = pd.to_datetime(closed.trading_date).max()
expected_prices = closed.loc[pd.to_datetime(closed.trading_date) == latest_day].reset_index(drop=True)
latest_prices = market.SQLiteSource(path).latest_closed_prices(cutoff)
pd.testing.assert_frame_equal(latest_prices, expected_prices, check_exact=True)
for field in ('as_of', 'latest_source_received_at', 'source_snapshot_ids', 'revision_policy'):
    assert records[field] == frames[field]
for field in ('daily', 'market', 'sector', 'financials'):
    pd.testing.assert_frame_equal(features._json_records_frame(frames[field]),
                                  features.model_input_frame(field, pd.DataFrame.from_records(records[field])),
                                  check_exact=True)
legacy = features.calculate(records, fixture['selection'])
result = features.calculate(frames, fixture['selection'])
assert result == legacy
assert hashlib.sha256(path.read_bytes()).hexdigest() == before
assert len(frames['daily']) == fixture['daily_rows']
runtime.initialize(runtime.export_state())
restored = market.feature_inputs(path, cutoff, True)
assert features.calculate(restored, fixture['selection']) == result
assert restored['source_snapshot_ids'] == records['source_snapshot_ids']
assert models.status(path, runtime._app.state.store)['imported_bundle_count'] == 0
json.dumps({'result':result, 'source_ids':records['source_snapshot_ids'],
            'daily_rows':len(frames['daily']), 'records_exact':True,
            'source_unchanged':True, 'restored_exact':True, 'model_count':0,
            'legacy_source_ids_exact':True, 'na_hash':hash(pd.NA),
            'latest_closed_price_rows':len(latest_prices)})
`)));
    self.postMessage(output);
  } catch (error) { self.postMessage({ error: String(error) }); }
};

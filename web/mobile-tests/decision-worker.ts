/// <reference lib="webworker" />
// Synthetic persistence/parity harness. Excluded from the app entry and APK.
self.onmessage = async (event: MessageEvent<Record<string, unknown>>) => {
  try {
    const url = new URL("/python/pyodide.mjs", self.location.origin).href;
    const { loadPyodide } = await import(/* @vite-ignore */ url);
    const python = await loadPyodide({ indexURL: "/python/" });
    await python.loadPackage(["numpy", "pandas", "pydantic", "sqlite3", "tzdata", "fastapi", "httpx"]);
    python.unpackArchive(new Uint8Array(await (await fetch("/python/stock_ai.zip")).arrayBuffer()), "zip", { extractDir: "/stockai-code" });
    python.globals.set("fixture_json", JSON.stringify(event.data));
    const result = JSON.parse(String(await python.runPythonAsync(`
import sys, json, io, zlib
from collections import OrderedDict
import pandas as pd
sys.path.insert(0, '/stockai-code')
from datetime import datetime, timedelta
from stock_ai.mobile import runtime, models, forecasts, decisions, market, market_codec
from stock_ai.mobile.storage import connect
from stock_ai.data.contracts import DatasetName
fixture = json.loads(fixture_json)
assert fixture['synthetic_only'] is True
# Only this test entry accepts synthetic approvals; production policy stays empty.
models.policy = lambda: fixture['policy']
models.bundled_selection = lambda: fixture['selection']
forecasts.bundled_selection = lambda: fixture['selection']
runtime.initialize(fixture['state'])
path, store = runtime.STATE / 'mobile.sqlite3', runtime._app.state.store
ledger, snapshot = store.latest_portfolio(), store.latest_prediction_snapshot()
now = datetime.fromisoformat(fixture['now'])
# Exercise the actual bundled Pandas parser and both storage representations.
# No schema, data hash, observation sequence or receipt is allowed to change.
identity_query = 'SELECT sequence,dataset,day,received_at,payload_hash,normalized_hash FROM market_batches ORDER BY sequence'
with connect(path) as db:
    identities = db.execute(identity_query).fetchall()
    rows = db.execute('SELECT sequence,raw,normalized,normalized_hash FROM market_batches').fetchall()
    for sequence, raw, compact, digest in rows:
        original = market_codec.table(db, compact, raw, digest)
        pd.testing.assert_frame_equal(
            market_codec.frame(db, compact, raw, digest, OrderedDict()),
            pd.read_json(io.BytesIO(original), orient='table'), check_exact=True)
        legacy_raw = zlib.compress(json.dumps(market_codec.records(db, raw), allow_nan=False).encode())
        db.execute('UPDATE market_batches SET raw=?,normalized=? WHERE sequence=?',
                   (legacy_raw, zlib.compress(original), sequence))
reader = market.SQLiteSource(path)
legacy_frames = {kind: reader.point_in_time(kind, now) for kind in DatasetName}
assert market.compact_legacy(path, 1) == 1
for kind in DatasetName:
    pd.testing.assert_frame_equal(reader.point_in_time(kind, now), legacy_frames[kind], check_exact=True)
while market.compact_legacy(path):
    pass
with connect(path) as db:
    assert db.execute(identity_query).fetchall() == identities
first = decisions.generate(path, store, now)
today = await runtime.request('GET', '/api/v1/today?businessDate=' + now.date().isoformat(), 'null')
assert ledger == store.latest_portfolio() and snapshot == store.latest_prediction_snapshot()
runtime.initialize(runtime.export_state())
for kind in DatasetName:
    pd.testing.assert_frame_equal(reader.point_in_time(kind, now), legacy_frames[kind], check_exact=True)
with connect(path) as db:
    assert db.execute(identity_query).fetchall() == identities
restored = decisions.generate(path, runtime._app.state.store, now + timedelta(minutes=1))
assert first == restored
json.dumps({'result': first, 'today': today, 'restored': restored,
            'market_parity': {'batches': len(rows), 'datasets': len(legacy_frames),
                              'exact_values_types_receipts_after_migration_and_restore': True},
            'active': decisions.view(path, runtime._app.state.store)['is_active']})
`)));
    self.postMessage(result);
  } catch (error) { self.postMessage({ error: String(error) }); }
};

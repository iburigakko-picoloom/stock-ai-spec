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
import sys, json
sys.path.insert(0, '/stockai-code')
from datetime import datetime, timedelta
from stock_ai.mobile import runtime, models, forecasts, decisions
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
first = decisions.generate(path, store, now)
today = await runtime.request('GET', '/api/v1/today?businessDate=' + now.date().isoformat(), 'null')
assert ledger == store.latest_portfolio() and snapshot == store.latest_prediction_snapshot()
runtime.initialize(runtime.export_state())
restored = decisions.generate(path, runtime._app.state.store, now + timedelta(minutes=1))
assert first == restored
json.dumps({'result': first, 'today': today, 'restored': restored,
            'active': decisions.view(path, runtime._app.state.store)['is_active']})
`)));
    self.postMessage(result);
  } catch (error) { self.postMessage({ error: String(error) }); }
};

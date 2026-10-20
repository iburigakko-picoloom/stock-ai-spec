/// <reference lib="webworker" />
// Synthetic browser acceptance only. No test policy/clock is shipped in the APK.
let python: {
  runPythonAsync(code: string): Promise<unknown>;
  globals: { set(name: string, value: unknown): void };
} | null = null;
let queue = Promise.resolve();

self.onmessage = (event: MessageEvent<{ id: number; command: string; fixture?: unknown; state?: string; method?: string; path?: string; body?: string; minutes?: number }>) => {
  queue = queue.then(async () => {
    const input = event.data;
    try {
      if (input.command === "initialize") {
        const url = new URL("/python/pyodide.mjs", self.location.origin).href;
        const { loadPyodide } = await import(/* @vite-ignore */ url);
        const runtime = await loadPyodide({ indexURL: "/python/" });
        await runtime.loadPackage(["numpy", "pandas", "pydantic", "sqlite3", "tzdata", "fastapi", "httpx"]);
        runtime.unpackArchive(new Uint8Array(await (await fetch("/python/stock_ai.zip")).arrayBuffer()), "zip", { extractDir: "/stockai-code" });
        python = runtime;
        if (!python) throw new Error("Synthetic interpreter unavailable");
        python.globals.set("fixture_json", JSON.stringify(input.fixture));
        python.globals.set("saved_state", input.state ?? "");
        await python.runPythonAsync(`
import sys, json
sys.path.insert(0, '/stockai-code')
from datetime import datetime, timedelta
from stock_ai.mobile import runtime, models, forecasts, decisions
fixture = json.loads(fixture_json)
assert fixture['synthetic_only'] is True
models.policy = lambda: fixture['policy']
models.bundled_selection = lambda: fixture['selection']
forecasts.bundled_selection = lambda: fixture['selection']
runtime.initialize(saved_state or fixture['state'])
now = datetime.fromisoformat(fixture['now'])
class FixtureClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return now if tz is None else now.astimezone(tz)
runtime.datetime = FixtureClock
path, store = runtime.STATE / 'mobile.sqlite3', runtime._app.state.store
ledger_before = store.latest_portfolio().model_dump_json()
forecast_before = store.latest_prediction_snapshot().model_dump_json()
if not saved_state:
    decisions.generate(path, store, now)
`);
        self.postMessage({ id: input.id });
        return;
      }
      if (!python) throw new Error("Synthetic interpreter not initialized");
      if (input.command === "advance") {
        python.globals.set("minutes", input.minutes);
        await python.runPythonAsync("now += timedelta(minutes=minutes)");
        self.postMessage({ id: input.id });
        return;
      }
      python.globals.set("method", input.method);
      python.globals.set("request_path", input.path);
      python.globals.set("body", input.body);
      const reply = JSON.parse(String(await python.runPythonAsync(`
reply = await runtime.request(method, request_path, body)
assert store.latest_portfolio().model_dump_json() == ledger_before
assert store.latest_prediction_snapshot().model_dump_json() == forecast_before
store.verify_integrity()
json.dumps({'reply': reply, 'state': runtime.export_state() if method == 'POST' and reply['status'] < 400 else None})
`)));
      self.postMessage({ id: input.id, ...reply });
    } catch (error) { self.postMessage({ id: input.id, error: String(error) }); }
  });
};

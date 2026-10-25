import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join, delimiter } from "node:path";
import { test, expect } from "@playwright/test";

test("offline WASM resumes a killed calculation from saved exact feature batches", async ({ page, context }) => {
  const root = fileURLToPath(new URL("../../", import.meta.url));
  const fixture = JSON.parse(execFileSync(join(root, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python"), ["-c", `
import json
from datetime import timedelta
from mobile.python import checkpoints, features
from stock_ai.fixtures import market_fixture
from tests.test_mobile_features import frozen_selection
frames = market_fixture(270)
daily = frames[0]
symbol = sorted(daily.symbol.unique())[0]
frames = (daily.loc[~((daily.symbol == symbol) & (daily.trading_date == daily.trading_date.min()))].copy(), *frames[1:])
payload = dict(zip(('daily', 'market', 'sector', 'financials'), frames, strict=True))
payload['as_of'] = (daily.available_at.max() + timedelta(minutes=1)).isoformat()
selection = frozen_selection()
print(json.dumps({'synthetic_only': True, 'as_of': payload['as_of'], 'inputs': checkpoints.encode(payload), 'selection': selection, 'expected': features.calculate(payload, selection)}))
`], { cwd: root, encoding: "utf-8", maxBuffer: 8 * 1024 * 1024, env: { ...process.env, PYTHONPATH: [root, join(root, "src")].join(delimiter) } }));
  expect(fixture.synthetic_only).toBe(true);
  await context.route("https://**", route => route.abort());
  await page.route("**/checkpoint-test", route => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Checkpoint fixture</title>" }));
  await page.goto("/checkpoint-test");
  const actual = await page.evaluate(async fixture => {
    const source = `self.onmessage = async event => {
      try {
        const { loadPyodide } = await import(${JSON.stringify(location.origin + "/python/pyodide.mjs")});
        const py = await loadPyodide({ indexURL: ${JSON.stringify(location.origin + "/python/")} });
        await py.loadPackage(["numpy", "pandas", "pydantic", "sqlite3", "tzdata", "fastapi", "httpx"]);
        py.unpackArchive(new Uint8Array(await (await fetch(${JSON.stringify(location.origin + "/python/stock_ai.zip")})).arrayBuffer()), "zip", { extractDir: "/stockai-code" });
        py.globals.set("fixture_json", JSON.stringify(event.data));
        py.globals.set("send_checkpoint", value => self.postMessage({ checkpoint: JSON.parse(value) }));
        const result = await py.runPythonAsync("import sys, json\\nsys.path.insert(0, '/stockai-code')\\nfrom stock_ai.mobile import checkpoints, features\\nf = json.loads(fixture_json)\\ncheckpoints.configure(f['context'], send_checkpoint)\\ncheckpoints.plan(10)\\npayload = checkpoints.cached('inputs', lambda: None, units=1)\\nresult = features.calculate(payload, f['selection'])\\njson.dumps(result)");
        self.postMessage({ result: JSON.parse(result) });
      } catch(error) { self.postMessage({ error: String(error) }); }
    };`;
    const url = URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
    const records: Record<string, string> = { inputs: fixture.inputs };
    let reused = 0;
    async function run(interrupt: boolean) {
      const worker = new Worker(url, { type: "module" });
      try {
        return await new Promise<unknown>((resolve, reject) => {
          worker.onerror = error => reject(new Error(error.message));
          worker.onmessage = event => {
            if (event.data.error) { reject(new Error(event.data.error)); return; }
            const value = event.data.checkpoint;
            if (value) {
              if (value.data !== null) records[value.key] = value.data;
              else if (value.key.startsWith("features-")) reused++;
              if (interrupt && value.key.startsWith("features-")) { worker.terminate(); resolve(null); }
              return;
            }
            resolve(event.data.result);
          };
          worker.postMessage({ context: { records, startedAt: fixture.as_of }, selection: fixture.selection });
        });
      } finally { worker.terminate(); }
    }
    try {
      await run(true);
      const saved = Object.keys(records).filter(key => key.startsWith("features-")).length;
      const result = await run(false);
      return { saved, reused, result };
    } finally { URL.revokeObjectURL(url); }
  }, fixture);
  expect(actual.saved).toBeGreaterThan(0);
  expect(actual.reused).toBeGreaterThan(0);
  expect(actual.result).toEqual(fixture.expected);
});

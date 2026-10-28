// Exercise the APK's pinned WASM/SQLite packages without a browser or user data.
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
// Pyodide's Node loader needs its .js glue to be CommonJS; web/ is ESM.
// Isolate packaging for this Node check without changing any pinned asset.
const directory = mkdtempSync(join(tmpdir(), "stockai-ui-wasm-"));
async function main() {
  cpSync(new URL("../web/public/python/", import.meta.url), directory, { recursive: true });
  writeFileSync(join(directory, "package.json"), '{"type":"commonjs"}');
  const assets = pathToFileURL(directory + "/");
  const { loadPyodide } = await import(new URL("pyodide.mjs", assets).href);
  const python = await loadPyodide({ indexURL: fileURLToPath(assets) });
  await python.loadPackage(["numpy", "pandas", "pydantic", "sqlite3", "tzdata", "fastapi", "httpx"]);
  python.unpackArchive(new Uint8Array(readFileSync(new URL("stock_ai.zip", assets))), "zip", { extractDir: "/stockai-code" });
  const result = await python.runPythonAsync(`
import sys, json
from contextlib import closing
sys.path.insert(0, '/stockai-code')
from stock_ai.mobile import runtime
runtime.initialize()
store = runtime._app.state.store
original = store.verify_integrity
calls = 0
def counted():
    global calls
    calls += 1
    return original()
store.verify_integrity = counted
for _ in range(4):
    response = await runtime.request('GET', '/api/v1/health')
    assert response['status'] == 200, response
assert calls == 1, calls
body = {'schema_version': 'manual-portfolio-v1', 'holdings_status': 'none',
        'investment_budget_yen': '10000', 'maximum_drawdown_percent': None,
        'accounts': [], 'holdings': []}
saved = await runtime.request('POST', '/api/v1/mobile/portfolio', json.dumps(body))
assert saved['status'] == 200, saved
assert (await runtime.request('GET', '/api/v1/health'))['status'] == 200
assert calls == 2, calls
assert (await runtime.request('GET', '/api/v1/execution-context'))['body']['decision'] is None
export = runtime.StateExport(operations_only=True)
pieces = []
while (piece := export.read_next()) is not None: pieces.append(piece)
import sqlite3
with closing(sqlite3.connect(runtime.STATE / 'operations.sqlite3')) as db:
    db.execute("UPDATE manual_portfolio_imports SET content_hash='corrupt'")
    db.commit()
assert (await runtime.request('GET', '/api/v1/health'))['status'] == 503
stream = runtime.StateImport(sum(map(len, pieces)))
for index, piece in enumerate(pieces): stream.append(index, piece)
stream.finish(initialize_runtime=False, operations_only=True)
stream.close()
runtime.initialize()
assert (await runtime.request('GET', '/api/v1/mobile/portfolio'))['body'] == saved['body']
assert (await runtime.request('GET', '/api/v1/health'))['status'] == 200
json.dumps({'status': 'passed', 'runtime': 'pinned Pyodide WASM32 under Node',
            'checks': ['unchanged proof reuse', 'write invalidation', 'execution context',
                       'corruption rejection', 'operations overlay restoration'],
            'android_native_test': False})
`);
  console.log(result);
}
try { await main(); } finally {
  rmSync(directory, { recursive: true, force: true });
}

/// <reference lib="webworker" />
// The entire interpreter, wheels and source archive are local APK assets.
let python: {
  loadPackage(names: string[]): Promise<void>;
  FS: { mkdirTree(path: string): void; writeFile(path: string, value: Uint8Array): void };
  unpackArchive(data: Uint8Array, format: string, options: { extractDir: string }): void;
  runPythonAsync(code: string): Promise<unknown>;
  globals: { set(key: string, value: unknown): void };
} | null = null;
let stage = "interpreter";

async function initialize(state: string): Promise<void> {
  stage = "interpreter";
  // Vite must leave the offline interpreter module URL unchanged.
  const url = new URL("/python/pyodide.mjs", self.location.origin).href;
  const { loadPyodide } = await import(/* @vite-ignore */ url);
  python = await loadPyodide({ indexURL: "/python/" });
  if (!python) throw new Error("Python initialization failed");
  stage = "packages";
  await python.loadPackage(["numpy", "pandas", "pydantic", "sqlite3", "tzdata", "fastapi", "httpx"]);
  stage = "archive";
  const archive = new Uint8Array(await (await fetch("/python/stock_ai.zip")).arrayBuffer());
  python.unpackArchive(archive, "zip", { extractDir: "/stockai-code" });
  python.globals.set("saved_state", state);
  const build = await (await fetch("/python/build-info.json")).json();
  python.globals.set("source_commit", build.source_commit);
  stage = "state";
  try {
    await python.runPythonAsync("import sys, os\nsys.path.insert(0, '/stockai-code')\nos.environ['STOCK_AI_CODE_COMMIT'] = source_commit\nfrom stock_ai.mobile import runtime\nruntime.initialize(saved_state)");
  } finally { python.globals.set("saved_state", null); }
}

// Serialize every operation, including startup, so no update can overtake an
// uncommitted portfolio/ledger write.
let queue = Promise.resolve();
self.onmessage = (event: MessageEvent<{ id: number; command: string; state?: string; method?: string; path?: string; body?: string }>) => {
  const input = event.data;
  queue = queue.then(async () => {
    try {
      if (input.command === "initialize") {
        try { await initialize(input.state || ""); }
        finally { delete input.state; }
      }
      if (!python) throw new Error("端末内の計算環境が未起動です。");
      let result: unknown = null;
      if (input.command === "request") {
        stage = "request";
        python.globals.set("method", input.method);
        python.globals.set("request_path", input.path);
        python.globals.set("request_body", input.body || "null");
        try {
          result = JSON.parse(String(await python.runPythonAsync("import json\njson.dumps(await runtime.request(method, request_path, request_body), ensure_ascii=False)")));
        } finally { python.globals.set("request_body", null); delete input.body; }
      }
      const state = input.command === "initialize" || input.method === "POST"
        ? String(await python.runPythonAsync("runtime.export_state()")) : null;
      self.postMessage({ id: input.id, result, state });
    } catch (error) {
      const kind = error instanceof WebAssembly.CompileError || error instanceof WebAssembly.LinkError || error instanceof WebAssembly.RuntimeError ? "wasm" : error instanceof TypeError ? "type" : error instanceof Error && error.name === "PythonError" ? "python" : "other";
      self.postMessage({ id: input.id, error_code: `${stage}_${kind}`, error: import.meta.env.DEV ? String(error) : "端末内の処理に失敗しました。保存済みデータを確認し、再起動してください。" });
    }
  });
};

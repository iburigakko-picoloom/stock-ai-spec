/// <reference lib="webworker" />
// The entire interpreter, wheels and source archive are local APK assets.
let python: {
  loadPackage(names: string[]): Promise<void>;
  FS: { mkdirTree(path: string): void; writeFile(path: string, value: Uint8Array): void };
  unpackArchive(data: Uint8Array, format: string, options: { extractDir: string }): void;
  runPythonAsync(code: string): Promise<unknown>;
  globals: { set(key: string, value: unknown): void };
} | null = null;

async function initialize(state: string): Promise<void> {
  // Vite must leave the offline interpreter module URL unchanged.
  const url = new URL("/python/pyodide.mjs", self.location.origin).href;
  const { loadPyodide } = await import(/* @vite-ignore */ url);
  python = await loadPyodide({ indexURL: "/python/" });
  if (!python) throw new Error("Python initialization failed");
  await python.loadPackage(["numpy", "pandas", "pydantic", "sqlite3", "tzdata", "fastapi", "httpx"]);
  const archive = new Uint8Array(await (await fetch("/python/stock_ai.zip")).arrayBuffer());
  python.unpackArchive(archive, "zip", { extractDir: "/stockai-code" });
  python.globals.set("saved_state", state);
  await python.runPythonAsync("import sys, os\nsys.path.insert(0, '/stockai-code')\nos.environ['STOCK_AI_CODE_COMMIT'] = 'apk-shared-source'\nfrom stock_ai.mobile import runtime\nruntime.initialize(saved_state)");
}

// Serialize every operation, including startup, so no update can overtake an
// uncommitted portfolio/ledger write.
let queue = Promise.resolve();
self.onmessage = (event: MessageEvent<{ id: number; command: string; state?: string; method?: string; path?: string; body?: string }>) => {
  const input = event.data;
  queue = queue.then(async () => {
    try {
      if (input.command === "initialize") await initialize(input.state || "");
      if (!python) throw new Error("端末内の計算環境が未起動です。");
      let result: unknown = null;
      if (input.command === "request") {
        python.globals.set("method", input.method);
        python.globals.set("request_path", input.path);
        python.globals.set("request_body", input.body || "null");
        result = JSON.parse(String(await python.runPythonAsync("import json\njson.dumps(await runtime.request(method, request_path, request_body), ensure_ascii=False)")));
      }
      const state = input.command === "initialize" || input.method === "POST"
        ? String(await python.runPythonAsync("runtime.export_state()")) : null;
      self.postMessage({ id: input.id, result, state });
    } catch (error) {
      self.postMessage({ id: input.id, error: import.meta.env.DEV ? String(error) : "端末内の処理に失敗しました。保存済みデータを確認し、再起動してください。" });
    }
  });
};

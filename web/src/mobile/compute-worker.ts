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

async function initialize(state: string | ArrayBuffer, progress: (phase: string) => void): Promise<void> {
  stage = "interpreter";
  progress(stage);
  // Vite must leave the offline interpreter module URL unchanged.
  const url = new URL("/python/pyodide.mjs", self.location.origin).href;
  const { loadPyodide } = await import(/* @vite-ignore */ url);
  python = await loadPyodide({ indexURL: "/python/" });
  if (!python) throw new Error("Python initialization failed");
  stage = "packages";
  progress(stage);
  await python.loadPackage(["numpy", "pandas", "pydantic", "sqlite3", "tzdata", "fastapi", "httpx"]);
  stage = "archive";
  progress(stage);
  const archive = new Uint8Array(await (await fetch("/python/stock_ai.zip")).arrayBuffer());
  python.unpackArchive(archive, "zip", { extractDir: "/stockai-code" });
  const build = await (await fetch("/python/build-info.json")).json();
  python.globals.set("source_commit", build.source_commit);
  stage = "state";
  progress(stage);
  await python.runPythonAsync("import sys, os\nsys.path.insert(0, '/stockai-code')\nos.environ['STOCK_AI_CODE_COMMIT'] = source_commit\nfrom stock_ai.mobile import runtime");
  if (typeof state === "string") {
    python.globals.set("saved_state", state);
    try { await python.runPythonAsync("runtime.initialize(saved_state)"); }
    finally { python.globals.set("saved_state", null); }
  } else {
    const bytes = new Uint8Array(state);
    python.globals.set("state_length", bytes.length);
    await python.runPythonAsync("_native_import = runtime.StateImport(state_length)");
    try {
      progress("decoding-input");
      const decoder = new TextDecoder("utf-8", { fatal: true });
      for (let offset = 0, index = 0; offset < bytes.length; offset += 256 * 1024, index++) {
        python.globals.set("state_fragment", decoder.decode(bytes.subarray(offset, offset + 256 * 1024)));
        python.globals.set("state_index", index);
        await python.runPythonAsync("_native_import.append(state_index, state_fragment)");
      }
      python.globals.set("state_fragment", null);
      await python.runPythonAsync("_native_import.finish()");
    } finally {
      python.globals.set("state_fragment", null);
      await python.runPythonAsync("_native_import.close()\n_native_import = None");
    }
  }
}

// Serialize every operation, including startup, so no update can overtake an
// uncommitted portfolio/ledger write.
let queue = Promise.resolve();
let awaitingAck: { id: number; index: number; resolve: () => void; reject: (error: Error) => void } | null = null;
function sendState(id: number, index: number, message: Record<string, unknown>): Promise<void> {
  return new Promise((resolve, reject) => {
    awaitingAck = { id, index, resolve, reject };
    self.postMessage({ id, ...message });
  });
}
async function exportNative(id: number, progress: (phase: string) => void): Promise<void> {
  if (!python) throw new Error("Runtime unavailable");
  const interpreter = python;
  await interpreter.runPythonAsync("_native_export = None");
  try {
    progress("export-archive");
    const length = Number(await interpreter.runPythonAsync("_native_export = runtime.StateExport()\n_native_export.length"));
    if (!Number.isSafeInteger(length) || length < 0 || length > 256 * 1024 * 1024) throw new Error("Invalid state length");
    await sendState(id, -1, { state_begin: length });
    progress("export-chunks");
    let received = 0;
    for (let index = 0; ; index++) {
      const fragment = await interpreter.runPythonAsync("_native_export.read_next()");
      if (fragment == null) break;
      if (typeof fragment !== "string" || fragment.length !== Math.min(256 * 1024, length - received) || fragment.length === 0) throw new Error("Invalid state fragment");
      await sendState(id, index, { state_chunk: fragment, index });
      received += fragment.length;
    }
    if (received !== length) throw new Error("Incomplete state");
  } finally {
    awaitingAck = null;
    await interpreter.runPythonAsync("_native_export.close() if _native_export is not None else None\n_native_export = None");
  }
}
self.onmessage = (event: MessageEvent<{ id: number; command: string; index?: number; ok?: boolean; state?: string; state_bytes?: ArrayBuffer; trace?: boolean; stream_state?: boolean; method?: string; path?: string; body?: string }>) => {
  const input = event.data;
  if (input.command === "state_ack") {
    if (awaitingAck?.id === input.id && (input.ok !== true || awaitingAck.index === input.index)) {
      const pending = awaitingAck; awaitingAck = null;
      if (input.ok === true) pending.resolve(); else pending.reject(new Error("State transfer aborted"));
    }
    return;
  }
  queue = queue.then(async () => {
    const progress = (phase: string) => { if (input.trace === true) self.postMessage({ id: input.id, progress: phase }); };
    try {
      if (input.command === "initialize") {
        if (input.state_bytes !== undefined) {
          stage = "state";
          if (!(input.state_bytes instanceof ArrayBuffer) || input.state_bytes.byteLength > 256 * 1024 * 1024 || input.state !== undefined) throw new TypeError("Invalid state transfer");
        }
        try { await initialize(input.state_bytes ?? input.state ?? "", progress); }
        finally { delete input.state; delete input.state_bytes; }
      }
      if (!python) throw new Error("端末内の計算環境が未起動です。");
      let result: unknown = null;
      if (input.command === "request") {
        stage = "request";
        progress(stage);
        python.globals.set("method", input.method);
        python.globals.set("request_path", input.path);
        python.globals.set("request_body", input.body || "null");
        try {
          result = JSON.parse(String(await python.runPythonAsync("import json\njson.dumps(await runtime.request(method, request_path, request_body), ensure_ascii=False)")));
        } finally { python.globals.set("request_body", null); delete input.body; }
      }
      const saves = input.command === "initialize" || input.method === "POST";
      if (saves && input.stream_state === true) {
        await exportNative(input.id, progress);
        self.postMessage({ id: input.id, result, state: true });
      } else {
        if (saves) progress("export");
        const state = saves ? String(await python.runPythonAsync("runtime.export_state()")) : null;
        self.postMessage({ id: input.id, result, state });
      }
    } catch (error) {
      const kind = error instanceof WebAssembly.CompileError || error instanceof WebAssembly.LinkError || error instanceof WebAssembly.RuntimeError ? "wasm" : error instanceof TypeError ? "type" : error instanceof Error && error.name === "PythonError" ? "python" : "other";
      self.postMessage({ id: input.id, error_code: `${stage}_${kind}`, error: import.meta.env.DEV ? String(error) : "端末内の処理に失敗しました。保存済みデータを確認し、再起動してください。" });
    }
  });
};

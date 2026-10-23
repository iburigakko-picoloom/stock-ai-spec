// Only the APK-owned WebView loads this entry; it exposes no provider or account credentials.
interface ComputeBridge {
  ready(): void;
  complete(identity: string, payload: string): void;
  inputChunk(identity: string, index: number): string | null;
  inputDone(identity: string): boolean;
  beginState(identity: string, length: number): boolean;
  stateChunk(identity: string, index: number, fragment: string): boolean;
  progress?(identity: string, phase: string): void;
}
interface ComputeCommand { id: number; command: string; state_length?: number; state?: string; state_bytes?: ArrayBuffer; trace?: boolean; stream_state?: boolean }
interface HostWindow extends Window {
  StockAICompute?: ComputeBridge;
  stockAICompute?: (request: ComputeCommand) => void;
}
const hostWindow = window as HostWindow;
const bridge = hostWindow.StockAICompute;
if (bridge) {
  const worker = new Worker(new URL("./compute-worker.ts", import.meta.url), { type: "module" });
  const chunkCharacters = 256 * 1024;
  const maxCharacters = 256 * 1024 * 1024;
  const yieldTurn = () => new Promise<void>(resolve => setTimeout(resolve, 0));
  let active: number | null = null;
  let completing = false;
  let output: { length: number; received: number; next: number } | null = null;
  const fail = (id: number, code: string) => bridge.complete(String(id), JSON.stringify({ error: "COMPUTE_WORKER_FAILED", code }));
  const release = (id: number) => { if (active === id) { active = null; completing = false; output = null; } };
  worker.onmessage = (event: MessageEvent<{ id: number; progress?: string; result?: unknown; state?: true | null; state_begin?: number; state_chunk?: string; index?: number; error?: string; error_code?: string }>) => {
    const message = event.data;
    if (message.id !== active || completing) return;
    const id = message.id;
    const identity = String(id);
    try {
      if (message.progress) { bridge.progress?.(identity, message.progress); return; }
      if (message.error) { fail(id, message.error_code ?? "unknown"); release(id); return; }
      if (message.state_begin !== undefined) {
        const length = message.state_begin;
        if (output || !Number.isSafeInteger(length) || length < 0 || length > maxCharacters) throw new Error("STATE_TRANSFER_FAILED");
        bridge.progress?.(identity, "staging-output");
        if (!bridge.beginState(identity, length)) throw new Error("STATE_TRANSFER_FAILED");
        output = { length, received: 0, next: 0 };
        worker.postMessage({ command: "state_ack", id, index: -1, ok: true }); return;
      }
      if (message.state_chunk !== undefined) {
        const fragment = message.state_chunk;
        if (!output || typeof fragment !== "string" || message.index !== output.next || fragment.length === 0
            || fragment.length !== Math.min(chunkCharacters, output.length - output.received)
            || /[^A-Za-z0-9+/=]/.test(fragment)
            || !bridge.stateChunk(identity, output.next, fragment)) throw new Error("STATE_TRANSFER_FAILED");
        output.received += fragment.length; output.next++;
        worker.postMessage({ command: "state_ack", id, index: message.index, ok: true }); return;
      }
      if (message.state === true) {
        if (!output || output.received !== output.length) throw new Error("STATE_TRANSFER_FAILED");
      } else if (message.state !== null || output) throw new Error("STATE_TRANSFER_FAILED");
      completing = true;
      bridge.complete(identity, JSON.stringify({ id, result: message.result, state: message.state }));
      release(id);
    } catch {
      worker.postMessage({ command: "state_ack", id, ok: false });
      fail(id, "state_other"); release(id);
    }
  };
  worker.onerror = () => {
    if (active !== null) {
      const id = active; release(id);
      fail(id, "worker_js");
    }
  };
  hostWindow.stockAICompute = async request => {
    if (!Number.isSafeInteger(request.id) || active !== null) return;
    const id = request.id;
    active = id; output = null;
    const input = { ...request };
    const transfer: Transferable[] = [];
    try {
      if (input.command === "initialize" || input.command === "initialize_operations") {
        const length = input.state_length;
        if ("state" in input || "state_bytes" in input || !Number.isSafeInteger(length) || length === undefined || length < 0 || length > maxCharacters) throw new Error("STATE_TRANSFER_FAILED");
        bridge.progress?.(String(id), "reading-input");
        // Capsules are ASCII base64. Transfer one owned byte buffer to the
        // worker instead of retaining/joining/cloning complete host strings.
        const bytes = new Uint8Array(length);
        const encoder = new TextEncoder();
        let received = 0;
        for (let offset = 0, index = 0; offset < length; offset += chunkCharacters, index++) {
          const fragment = bridge.inputChunk(String(id), index);
          if (typeof fragment !== "string" || fragment.length > chunkCharacters || received + fragment.length > length) throw new Error("STATE_TRANSFER_FAILED");
          const encoded = encoder.encodeInto(fragment, bytes.subarray(received, received + fragment.length));
          if (encoded.read !== fragment.length || encoded.written !== fragment.length) throw new Error("STATE_TRANSFER_FAILED");
          received += fragment.length;
          await yieldTurn();
        }
        if (received !== length || !bridge.inputDone(String(id))) throw new Error("STATE_TRANSFER_FAILED");
        input.state_bytes = bytes.buffer; transfer.push(bytes.buffer);
        delete input.state_length;
      }
      input.trace = true; input.stream_state = true;
      bridge.progress?.(String(id), "posting-input");
      worker.postMessage(input, transfer);
    } catch {
      fail(id, "state_other");
      release(id);
    } finally { delete input.state; delete input.state_bytes; }
  };
  bridge.ready();
}
export {};

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
interface ComputeCommand { id: number; command: string; state_length?: number; state?: string; state_bytes?: ArrayBuffer; trace?: boolean; transfer_state?: boolean }
interface HostWindow extends Window {
  StockAICompute?: ComputeBridge;
  stockAICompute?: (request: ComputeCommand) => void;
}
const hostWindow = window as HostWindow;
const bridge = hostWindow.StockAICompute;
if (bridge) {
  const worker = new Worker(new URL("./compute-worker.ts", import.meta.url), { type: "module" });
  const chunkCharacters = 256 * 1024;
  const maxCharacters = 128 * 1024 * 1024;
  const yieldTurn = () => new Promise<void>(resolve => setTimeout(resolve, 0));
  let active: number | null = null;
  let completing = false;
  const fail = (id: number, code: string) => bridge.complete(String(id), JSON.stringify({ error: "COMPUTE_WORKER_FAILED", code }));
  worker.onmessage = async (event: MessageEvent<{ id: number; progress?: string; result?: unknown; state?: string | null; state_bytes?: ArrayBuffer; error?: string; error_code?: string }>) => {
    const message = event.data;
    if (message.id !== active || completing) return;
    if (message.progress) { bridge.progress?.(String(message.id), message.progress); return; }
    const id = message.id;
    const identity = String(id);
    completing = true;
    try {
      if (message.error) { fail(id, message.error_code ?? "unknown"); return; }
      let state: true | null = null;
      if (message.state_bytes !== undefined) {
        if (!(message.state_bytes instanceof ArrayBuffer) || message.state !== undefined) throw new Error("STATE_TRANSFER_FAILED");
        const saved = new Uint8Array(message.state_bytes); delete message.state_bytes;
        bridge.progress?.(identity, "staging-output");
        if (saved.length > maxCharacters || !bridge.beginState(identity, saved.length)) throw new Error("STATE_TRANSFER_FAILED");
        const decoder = new TextDecoder("utf-8", { fatal: true });
        for (let offset = 0, index = 0; offset < saved.length; offset += chunkCharacters, index++) {
          const piece = saved.subarray(offset, offset + chunkCharacters);
          const fragment = decoder.decode(piece);
          if (fragment.length !== piece.length || !bridge.stateChunk(identity, index, fragment)) throw new Error("STATE_TRANSFER_FAILED");
          await yieldTurn();
        }
        state = true;
      } else if (message.state !== null) throw new Error("STATE_TRANSFER_FAILED");
      bridge.complete(identity, JSON.stringify({ id, result: message.result, state }));
    } catch { fail(id, "state_other"); }
    finally { if (active === id) { active = null; completing = false; } }
  };
  worker.onerror = () => {
    if (active !== null) {
      const id = active; active = null; completing = false;
      fail(id, "worker_js");
    }
  };
  hostWindow.stockAICompute = async request => {
    if (!Number.isSafeInteger(request.id) || active !== null) return;
    const id = request.id;
    active = id;
    const input = { ...request };
    const transfer: Transferable[] = [];
    try {
      if (input.command === "initialize") {
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
      input.trace = true; input.transfer_state = true;
      bridge.progress?.(String(id), "posting-input");
      worker.postMessage(input, transfer);
    } catch {
      fail(id, "state_other");
      if (active === id) { active = null; completing = false; }
    } finally { delete input.state; delete input.state_bytes; }
  };
  bridge.ready();
}
export {};

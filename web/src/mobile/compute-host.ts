// Only the APK-owned WebView loads this entry; it exposes no provider or account credentials.
interface ComputeBridge {
  ready(): void;
  complete(identity: string, payload: string): void;
}
interface HostWindow extends Window {
  StockAICompute?: ComputeBridge;
  stockAICompute?: (request: { id: number; command: string }) => void;
}
const hostWindow = window as HostWindow;
const bridge = hostWindow.StockAICompute;
if (bridge) {
  const worker = new Worker(new URL("./compute-worker.ts", import.meta.url), { type: "module" });
  let active: number | null = null;
  worker.onmessage = (event: MessageEvent<{ id: number; error?: string }>) => {
    if (event.data.id !== active) return;
    const identity = String(active); active = null;
    bridge.complete(identity, JSON.stringify(event.data.error ? { error: "COMPUTE_WORKER_FAILED" } : event.data));
  };
  worker.onerror = () => {
    if (active !== null) {
      const identity = String(active); active = null;
      bridge.complete(identity, JSON.stringify({ error: "COMPUTE_WORKER_UNAVAILABLE" }));
    }
  };
  hostWindow.stockAICompute = request => {
    if (!Number.isSafeInteger(request.id) || active !== null) return;
    active = request.id; worker.postMessage(request);
  };
  bridge.ready();
}
export {};

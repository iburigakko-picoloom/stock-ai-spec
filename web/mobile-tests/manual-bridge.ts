// This browser-only bridge replaces native.ts in the test harness, never in a build.
interface Reply { reply: { status: number; body: unknown }; state?: string; error?: string }
const stateKey = "synthetic-manual-chatgpt-state";
const worker = new Worker(new URL("./manual-worker.ts", import.meta.url), { type: "module" });
let sequence = 0;
const pending = new Map<number, { resolve(value: Reply): void; reject(error: Error): void }>();
worker.onmessage = event => {
  const task = pending.get(event.data.id);
  if (!task) return;
  pending.delete(event.data.id);
  if (event.data.error) task.reject(new Error(event.data.error));
  else task.resolve(event.data);
};
worker.onerror = event => {
  for (const task of pending.values()) task.reject(new Error(event.message));
  pending.clear();
};
function send(value: Record<string, unknown>): Promise<Reply> {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    worker.postMessage({ ...value, id });
  });
}
const ready = fetch("/synthetic-manual-fixture.json").then(response => response.json()).then(fixture =>
  send({ command: "initialize", fixture, state: sessionStorage.getItem(stateKey) ?? "" }));
export const isAndroid = () => true;
export const StockAI = {
  async compute(input: { method: string; path: string; body: string }) {
    await ready;
    const result = await send({ command: "request", ...input });
    if (result.state) sessionStorage.setItem(stateKey, result.state);
    return result.reply;
  },
};
export async function advance(minutes: number): Promise<void> {
  await ready;
  await send({ command: "advance", minutes });
}
addEventListener("pagehide", () => worker.terminate(), { once: true });

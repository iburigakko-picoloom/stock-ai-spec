import { StockAI } from "./native";

interface Reply { result: { status: number; body: unknown } | null; state: string | null; error?: string }
let worker: Worker | null = null;
let generation = 0;
let sequence = 0;
let startup: Promise<void> | null = null;
let queue = Promise.resolve();
const pending = new Map<number, { resolve: (reply: Reply) => void; reject: (reason: Error) => void }>();

function send(input: Record<string, unknown>): Promise<Reply> {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    worker!.postMessage({ ...input, id });
  });
}

async function persist(reply: Reply): Promise<void> {
  if (reply.error) throw new Error(reply.error);
  if (reply.state !== null) {
    try {
      const saved = await StockAI.writeState({ generation, payload: reply.state });
      generation = saved.generation;
    } catch {
      worker?.terminate(); worker = null; startup = null;
      throw new Error("保存が確定しませんでした。保存済みの状態から再起動してください。");
    }
  }
}

async function start(): Promise<void> {
  const state = await StockAI.readState();
  generation = state.generation;
  worker = new Worker(new URL("./compute-worker.ts", import.meta.url), { type: "module" });
  worker.onmessage = (event: MessageEvent<Reply & { id: number }>) => {
    const item = pending.get(event.data.id);
    if (item) { pending.delete(event.data.id); item.resolve(event.data); }
  };
  worker.onerror = () => {
    for (const item of pending.values()) item.reject(new Error("端末内の計算環境が停止しました。アプリを再起動してください。"));
    pending.clear();
  };
  await persist(await send({ command: "initialize", state: state.payload }));
}

export async function mobileRequest<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  startup ??= start();
  await startup;
  let result!: T;
  const operation = queue.then(async () => {
    const reply = await send({ command: "request", method, path, body: JSON.stringify(body ?? null) });
    // Resolve a write only after Android's encrypted durable transaction commits.
    await persist(reply);
    if (!reply.result || reply.result.status >= 400) {
      const errorBody = reply.result?.body as { detail?: unknown } | undefined;
      throw new Error(typeof errorBody?.detail === "string" ? errorBody.detail : "入力または端末の状態を確認してください。");
    }
    result = reply.result.body as T;
  });
  queue = operation.catch(() => undefined);
  await operation;
  return result;
}

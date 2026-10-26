import { isAndroid } from "./mobile/native";
import { mobileRequest } from "./mobile/runtime";

const MANUAL_HEADERS = {
  "Content-Type": "application/json",
  "X-Stock-AI-Intent": "manual-record",
};

export { ApiError } from "./apiError";
import { responseError } from "./apiError";

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let body: unknown = null;
    try { body = await response.json(); } catch { /* Keep the HTTP status. */ }
    throw responseError(response.status, body);
  }
  return (await response.json()) as T;
}

async function performRead<T>(path: string): Promise<T> {
  if (isAndroid()) return mobileRequest<T>("GET", path);
  return parse<T>(
    await fetch(path, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    }),
  );
}

// Share concurrent reads only. A write is a barrier on both start and finish:
// no caller after a save may reuse an earlier in-flight read.
let writeEpoch = 0;
const reads = new Map<string, { epoch: number; promise: Promise<unknown> }>();
export function apiGet<T>(path: string): Promise<T> {
  const current = reads.get(path);
  if (current?.epoch === writeEpoch) return current.promise.then(value => structuredClone(value) as T);
  const entry = { epoch: writeEpoch, promise: Promise.resolve() as Promise<unknown> };
  entry.promise = performRead<T>(path).finally(() => { if (reads.get(path) === entry) reads.delete(path); });
  reads.set(path, entry);
  return entry.promise.then(value => structuredClone(value) as T);
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  writeEpoch++;
  try {
  if (isAndroid()) return await mobileRequest<T>("POST", path, body);
  return await parse<T>(await fetch(path, {
    method: "POST", headers: MANUAL_HEADERS, body: JSON.stringify(body), cache: "no-store",
  }));
  } finally { writeEpoch++; }
}

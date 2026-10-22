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

async function read<T>(path: string): Promise<T> {
  if (isAndroid()) return mobileRequest<T>("GET", path);
  return parse<T>(
    await fetch(path, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    }),
  );
}

export const apiGet = read;

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  if (isAndroid()) return mobileRequest<T>("POST", path, body);
  return parse<T>(await fetch(path, {
    method: "POST", headers: MANUAL_HEADERS, body: JSON.stringify(body), cache: "no-store",
  }));
}

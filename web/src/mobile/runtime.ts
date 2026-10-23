import { StockAI } from "./native";
import { responseError } from "../apiError";

// Android owns the serialized interpreter and durable writer. Activity changes
// never create another Python state or a second generation counter in the UI.
export async function mobileRequest<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const reply = await StockAI.compute({ method, path, body: JSON.stringify(body ?? null) });
  if (reply.status >= 400) {
    throw responseError(reply.status, reply.body);
  }
  const result = reply.body as T;
  if (path === "/api/v1/settings" && result && typeof result === "object") {
    const settings = result as { data?: { jQuantsApiKeyConfigured: boolean }; runtime?: { remoteAccess: string } };
    if (settings.data) settings.data.jQuantsApiKeyConfigured = (await StockAI.keyStatus()).configured;
    if (settings.runtime) settings.runtime.remoteAccess = "端末内で実行";
  }
  return result;
}

export async function restoreMobileState(payload: string): Promise<void> {
  // Native validates in an isolated interpreter and commits before swapping the
  // active owner state. Failed validation preserves the original durable data.
  await StockAI.restoreState({ payload });
  window.location.reload();
}

export async function restoreMobileBackup(token: string): Promise<void> {
  await StockAI.restoreBackup({ token, confirmed: true });
  window.location.reload();
}

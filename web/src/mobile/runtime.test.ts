import { beforeEach, expect, test, vi } from "vitest";
import { StockAI } from "./native";
import { mobileRequest, restoreMobileBackup } from "./runtime";

vi.mock("./native", () => ({ StockAI: { compute: vi.fn(), keyStatus: vi.fn(), restoreState: vi.fn(), restoreBackup: vi.fn() } }));
beforeEach(() => vi.resetAllMocks());

test("a mutation resolves only when the shared native owner acknowledges the durable result", async () => {
  let finish!: (value: { status: number; body: unknown }) => void;
  vi.mocked(StockAI.compute).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  let resolved = false;
  const result = mobileRequest("POST", "/api/v1/mobile/portfolio", { synthetic_only: true })
    .then(value => { resolved = true; return value; });
  await Promise.resolve();
  expect(resolved).toBe(false);
  finish({ status: 200, body: { saved: true } });
  await expect(result).resolves.toEqual({ saved: true });
  expect(StockAI.compute).toHaveBeenCalledWith({ method: "POST", path: "/api/v1/mobile/portfolio", body: '{"synthetic_only":true}' });
});

test("HTTP failure keeps the native committed receipt and exposes its stable reason", async () => {
  vi.mocked(StockAI.compute).mockResolvedValue({ status: 409, body: { detail: "口座・保有が更新されています" } });
  await expect(mobileRequest("POST", "/api/v1/mobile/portfolio", {})).rejects.toThrow("口座・保有が更新されています");
});

test("native errors preserve HTTP status and conflict code", async () => {
  vi.mocked(StockAI.compute).mockResolvedValue({ status: 409, body: { detail: "changed", code: "RECONCILIATION_BASE_CHANGED" } });
  await expect(mobileRequest("POST", "/api/v1/imports/positions/p/confirm", {})).rejects.toMatchObject({
    status: 409, detail: "changed", code: "RECONCILIATION_BASE_CHANGED",
  });
});

test("settings still decorate native key availability without reading credentials", async () => {
  vi.mocked(StockAI.compute).mockResolvedValue({ status: 200, body: { data: {}, runtime: {} } });
  vi.mocked(StockAI.keyStatus).mockResolvedValue({ configured: true });
  await expect(mobileRequest("GET", "/api/v1/settings")).resolves.toEqual({
    data: { jQuantsApiKeyConfigured: true }, runtime: { remoteAccess: "端末内で実行" },
  });
});

test("portable restore sends only a confirmed token and propagates native rejection", async () => {
  vi.mocked(StockAI.restoreBackup).mockRejectedValue(new Error("synthetic-native-conflict"));
  await expect(restoreMobileBackup("synthetic-preview")).rejects.toThrow("synthetic-native-conflict");
  expect(StockAI.restoreBackup).toHaveBeenCalledWith({ token: "synthetic-preview", confirmed: true });
  expect(StockAI.restoreState).not.toHaveBeenCalled();
});

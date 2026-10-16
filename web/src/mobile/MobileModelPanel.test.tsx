import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiGet, apiPost } from "../api";
import { StockAI } from "./native";
import { MobileModelPanel } from "./MobileModelPanel";

vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("./native", () => ({ StockAI: { importModel: vi.fn() } }));
afterEach(cleanup);
const model = { approved_bundle_count: 1, imported_bundle_count: 1, bundle_ready: true,
  model_adopted: false };
const run = { run_id: "fixture-run", phase: "published", outcome: "forecast",
  checked_at: "2026-02-03T11:50:00+09:00", scope: { as_of: "2026-02-03T11:30:00+09:00",
    universe: { latest_source_date: "2026-02-02" } },
  snapshot: { generated_at: "2026-02-03T11:50:00+09:00", data_as_of: "2026-02-03T02:15:00Z",
    predictions: [] }, outputs: [
    { horizon: 5, task: "regression", values: [["7203", .01]] },
    { horizon: 20, task: "regression", values: [["7203", .04]] },
  ], excluded_candidates: [{ symbol: "186A", reason: "FEATURE_HISTORY_UNAVAILABLE" }],
  blocking_reasons: [] };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? model : null);
});
test("one file imports the reviewed bundle and refreshes saved status", async () => {
  vi.mocked(StockAI.importModel).mockResolvedValue({ content: "synthetic bundle file" });
  render(<MobileModelPanel disabled={false} inputsSaved onBusy={vi.fn()} />);
  const button = screen.getByRole("button", { name: "モデル一式を取り込む" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/models/import", { content: "synthetic bundle file" }));
  expect(screen.getByText(/実運用の採用確認/)).toHaveTextContent("未完了・研究用");
});
test("frozen timestamps, excluded candidates and stored output remain readable", async () => {
  vi.mocked(apiPost).mockResolvedValue(run);
  render(<MobileModelPanel disabled={false} inputsSaved onBusy={vi.fn()} />);
  const button = screen.getByRole("button", { name: "当日の数値予測を計算・保存" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("数値予測を保存"));
  expect(screen.getByText(/数値生成：/)).toHaveTextContent("2026/2/3 11:50:00 JST");
  expect(screen.getByText(/参照情報の受領：/)).toHaveTextContent("2026/2/3 11:15:00 JST");
  expect(screen.getByText("2026/2/3 11:15:00 JST")).toHaveAttribute("datetime", "2026-02-03T02:15:00Z");
  expect(screen.getByText(/推奨株数/)).toHaveTextContent("未作成");
  fireEvent.click(screen.getByText("算出できた予測を見る 1社"));
  expect(screen.getByRole("cell", { name: "4%" })).toBeVisible();
  fireEvent.click(screen.getByText("履歴不足で予測を見送った候補 1社"));
  expect(screen.getByText("186A", { exact: true })).toBeVisible();
});
test("missing held prediction is incomplete with useful preserved numeric output", async () => {
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? model : {
    ...run, snapshot: null, phase: "blocked", outcome: "blocked", blocking_reasons: ["HELD_FORECAST_MISSING:1234"],
  });
  render(<MobileModelPanel disabled={false} inputsSaved onBusy={vi.fn()} />);
  await waitFor(() => expect(screen.getByText(/保有1234の予測/)).toBeVisible());
  expect(screen.getByText("算出できた予測を見る 1社")).toBeVisible();
});
test("unsaved personal changes disable generation while import remains available", async () => {
  render(<MobileModelPanel disabled={false} inputsSaved={false} onBusy={vi.fn()} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "モデル一式を取り込む" })).toBeEnabled());
  expect(screen.getByRole("button", { name: "当日の数値予測を計算・保存" })).toBeDisabled();
});

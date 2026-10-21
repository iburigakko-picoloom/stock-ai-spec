import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { StockAI } from "./native";
import { MobileModelPanel } from "./MobileModelPanel";

vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("./native", () => ({ StockAI: { importModel: vi.fn() } }));
afterEach(cleanup);
const model = { approved_bundle_count: 1, imported_bundle_count: 1, bundle_ready: true,
  model_adopted: false };
const decision = { run_id: "fixture-decision", phase: "published", outcome: "proposal",
  checked_at: "2026-02-03T11:50:01+09:00", is_active: true, blocking_reasons: [] };
function panel(inputsSaved = true): void {
  render(<MemoryRouter><MobileModelPanel disabled={false} inputsSaved={inputsSaved} onBusy={vi.fn()} /></MemoryRouter>);
}
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
  panel();
  const button = screen.getByRole("button", { name: "モデル一式を取り込む" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/models/import", { content: "synthetic bundle file" }));
  expect(screen.getByText(/実運用の採用確認/)).toHaveTextContent("未完了・研究用");
});
test("frozen timestamps, excluded candidates and stored output remain readable", async () => {
  vi.mocked(apiPost).mockImplementation(async path => path.includes("/decision/") ? decision : run);
  panel();
  const button = screen.getByRole("button", { name: "当日の予測・株数を計算・保存" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("予測と株数の判定を保存"));
  expect(vi.mocked(apiPost).mock.calls.map(call => call[0])).toEqual([
    "/api/v1/mobile/daily/generate", "/api/v1/mobile/decision/generate",
  ]);
  expect(screen.getByText(/数値生成：/)).toHaveTextContent("2026/2/3 11:50:00 JST");
  expect(screen.getByText(/参照情報の受領：/)).toHaveTextContent("2026/2/3 11:15:00 JST");
  expect(screen.getByText("2026/2/3 11:15:00 JST")).toHaveAttribute("datetime", "2026-02-03T02:15:00Z");
  expect(screen.getByText(/推奨株数/)).toHaveTextContent("保存済み・研究用");
  expect(screen.getByRole("link", { name: "今日の判定を見る" })).toHaveAttribute("href", "/today");
  fireEvent.click(screen.getByText("算出できた予測を見る 1社"));
  expect(screen.getByRole("cell", { name: "4%" })).toBeVisible();
  fireEvent.click(screen.getByText("履歴不足で予測を見送った候補 1社"));
  expect(screen.getByText("186A", { exact: true })).toBeVisible();
});
test("missing held prediction is incomplete with useful preserved numeric output", async () => {
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? model : path.endsWith("/decision") ? null : {
    ...run, snapshot: null, phase: "blocked", outcome: "blocked", blocking_reasons: ["HELD_FORECAST_MISSING:1234"],
  });
  panel();
  await waitFor(() => expect(screen.getByText(/保有1234の予測/)).toBeVisible());
  expect(screen.getByText("算出できた予測を見る 1社")).toBeVisible();
});
test("unsaved personal changes disable generation while import remains available", async () => {
  panel(false);
  await waitFor(() => expect(screen.getByRole("button", { name: "モデル一式を取り込む" })).toBeEnabled());
  expect(screen.getByRole("button", { name: "当日の予測・株数を計算・保存" })).toBeDisabled();
});
test("quantity save failure preserves the already saved numerical stage", async () => {
  vi.mocked(apiPost).mockResolvedValueOnce(run).mockRejectedValueOnce(new Error("株数の保存を再開してください"));
  panel();
  const button = screen.getByRole("button", { name: "当日の予測・株数を計算・保存" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("株数の保存を再開"));
  fireEvent.click(screen.getByText("計算時刻・参照情報"));
  expect(screen.getByText(/数値生成：/)).toBeVisible();
  expect(screen.queryByRole("link", { name: "今日の判定を見る" })).not.toBeInTheDocument();
});
test.each(["cash_only", "proposal"])("saved %s receipt displays only while its references are current", async outcome => {
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? model : path.endsWith("/daily") ? run : { ...decision, outcome, is_active: false });
  panel();
  await waitFor(() => expect(screen.getByText(/保存後に入力や計算対象が変わっています/)).toBeVisible());
  expect(screen.queryByRole("link", { name: "今日の判定を見る" })).not.toBeInTheDocument();
});

test("return-only research imports without adoption and opens manual consultation", async () => {
  const research = { ...model, approved_bundle_count: 0, research_bundle_count: 1,
    return_only_research: true, risk_available: false };
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? research : null);
  vi.mocked(apiPost).mockImplementation(async path => path.includes("/decision/") ? {
    ...decision, outcome: "blocked", phase: "blocked", is_active: false,
    blocking_reasons: ["FORECAST_RISK_UNAVAILABLE"],
  } : { ...run, snapshot: { ...run.snapshot, candidate_symbols: ["7203"], holding_symbols: ["7203"] } });
  panel();
  await waitFor(() => expect(screen.getByRole("button", { name: "モデル一式を取り込む" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "当日の予測を計算・保存" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("ChatGPTへの相談"));
  expect(screen.getByRole("link", { name: "予測を使ってChatGPTへ相談する" })).toHaveAttribute("href", "/today/chatgpt");
  expect(screen.queryByRole("link", { name: "今日の判定を見る" })).not.toBeInTheDocument();
  expect(screen.getByText(/自動判定に必要なリスク情報・検証がそろっていません/)).toBeVisible();
  expect(screen.getByText("上位20と全保有の予測を見る 1社")).toBeVisible();
  expect(screen.getByText(/実運用の採用確認/)).toHaveTextContent("未完了・研究用");
});

test("rank-only research preserves units, all holdings and unavailable returns", async () => {
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? {
    ...model, approved_bundle_count: 0, research_bundle_count: 1, ensemble_research: true,
  } : null);
  vi.mocked(apiPost).mockImplementation(async path => path.includes("/decision/") ? {
    ...decision, outcome: "blocked", phase: "blocked", is_active: false,
    blocking_reasons: ["FORECAST_RISK_UNAVAILABLE"],
  } : { ...run, snapshot: { ...run.snapshot, candidate_symbols: ["1000"], holding_symbols: ["7203"] },
    outputs: [
      { horizon: 5, role: "ranking", values: [["1000", .4], ["7203", .2]] },
      { horizon: 20, role: "ranking", values: [["1000", .9], ["7203", .1]] },
    ] });
  panel();
  const button = await screen.findByRole("button", { name: "当日の予測を計算・保存" });
  fireEvent.click(button);
  const summary = await screen.findByText("上位20と全保有の予測を見る 2社");
  fireEvent.click(summary);
  expect(screen.getByRole("columnheader", { name: "20日順位スコア" })).toBeVisible();
  expect(screen.getByRole("cell", { name: "0.9000" })).toBeVisible();
  expect(screen.getByRole("link", { name: "7203" })).toBeVisible();
  expect(screen.getAllByRole("cell", { name: "未提供" })).toHaveLength(4);
  expect(screen.queryByText(/NaN|90%/)).not.toBeInTheDocument();
  expect(screen.getByText(/期待リターン率ではありません/)).toBeVisible();
});

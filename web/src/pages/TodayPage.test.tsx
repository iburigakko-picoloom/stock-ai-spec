import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { useApiData } from "../hooks";
import { TodayPage } from "./TodayPage";
import type { TodayResponse } from "../types";
import { isAndroid } from "../mobile/native";

vi.mock("../hooks", () => ({ useApiData: vi.fn() }));
vi.mock("../mobile/DailyPanel", () => ({ DailyPanel: () => null, DailyStatusLink:()=>null }));
vi.mock("../mobile/native", () => ({ isAndroid: vi.fn(() => false) }));
afterEach(() => { cleanup(); vi.mocked(isAndroid).mockReturnValue(false); });
const data: TodayResponse = {
  businessDate: "2026-10-22", pipelineState: "PRE_MARKET", isStale: true,
  blockingReason: "ALPHA_CUTOFF_OPEN", runtimeMode: "RESEARCH", proposal: null,
  savedAnalysis: { snapshotId: "old", asOf: "2026-10-21T11:30:00+09:00",
    generatedAt: "2026-10-21T11:40:00+09:00", dataAsOf: "2026-10-21T11:00:00+09:00",
    modelVersion: "research-v1", readOnly: true, holdingSymbols: ["1234"],
    predictions: [{ symbol: "1234", expected_return_5d: null, expected_return_20d: .02, rank_score_20d: .8 }] },
};
function response(value: TodayResponse, loading = false) {
  vi.mocked(useApiData).mockReturnValue({ data: value, loading, savedAt: null, error: null, reload: vi.fn() });
}
test("previous saved analysis stays read-only through refresh and switches with new archive", () => {
  response(data);
  const view = render(<MemoryRouter><TodayPage /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "2026/10/21の分析" })).toBeVisible();
  expect(screen.getByText("今日の予測は11:30以降に更新します。時刻までお待ちください。")).toBeVisible();
  expect(screen.getByText("1234")).toBeVisible();
  expect(screen.getByText("（保有）")).toBeVisible();
  expect(screen.getByText("—")).toBeVisible();
  expect(screen.queryByRole("link", { name: /判断を確認/ })).not.toBeInTheDocument();
  response(data, true);
  view.rerender(<MemoryRouter><TodayPage /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "2026/10/21の分析" })).toBeVisible();
  expect(screen.getByText("更新状況を確認中…")).toBeVisible();
  response({ ...data, savedAnalysis: { ...data.savedAnalysis!, snapshotId: "new", asOf: "2026-10-22T11:30:00+09:00" } });
  view.rerender(<MemoryRouter><TodayPage /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "2026/10/22の分析" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "2026/10/21の分析" })).not.toBeInTheDocument();
});
test("no saved result shows preparation instead of a fictional previous analysis", () => {
  response({ ...data, savedAnalysis: null });
  render(<MemoryRouter><TodayPage /></MemoryRouter>);
  expect(screen.getByText("今日の提案をまだ表示できません")).toBeVisible();
  expect(screen.queryByRole("region", { name: "保存済み分析" })).not.toBeInTheDocument();
  expect(screen.queryByText("ALPHA_CUTOFF_OPEN")).not.toBeInTheDocument();
});

test("new reference analysis names the price date without pretending it was generated then", () => {
  response({ ...data, savedAnalysis: { ...data.savedAnalysis!, analysisKind: "latest_available_reference", priceDate: "2026-10-23", generatedAt: "2026-10-24T23:00:00+09:00" } });
  render(<MemoryRouter><TodayPage /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "2026-10-23の終値によるランキング" })).toBeVisible();
  expect(screen.getByText(/ランキングからChatGPTに相談できます/)).toBeVisible();
  expect(screen.queryByRole("link", { name: /判断を確認/ })).not.toBeInTheDocument();
});

test("Android keeps the saved analysis visible during refresh without a loading card", () => {
  vi.mocked(isAndroid).mockReturnValue(true);
  response(data, true);
  render(<MemoryRouter><TodayPage /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "2026/10/21の分析" })).toBeVisible();
  expect(screen.getByText(/前回の表示・閲覧用/)).toBeVisible();
  expect(screen.queryByText("更新状況を確認中…")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /判断を確認/ })).not.toBeInTheDocument();
});

test("Android shows previous proposal during refresh but enables review only after fresh success", () => {
  vi.mocked(isAndroid).mockReturnValue(true);
  const current: TodayResponse = { ...data, isStale: false, proposal: {
    proposalId: "previous", asOf: data.savedAnalysis!.asOf, generatedAt: data.savedAnalysis!.generatedAt,
    modelBundleVersion: "fixture", decisionEngineVersion: "fixture", status: "READY",
    isResearchOnly: true, isOrderInstruction: false, estimatedSellValue: "0", estimatedBuyValue: "0",
    estimatedTransactionCost: "0", estimatedTaxEffect: "0", estimatedTaxCashWithholding: "0",
    estimatedCashAfter: { fixture: "1040000" }, changeCount: 0, holdExpectedValue: "0",
    proposedExpectedValue: "0", netImprovement: "0", noTradeReason: "前回の結果", lines: [],
  } };
  response(current, true);
  const view = render(<MemoryRouter><TodayPage /></MemoryRouter>);
  expect(screen.getByText("前回の結果")).toBeVisible();
  expect(screen.queryByRole("link", { name: /判断を確認/ })).not.toBeInTheDocument();
  response(current);
  view.rerender(<MemoryRouter><TodayPage /></MemoryRouter>);
  expect(screen.getByRole("link", { name: /判断を確認/ })).toBeVisible();
});

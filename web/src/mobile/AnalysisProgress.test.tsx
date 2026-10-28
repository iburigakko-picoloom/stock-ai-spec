import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AnalysisProgress } from "./AnalysisProgress";
import { StockAI, type AnalysisStatus } from "./native";
vi.mock("./native", () => ({ isAndroid: () => true, StockAI: { analysisStatus: vi.fn() } }));
afterEach(() => { cleanup(); vi.useRealTimers(); });
test("one foreground return causes one progress read", async () => {
  let finish!: (value: AnalysisStatus) => void;
  vi.mocked(StockAI.analysisStatus).mockReset().mockResolvedValueOnce({ state: "idle" })
    .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValue({ state: "idle" });
  render(<AnalysisProgress />);
  await waitFor(() => expect(StockAI.analysisStatus).toHaveBeenCalledTimes(1));
  await act(async () => { await Promise.resolve(); });
  act(() => { document.dispatchEvent(new Event("visibilitychange")); window.dispatchEvent(new Event("focus")); });
  await waitFor(() => expect(StockAI.analysisStatus).toHaveBeenCalledTimes(2));
  await act(async () => finish({ state: "running", percent: 32 }));
  expect(StockAI.analysisStatus).toHaveBeenCalledTimes(2);
  expect(screen.getByText(/32%/)).toBeVisible();
});
test("missing old reasons do not send the user to another copy of this screen", async () => {
  vi.mocked(StockAI.analysisStatus).mockResolvedValue({ state: "blocked" });
  render(<AnalysisProgress />);
  expect(await screen.findByText(/以前の失敗理由が記録されていません/)).toBeVisible();
  expect(screen.queryByText(/予測設定で/)).not.toBeInTheDocument();
});
test("a failed progress read is visible instead of silently appearing idle", async () => {
  vi.mocked(StockAI.analysisStatus).mockRejectedValue(new Error("unavailable"));
  render(<AnalysisProgress />);
  expect(await screen.findByRole("alert")).toHaveTextContent("進捗・停止理由を確認できません");
});
test("a delayed progress read warns, then displays the late result", async () => {
  vi.useFakeTimers();
  let finish!: (value: AnalysisStatus) => void;
  vi.mocked(StockAI.analysisStatus).mockReset().mockReturnValue(new Promise(resolve => { finish=resolve; }));
  const view=render(<AnalysisProgress />);
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
  expect(screen.getByRole("alert")).toHaveTextContent("進捗・停止理由を確認できません");
  expect(StockAI.analysisStatus).toHaveBeenCalledOnce();
  await act(async () => finish({state:"blocked",blockingReasons:["NO_USABLE_FORECAST"]}));
  expect(screen.getByText(/予測に必要な株価履歴が不足/)).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  view.unmount(); vi.useRealTimers();
});
test("reopened HTTP failure displays the diagnostic locally even without blocking reasons", async () => {
  vi.mocked(StockAI.analysisStatus).mockResolvedValue({ state: "blocked", responseStatus: 422, responseCode: "FORECAST_VALIDATION_FAILED", diagnostic: "ValueError:stock_ai.mobile.forecasts:generate:443" });
  render(<AnalysisProgress />);
  expect(await screen.findByText(/診断コード：FORECAST_VALIDATION_FAILED/)).toHaveTextContent("ValueError:stock_ai.mobile.forecasts:generate:443");
  expect(screen.queryByText(/予測設定で|続きから再開/)).not.toBeInTheDocument();
});
test("blocked model inputs show a persistent reason instead of a stuck 99% retry", async () => {
  vi.mocked(StockAI.analysisStatus).mockResolvedValue({ state: "blocked", percent: 99, blockingReasons: ["ENSEMBLE_RANK_POPULATION_INCOMPLETE"] });
  render(<AnalysisProgress />);
  expect(await screen.findByText("分析を完了できませんでした")).toBeVisible();
  expect(screen.getByText(/モデルが必要とする銘柄の株価履歴が不足/)).toBeVisible();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  expect(screen.queryByText(/続きから再開/)).not.toBeInTheDocument();
});
test("displays durable percentage and resume status after reopening", async () => {
  vi.mocked(StockAI.analysisStatus).mockResolvedValue({ state: "interrupted", phase: "features", percent: 43, savedUnits: 43, totalUnits: 100 });
  render(<AnalysisProgress />);
  expect(await screen.findByText("中断・途中保存済み 43%")).toBeVisible();
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "43");
  expect(screen.getByText(/保存済みの続きから再開/)).toBeVisible();
});
test("does not invent a percentage before the work population is known", async () => {
  vi.mocked(StockAI.analysisStatus).mockResolvedValue({ state: "running", phase: "preparing", percent: null });
  render(<AnalysisProgress />);
  expect(await screen.findByText(/データ準備中/)).toBeVisible();
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("value");
});

test("keeps failure reason visible after reopening and identifies saving", async () => {
  vi.mocked(StockAI.analysisStatus).mockResolvedValue({ state: "interrupted", phase: "saving", percent: 99, failure: "timeout" });
  const view = render(<AnalysisProgress />);
  expect(await screen.findByText(/処理時間の上限で中断/)).toBeVisible();
  view.unmount();
  vi.mocked(StockAI.analysisStatus).mockResolvedValue({ state: "running", phase: "saving", percent: 99 });
  render(<AnalysisProgress />);
  expect(await screen.findByText("予測結果を保存中 99%")).toBeVisible();
});


test("a slow progress read does not enqueue polls and focus requests one follow-up", async () => {
  vi.useFakeTimers();
  vi.mocked(StockAI.analysisStatus).mockReset();
  let finish!: (value: { state: "idle" }) => void;
  vi.mocked(StockAI.analysisStatus).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValue({ state: "running", percent: 32 });
  const view = render(<AnalysisProgress />);
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000); window.dispatchEvent(new Event("focus")); window.dispatchEvent(new Event("focus")); });
  await act(async () => { await vi.advanceTimersByTimeAsync(16); });
  expect(StockAI.analysisStatus).toHaveBeenCalledTimes(1);
  await act(async () => { finish({ state: "idle" }); });
  expect(StockAI.analysisStatus).toHaveBeenCalledTimes(2);
  expect(screen.getByText(/32%/)).toBeVisible();
  view.unmount(); vi.useRealTimers();
});


test("backgrounding pauses progress polling and foregrounding refreshes it", async () => {
  vi.useFakeTimers();
  let visibility: DocumentVisibilityState = "visible";
  const visible = vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
  vi.mocked(StockAI.analysisStatus).mockReset().mockResolvedValue({ state: "running", percent: 10 });
  const view = render(<AnalysisProgress />);
  await act(async () => {});
  expect(StockAI.analysisStatus).toHaveBeenCalledTimes(1);
  visibility = "hidden";
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await vi.advanceTimersByTimeAsync(10_000); });
  expect(StockAI.analysisStatus).toHaveBeenCalledTimes(1);
  visibility = "visible";
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await vi.advanceTimersByTimeAsync(16); });
  expect(StockAI.analysisStatus).toHaveBeenCalledTimes(2);
  view.unmount(); visible.mockRestore(); vi.useRealTimers();
});

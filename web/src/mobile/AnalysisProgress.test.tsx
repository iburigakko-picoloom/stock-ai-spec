import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AnalysisProgress } from "./AnalysisProgress";
import { StockAI } from "./native";
vi.mock("./native", () => ({ isAndroid: () => true, StockAI: { analysisStatus: vi.fn() } }));
afterEach(cleanup);
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

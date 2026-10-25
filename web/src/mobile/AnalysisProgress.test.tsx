import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AnalysisProgress } from "./AnalysisProgress";
import { StockAI } from "./native";
vi.mock("./native", () => ({ isAndroid: () => true, StockAI: { analysisStatus: vi.fn() } }));
afterEach(cleanup);
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

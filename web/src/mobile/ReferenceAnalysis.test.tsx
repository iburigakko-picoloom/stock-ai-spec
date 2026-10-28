import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiPost } from "../api";
import { ReferenceAnalysis } from "./ReferenceAnalysis";

vi.mock("../api", () => ({ apiPost: vi.fn() }));
vi.mock("./native", () => ({ isAndroid: () => true }));
vi.mock("./AnalysisProgress", () => ({ AnalysisProgress: () => null }));
afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());
test("unknown blocking codes do not falsely route to market data", async () => {
  vi.mocked(apiPost).mockResolvedValue({ phase: "blocked", blocking_reasons: ["UNEXPECTED_CONTRACT"] });
  render(<MemoryRouter><ReferenceAnalysis onSaved={vi.fn()} hasSaved /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "ランキングを更新" }));
  expect(await screen.findByRole("status")).toHaveTextContent("UNEXPECTED_CONTRACT");
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

test("first analysis uses reference mode, prevents duplicate work and reloads the saved view", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiPost).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const reload = vi.fn();
  render(<MemoryRouter><ReferenceAnalysis onSaved={reload} hasSaved={false} /></MemoryRouter>);
  const button = screen.getByRole("button", { name: "ランキングを更新" });
  fireEvent.click(button); fireEvent.click(button);
  expect(apiPost).toHaveBeenCalledTimes(1);
  expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/daily/generate", { reference_only: true });
  expect(button).toBeDisabled();
  expect(screen.getByText(/途中結果は自動保存/)).toBeVisible();
  finish({ phase: "reference_saved", blocking_reasons: [] });
  await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("status")).toHaveTextContent("ランキングを保存しました");
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
});

test("explains when the current source data has already been predicted", async () => {
  vi.mocked(apiPost).mockResolvedValue({ phase: "reference_saved", blocking_reasons: [], reused: true });
  const reload = vi.fn();
  render(<MemoryRouter><ReferenceAnalysis onSaved={reload} hasSaved /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "ランキングを更新" }));
  expect(await screen.findByRole("status")).toHaveTextContent("予測済みのため、ランキングの更新は不要です");
  expect(reload).toHaveBeenCalledOnce();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

test.each([
  ["UNIVERSE_PRICE_SESSION_MISSING", "market"],
  ["ENSEMBLE_RANK_POPULATION_INCOMPLETE", "market"],
  ["PERSONAL_HOLDINGS_UNCONFIRMED", "holdings"],
  ["CALIBRATED_MODEL_BUNDLE_UNAVAILABLE", "model"],
])("%s directs to the actual prerequisite without generating a decision", async (code, target) => {
  vi.mocked(apiPost).mockResolvedValue({ phase: "blocked", blocking_reasons: [code] });
  const reload = vi.fn();
  render(<MemoryRouter><ReferenceAnalysis onSaved={reload} hasSaved /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "ランキングを更新" }));
  expect(await screen.findByRole("link")).toHaveAttribute("href", target === "holdings" ? "/holdings" : `/settings?edit=${target}`);
  expect(reload).not.toHaveBeenCalled();
  expect(apiPost).toHaveBeenCalledTimes(1);
});

test("preserves computation errors without falsely directing users to market inputs", async () => {
  vi.mocked(apiPost).mockRejectedValue(new Error("途中保存から再試行してください。"));
  render(<MemoryRouter><ReferenceAnalysis onSaved={vi.fn()} hasSaved={false} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "ランキングを更新" }));
  expect(await screen.findByRole("status")).toHaveTextContent("途中保存から再試行してください。");
  expect(screen.getByRole("button", { name: "ランキングを更新" })).toBeEnabled();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

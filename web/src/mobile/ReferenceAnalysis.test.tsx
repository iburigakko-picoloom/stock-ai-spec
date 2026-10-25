import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiPost } from "../api";
import { ReferenceAnalysis } from "./ReferenceAnalysis";

vi.mock("../api", () => ({ apiPost: vi.fn() }));
vi.mock("./native", () => ({ isAndroid: () => true }));
afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

test("first analysis uses reference mode, prevents duplicate work and reloads the saved view", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiPost).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const reload = vi.fn();
  render(<MemoryRouter><ReferenceAnalysis onSaved={reload} hasSaved={false} /></MemoryRouter>);
  const button = screen.getByRole("button", { name: "最新データで分析する" });
  fireEvent.click(button); fireEvent.click(button);
  expect(apiPost).toHaveBeenCalledTimes(1);
  expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/daily/generate", { reference_only: true });
  expect(button).toBeDisabled();
  expect(screen.getByText(/途中結果は自動保存/)).toBeVisible();
  finish({ phase: "reference_saved", blocking_reasons: [] });
  await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("status")).toHaveTextContent("参考分析を保存しました");
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
});

test.each([
  ["UNIVERSE_PRICE_SESSION_MISSING", "market"],
  ["PERSONAL_HOLDINGS_UNCONFIRMED", "accounts"],
  ["CALIBRATED_MODEL_BUNDLE_UNAVAILABLE", "model"],
])("%s directs to the actual prerequisite without generating a decision", async (code, target) => {
  vi.mocked(apiPost).mockResolvedValue({ phase: "blocked", blocking_reasons: [code] });
  const reload = vi.fn();
  render(<MemoryRouter><ReferenceAnalysis onSaved={reload} hasSaved /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "最新データで分析する" }));
  expect(await screen.findByRole("link")).toHaveAttribute("href", `/settings?edit=${target}`);
  expect(reload).not.toHaveBeenCalled();
  expect(apiPost).toHaveBeenCalledTimes(1);
});

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiGet, apiPost } from "../api";
import { MobileDevicePanel } from "./MobileDevicePanel";
import { ApiError } from "../apiError";

vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("./native", () => ({ isAndroid: () => true, StockAI: { keyStatus: async () => ({ configured: false }) } }));
vi.mock("./DailyPanel", () => ({ DailyControls: () => null, useDailyAutomation: () => ({ status: null, busy: false }) }));
vi.mock("./MobilePersonalPanel", () => ({ MobilePersonalPanel: () => null }));
beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);
const saved = { revision_id: "a".repeat(64), saved_at: "2026-10-01T00:00:00Z", portfolio: {
  schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: "10000",
  maximum_drawdown_percent: null, accounts: [], holdings: [],
} };
test("edit fields wait for hydration and preserve values after a rejected save", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiGet).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  render(<MemoryRouter initialEntries={["/settings?edit=capital"]}><MobileDevicePanel /></MemoryRouter>);
  const input = await screen.findByLabelText("投資上限（円・未定は空欄）");
  expect(input).toBeDisabled();
  await act(async () => finish(saved));
  expect(input).toBeEnabled(); expect(input).toHaveValue("10000");
  fireEvent.change(input, { target: { value: "20000" } });
  let fail!: (error: Error) => void;
  vi.mocked(apiPost).mockImplementation(() => new Promise((_resolve, reject) => { fail = reject; }));
  fireEvent.click(screen.getByRole("button", { name: "運用資金を保存" }));
  expect(input).toBeDisabled();
  await act(async () => fail(new ApiError(409, "changed")));
  expect(input).toHaveValue("20000"); expect(input).toBeEnabled();
  expect(apiGet).toHaveBeenCalledTimes(1);
  expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/portfolio", {
    expected_revision_id: saved.revision_id, portfolio: { ...saved.portfolio, investment_budget_yen: "20000" },
  });
});

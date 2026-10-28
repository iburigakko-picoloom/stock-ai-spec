import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiGet, apiPost } from "../api";
import { MobileDevicePanel } from "./MobileDevicePanel";
import { ApiError } from "../apiError";
import { StockAI } from "./native";

vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("./native", () => ({ isAndroid: () => true, StockAI: { keyStatus: async () => ({ configured: false }), readSavedView: vi.fn() } }));
vi.mock("./DailyPanel", () => ({ DailyControls: () => null, useDailyAutomation: () => ({ status: null, busy: false }) }));
beforeEach(() => { vi.resetAllMocks(); vi.mocked(StockAI.readSavedView).mockResolvedValue({ available: false }); });
afterEach(() => { cleanup(); vi.useRealTimers(); });
const saved = { revision_id: "a".repeat(64), saved_at: "2026-10-01T00:00:00Z", portfolio: {
  schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: "10000",
  maximum_drawdown_percent: null, accounts: [], holdings: [],
} };

test("failed settings read stops showing checking and retry hydrates the editor", async () => {
  vi.mocked(apiGet).mockRejectedValueOnce(new Error("failed")).mockResolvedValue(saved);
  render(<MemoryRouter><MobileDevicePanel /></MemoryRouter>);
  expect(await screen.findByRole("button", { name: /運用資金.*再確認が必要/ })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "口座・保有を読み直す" }));
  expect(await screen.findByRole("button", { name: /運用資金.*¥10,000/ })).toBeVisible();
});

test("saved settings stay read-only during a long read, then a late verified result enables editing", async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  let finish!: (value: unknown) => void;
  vi.mocked(apiGet).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  vi.mocked(StockAI.readSavedView).mockResolvedValue({ available: true, readOnly: true, savedAt: saved.saved_at, body: saved });
  render(<MemoryRouter><MobileDevicePanel /></MemoryRouter>);
  await act(async () => {});
  expect(screen.getByRole("button", { name: /運用資金.*¥10,000/ })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /運用資金.*¥10,000/ }));
  expect(screen.getByLabelText("投資上限（円・未定は空欄）")).toBeDisabled();
  await act(async () => { await vi.advanceTimersByTimeAsync(45_000); });
  expect(screen.getByRole("alert")).toHaveTextContent("時間がかかっています");
  await act(async () => finish(saved));
  expect(screen.getByLabelText("投資上限（円・未定は空欄）")).toBeEnabled();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
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


test("account subpages have separate history and preserve unsaved portfolio edits", async () => {
  const profile = { ...saved, portfolio: { ...saved.portfolio, accounts: [{ id: "acct", name: "保存済み口座", account_type: "nisa", withholding_mode: "not_applicable", available_cash_yen: "10000" }] } };
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("readiness")
    ? { input_gaps: ["personal_settings"], initial_ledger: { blocking_reasons: [] }, comparison: { ledger_portfolio_id: null, blocking_reasons: [] } }
    : path.endsWith("settings") ? { saved: null, current_portfolio: profile } : profile);
  render(<MemoryRouter initialEntries={["/settings?edit=accounts"]}><MobileDevicePanel /></MemoryRouter>);
  const row = await screen.findByRole("button", { name: /現金・買付余力.*入力済み/ });
  expect(screen.queryByRole("textbox", { name: "口座の呼び名" })).not.toBeInTheDocument();
  fireEvent.click(row);
  expect(screen.getByRole("heading", { name: "現金・買付余力" })).toBeVisible();
  fireEvent.change(await screen.findByRole("textbox", { name: "現金入力（円）" }), { target: { value: "12345" } });
  fireEvent.click(screen.getByRole("button", { name: "← 証券口座へ" }));
  expect(screen.getByRole("button", { name: /現金・買付余力.*未保存/ })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /現金・買付余力.*未保存/ }));
  expect(screen.getByRole("textbox", { name: "現金入力（円）" })).toHaveValue("12345");
  expect(screen.queryByRole("button", { name: "口座を追加" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /保有株を追加/ })).not.toBeInTheDocument();
  expect(apiPost).not.toHaveBeenCalled();
});

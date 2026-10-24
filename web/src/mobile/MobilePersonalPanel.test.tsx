import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiGet, apiPost } from "../api";
import { MobilePersonalPanel } from "./MobilePersonalPanel";
import { emptySettings, type Readiness, type SavedPortfolio, type SavedSettings } from "./personal";

vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
afterEach(cleanup);

test("profile revision changes preserve edits and require explicit rebase", async () => {
  const { rerender } = render(<MobilePersonalPanel profile={profile} disabled={false} />);
  const year = await screen.findByRole("spinbutton", { name: "損益の対象年" });
  fireEvent.change(year, { target: { value: "2025" } });
  const reads = vi.mocked(apiGet).mock.calls.length;
  rerender(<MobilePersonalPanel profile={{ ...profile, revision_id: "d".repeat(64) }} disabled={false} />);
  expect(year).toHaveValue(2025);
  expect(screen.getByRole("button", { name: "補足設定を保存" })).toBeDisabled();
  expect(apiGet).toHaveBeenCalledTimes(reads + 2);
  await waitFor(() => expect(screen.getByRole("button", { name: "最新の口座・保有に合わせて見直す" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "最新の口座・保有に合わせて見直す" }));
  expect(year).toHaveValue(2025);
  await waitFor(() => expect(screen.getByRole("button", { name: "補足設定を保存" })).toBeEnabled());
});

test("pending save keeps the form, shows progress and retains input on failure", async () => {
  let rejectSave!: (error: Error) => void;
  vi.mocked(apiPost).mockImplementation(() => new Promise((_resolve, reject) => { rejectSave = reject; }));
  render(<MobilePersonalPanel profile={profile} disabled={false} />);
  const save = await screen.findByRole("button", { name: "補足設定を保存" });
  const year = screen.getByRole("spinbutton", { name: "損益の対象年" });
  fireEvent.change(year, { target: { value: "2026" } });
  fireEvent.click(save);
  expect(screen.getByText("端末で確認・保存中…")).toBeInTheDocument();
  expect(save).toBeDisabled();
  fireEvent.click(save);
  expect(apiPost).toHaveBeenCalledTimes(1);
  rejectSave(new Error("保存できませんでした"));
  await screen.findByText("保存できませんでした");
  expect(screen.queryByText("端末で確認・保存中…")).not.toBeInTheDocument();
  expect(year).toHaveValue(2026);
  expect(save).toBeEnabled();
});
const profile: SavedPortfolio = { revision_id: "a".repeat(64), saved_at: "2026-01-06T10:00:00Z", portfolio: {
  schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: null,
  maximum_drawdown_percent: null, accounts: [], holdings: [],
} };
const initial: Readiness["initial_ledger"] = { preview_id: "c".repeat(64), created_at: "2026-01-06T10:00:00Z",
  blocking_reasons: ["accounts"], prices: { date: null, prices: {}, source_hash: null }, portfolio: null };
const ready: Readiness = { input_gaps: ["accounts"], initial_ledger: initial,
  comparison: { ledger_portfolio_id: null, blocking_reasons: [{ code: "FORECAST_MISSING" }], research_only: true } };

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("readiness") ? ready : { saved: null, current_portfolio: profile });
});

test("incomplete settings can be saved without inventing amounts and blocked balances cannot be confirmed", async () => {
  render(<MobilePersonalPanel profile={profile} disabled={false} />);
  const save = await screen.findByRole("button", { name: "補足設定を保存" });
  await waitFor(() => expect(save).toBeEnabled());
  const draft = emptySettings(profile);
  const saved: SavedSettings = { revision_id: "b".repeat(64), saved_at: profile.saved_at, settings: draft };
  vi.mocked(apiPost).mockImplementation(async path => path.endsWith("settings") ? { saved, current_portfolio: profile } : initial);
  fireEvent.click(save);
  await screen.findByText("保存しました。");
  expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/personal/settings", { expected_revision_id: null, settings: draft });
  expect(draft.tax_assumptions.taxable_rate_percent).toBeNull();
  const preview = screen.getByRole("button", { name: "初回残高の確認内容を作る" });
  expect(preview).toBeEnabled();
  fireEvent.click(preview);
  await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/personal/initial/preview", {}));
  expect(screen.queryByRole("button", { name: "この内容を初回台帳に確定" })).not.toBeInTheDocument();
});

test("initial balances display every account and require explicit confirmation", async () => {
  const saved: SavedSettings = { revision_id: "b".repeat(64), saved_at: profile.saved_at, settings: emptySettings(profile) };
  const preview = { ...initial, blocking_reasons: [], prices: { date: "2026-01-05", prices: { "7203": "1000" }, source_hash: "d".repeat(64) },
    portfolio: { portfolio_id: "initial-test", accounts: [{ account_id: "test", display_name: "Synthetic account" }],
      cash: [{ account_bucket_id: "test", available_cash: "1000.0001", reserved_cash: "100" }],
      positions: [{ symbol: "7203", account_bucket_id: "test", shares: 37, average_acquisition_price: "900", market_price: "1000" }] } };
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("readiness") ? ready : { saved, current_portfolio: profile });
  vi.mocked(apiPost).mockImplementation(async path => path.endsWith("preview") ? preview : { portfolio_id: "initial-test" });
  render(<MobilePersonalPanel profile={profile} disabled={false} />);
  const create = await screen.findByRole("button", { name: "初回残高の確認内容を作る" });
  await waitFor(() => expect(create).toBeEnabled());
  fireEvent.click(create);
  const confirm = await screen.findByRole("button", { name: "この内容を初回台帳に確定" });
  expect(confirm).toBeDisabled();
  expect(screen.getByText(/Synthetic account：総現金 1000.0001円／確保中 100円/)).toBeInTheDocument();
  expect(screen.getByText(/7203 37株／取得単価 900円／参考価格 1000円/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: "この口座・保有・現金・税の保存内容を初回台帳に確定します" }));
  fireEvent.click(confirm);
  await screen.findByText("残高を登録しました。ホームで確認できます。");
  expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/personal/initial/confirm", { preview_id: initial.preview_id, confirmed: true });
});

test("a changed portfolio requires the settings to be reviewed and saved again", async () => {
  const draft = emptySettings(profile);
  draft.portfolio_revision_id = "0".repeat(64);
  draft.research_conditions_reviewed = true;
  const saved: SavedSettings = { revision_id: "b".repeat(64), saved_at: profile.saved_at, settings: draft };
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("readiness") ? ready : { saved, current_portfolio: profile });
  render(<MobilePersonalPanel profile={profile} disabled={false} />);
  const save = await screen.findByRole("button", { name: "補足設定を保存" });
  await waitFor(() => expect(screen.getByText("口座・保有が更新されています。補足設定を見直してください。")).toBeInTheDocument());
  expect(save).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "最新の口座・保有に合わせて見直す" }));
  expect(save).toBeEnabled();
  expect(screen.getByRole("checkbox", { name: "探索方法を含む研究用の比較条件を確認しました" })).not.toBeChecked();
  expect(screen.getByRole("button", { name: "初回残高の確認内容を作る" })).toBeDisabled();
});

test("saved exact policy stays selected and changing search requires renewed review", async () => {
  const draft = { ...emptySettings(profile), research_decision_policy: "daily-decision-engine-v2" as const,
    research_conditions_reviewed: true };
  const saved: SavedSettings = { revision_id: "b".repeat(64), saved_at: profile.saved_at, settings: draft };
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("readiness") ? ready : { saved, current_portfolio: profile });
  render(<MobilePersonalPanel profile={profile} disabled={false} />);
  const select = await screen.findByRole("combobox", { name: "株数の探索方法" });
  expect(select).toHaveValue("daily-decision-engine-v2");
  const review = screen.getByRole("checkbox", { name: "探索方法を含む研究用の比較条件を確認しました" });
  expect(review).toBeChecked();
  fireEvent.change(select, { target: { value: "daily-decision-engine-v3-bounded" } });
  expect(review).not.toBeChecked();
  expect(screen.getByText(/最良の組合せは保証しません/)).toBeInTheDocument();
});


test("overview distinguishes saved inputs, missing supplements and confirmed balance", async () => {
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("readiness")
    ? { ...ready, comparison: { ...ready.comparison, ledger_portfolio_id: "confirmed" } }
    : { saved: null, current_portfolio: profile });
  const onStep = vi.fn();
  render(<MobilePersonalPanel profile={profile} disabled={false} step="overview" onStep={onStep} portfolioStatus="入力済み" />);
  await waitFor(() => expect(screen.getByRole("button", { name: /取引の確認/ })).toHaveTextContent("未入力"));
  expect(screen.getByRole("button", { name: /口座・保有/ })).toHaveTextContent("入力済み");
  expect(screen.getByRole("button", { name: /残高登録/ })).toHaveTextContent("登録済み");
  expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /残高登録/ }));
  expect(onStep).toHaveBeenCalledWith("balances");
});

test("new unsaved supplements survive list navigation and cannot confirm a balance", async () => {
  const view = render(<MobilePersonalPanel profile={profile} disabled={false} step="conditions" />);
  fireEvent.click(await screen.findByRole("button", { name: "計算条件の確認・変更 →" }));
  const year = await screen.findByRole("spinbutton", { name: "損益の対象年" });
  fireEvent.change(year, { target: { value: "2026" } });
  view.rerender(<MobilePersonalPanel profile={profile} disabled={false} step="overview" />);
  expect(screen.getByRole("button", { name: /取引の確認/ })).toHaveTextContent("未保存");
  view.rerender(<MobilePersonalPanel profile={profile} disabled={false} step="balances" />);
  expect(screen.queryByRole("spinbutton", { name: "損益の対象年" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "初回残高の確認内容を作る" })).toBeDisabled();
  view.rerender(<MobilePersonalPanel profile={profile} disabled={false} step="conditions" />);
  expect(screen.getByRole("spinbutton", { name: "損益の対象年" })).toHaveValue(2026);
  expect(screen.queryByRole("button", { name: "初回残高の確認内容を作る" })).not.toBeInTheDocument();
});

test("overview never labels failed reads as missing or completed", async () => {
  vi.mocked(apiGet).mockRejectedValue(new Error("offline"));
  render(<MobilePersonalPanel profile={profile} disabled={false} step="overview" />);
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: /取引の確認/ })).toHaveTextContent("確認できません");
  expect(screen.getByRole("button", { name: /残高登録/ })).toHaveTextContent("確認できません");
});

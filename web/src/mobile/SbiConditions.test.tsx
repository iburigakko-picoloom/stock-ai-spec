import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { SbiConditions, sbiStandardSettings } from "./SbiConditions";
import { emptySettings, type PersonalSettings, type SavedPortfolio } from "./personal";

afterEach(cleanup);
const profile: SavedPortfolio = { revision_id: "a".repeat(64), saved_at: "2026-10-24T10:00:00Z", portfolio: {
  schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: "100000", maximum_drawdown_percent: 10,
  accounts: [{ id: "test", name: "試験口座", account_type: "taxable_specified", withholding_mode: "withholding", available_cash_yen: "100000" }], holdings: [],
} };

test("standard assumptions fill no account facts, fee eligibility or cash interpretation and use JST", () => {
  const blank = emptySettings(profile);
  const result = sbiStandardSettings(blank, new Date("2026-12-31T16:00:00Z"));
  expect(result.tax_year).toBe(2027);
  expect(result.tax_assumptions).toEqual({ effective_from: "2027-01-01", taxable_rate_percent: "20.315", nisa_opportunity_cost_percent: "0" });
  expect(result.accounts).toEqual(blank.accounts);
  expect(result.cash_basis).toBeNull();
  expect(result.cost_assumptions).toMatchObject({ commission_fixed_yen: null, commission_bps: null, minimum_commission_yen: null, zero_commission_confirmed: false, full_spread_bps: "10", slippage_bps: "5", impact_bps_at_full_adv: "25" });
  expect(blank.tax_year).toBeNull();
});

test("standard assumptions preserve saved custom amounts and prior tax year for explicit review", () => {
  const prior = sbiStandardSettings(emptySettings(profile), new Date("2025-01-01"));
  prior.cost_assumptions.full_spread_bps = "18";
  prior.cost_assumptions.commission_fixed_yen = "99";
  prior.tax_assumptions.taxable_rate_percent = "21";
  prior.accounts[0].reserved_cash_yen = "123.45";
  prior.accounts[0].realized_loss_ytd = "789";
  expect(sbiStandardSettings(prior, new Date("2026-10-24"))).toEqual(prior);
});

function Harness({ initial = emptySettings(profile), source = profile }: { initial?: PersonalSettings; source?: SavedPortfolio }) {
  const [draft, change] = useState(initial);
  return <><SbiConditions profile={source} draft={draft} change={change} onManual={vi.fn()} /><output data-testid="draft">{JSON.stringify(draft)}</output></>;
}
function read(): PersonalSettings { return JSON.parse(screen.getByTestId("draft").textContent!); }

test("no extra amount entry is required for no reserves, no sales and no carryforward; unknown remains unknown", () => {
  render(<Harness />);
  expect(screen.queryAllByRole("textbox")).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "標準の計算条件を使う" }));
  expect(read().accounts[0].pending_activity).toBe("unknown");
  fireEvent.change(screen.getByLabelText("注文用・出金用などに確保している現金"), { target: { value: "none" } });
  fireEvent.change(screen.getByLabelText("今年の売却による利益・損失"), { target: { value: "none" } });
  fireEvent.change(screen.getByLabelText("前年以前から繰り越して使う損失"), { target: { value: "none" } });
  fireEvent.change(screen.getByLabelText("残高に未反映の売買・入出金や、未決済の取引"), { target: { value: "pending" } });
  expect(read().accounts[0]).toMatchObject({ reserved_cash_yen: "0", pending_activity: "pending", realized_gain_ytd: "0", realized_loss_ytd: "0", loss_carryforward_user_input: "0" });
  expect(screen.queryAllByRole("textbox")).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("国内株式の「ゼロ革命」"), { target: { value: "free" } });
  expect(read().cost_assumptions).toMatchObject({ commission_fixed_yen: "0", commission_bps: "0", minimum_commission_yen: "0", zero_commission_confirmed: true });
  fireEvent.change(screen.getByLabelText("国内株式の「ゼロ革命」"), { target: { value: "" } });
  expect(read().cost_assumptions.commission_fixed_yen).toBeNull();
});

test("amount questions retain entered decimals; standard settings cannot erase them", () => {
  render(<Harness />);
  fireEvent.change(screen.getByLabelText("注文用・出金用などに確保している現金"), { target: { value: "amount" } });
  fireEvent.change(screen.getByLabelText("確保中の金額（円）"), { target: { value: "123.4567" } });
  fireEvent.change(screen.getByLabelText("今年の売却による利益・損失"), { target: { value: "amount" } });
  fireEvent.change(screen.getByLabelText("今年の売却益の合計（円）"), { target: { value: "900" } });
  fireEvent.change(screen.getByLabelText("今年の売却損の合計（正の円額）"), { target: { value: "50" } });
  fireEvent.click(screen.getByRole("button", { name: "標準の計算条件を使う" }));
  expect(read().accounts[0]).toMatchObject({ reserved_cash_yen: "123.4567", realized_gain_ytd: "900", realized_loss_ytd: "50" });
});

test("NISA asks only remaining capacity and explicitly marks unused tax inputs, preserving existing amounts", () => {
  const nisa = structuredClone(profile);
  nisa.portfolio.accounts[0].account_type = "nisa";
  const initial = emptySettings(nisa);
  initial.accounts[0].realized_gain_ytd = "100";
  render(<Harness initial={initial} source={nisa} />);
  expect(screen.queryByLabelText("今年の売却による利益・損失")).not.toBeInTheDocument();
  expect(screen.getByLabelText("今年の残り購入枠（円）")).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name: "NISAの課税計算を対象外にする" }));
  expect(read().accounts[0]).toMatchObject({ realized_gain_ytd: "100", realized_loss_ytd: "0", loss_carryforward_user_input: "0", nisa_annual_capacity_user_input: null, nisa_lifetime_capacity_user_input: null });
});

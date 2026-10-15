import { z } from "zod";
import type { ManualPortfolio } from "./portfolio";

const hash = z.string().regex(/^[0-9a-f]{64}$/);
export const amount = z.string().trim().regex(/^(0|[1-9]\d{0,11})(\.\d{1,4})?$/, "金額・率は0以上の数字で入力してください").nullable();
const percent = amount.refine(value => value === null || Number(value) <= 100, "率は100%以下にしてください");
const actualDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/).refine(value => {
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}, "日付を確認してください").nullable();
export const costLabels = {
  commission_fixed_yen: "1回の注文にかかる固定手数料（円）",
  commission_bps: "売買代金に対する手数料（bps）",
  minimum_commission_yen: "最低手数料（円）",
  full_spread_bps: "売値と買値の差・全幅（bps）",
  slippage_bps: "想定価格からのずれ（bps）",
  impact_bps_at_full_adv: "1日売買代金と同額を取引する場合の価格影響（bps）",
} as const;
export const taxLabels = {
  realized_gain_ytd: "今年の実現利益（円）",
  realized_loss_ytd: "今年の実現損失（円・正の金額）",
  loss_carryforward_user_input: "利用する繰越損失（円）",
  nisa_annual_capacity_user_input: "NISA・今年の残り購入枠（円）",
  nisa_lifetime_capacity_user_input: "NISA・生涯の残り購入枠（円）",
} as const;
const account = z.object({
  account_id: z.string().uuid(), reserved_cash_yen: amount,
  pending_activity: z.enum(["unknown", "none", "pending"]),
  realized_gain_ytd: amount, realized_loss_ytd: amount, loss_carryforward_user_input: amount,
  nisa_annual_capacity_user_input: amount, nisa_lifetime_capacity_user_input: amount,
}).strict();
export const personalSettingsInput = z.object({
  schema_version: z.literal("manual-personal-settings-v1"), portfolio_revision_id: hash,
  cash_basis: z.enum(["total_including_reserved", "deployable_after_reserved"]).nullable(),
  budget_basis: z.literal("maximum_total_equity_market_value").nullable(),
  nisa_capacity_basis: z.literal("remaining_purchase_notional_no_same_day_sale_restore"),
  tax_year: z.number().int().min(2000).max(2200).nullable(), accounts: z.array(account).max(30),
  cost_assumptions: z.object({
    commission_fixed_yen: amount, commission_bps: amount, minimum_commission_yen: amount,
    zero_commission_confirmed: z.boolean(), full_spread_bps: amount, slippage_bps: amount,
    impact_bps_at_full_adv: amount,
  }).strict(),
  tax_assumptions: z.object({ effective_from: actualDate, taxable_rate_percent: percent,
    nisa_opportunity_cost_percent: percent }).strict(),
  research_decision_policy: z.literal("daily-decision-engine-v2"),
  research_conditions_reviewed: z.boolean(),
}).strict().superRefine((value, ctx) => {
  if (new Set(value.accounts.map(item => item.account_id)).size !== value.accounts.length)
    ctx.addIssue({ code: "custom", message: "同じ口座の補足設定が重複しています" });
  const costs = value.cost_assumptions;
  const commissions = [costs.commission_fixed_yen, costs.commission_bps, costs.minimum_commission_yen];
  if (commissions.every(item => item !== null && Number(item) === 0) && !costs.zero_commission_confirmed)
    ctx.addIssue({ code: "custom", message: "手数料をすべて0にする場合は、無料であることを確認してください" });
  if (costs.zero_commission_confirmed && commissions.some(item => item !== null && Number(item) !== 0))
    ctx.addIssue({ code: "custom", message: "手数料無料の確認と、入力した手数料が一致していません" });
});
export type PersonalSettings = z.infer<typeof personalSettingsInput>;
export const settingsSave = z.object({ expected_revision_id: hash.nullable(), settings: personalSettingsInput }).strict();
export const savedSettings = z.object({ revision_id: hash, saved_at: z.string().datetime(), settings: personalSettingsInput }).strict();
export const settingsResponse = z.object({ saved: savedSettings.nullable(), current_portfolio_revision_id: hash.nullable() }).strict();
export type SavedSettings = z.infer<typeof savedSettings>;

function moneyUnits(value: string) {
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole) * BigInt(10000) + BigInt(fraction.padEnd(4, "0"));
}

export function blankAccount(accountId: string): PersonalSettings["accounts"][number] {
  return { account_id: accountId, reserved_cash_yen: null, pending_activity: "unknown",
    realized_gain_ytd: null, realized_loss_ytd: null, loss_carryforward_user_input: null,
    nisa_annual_capacity_user_input: null, nisa_lifetime_capacity_user_input: null };
}
export function emptySettings(revision: string, portfolio: ManualPortfolio): PersonalSettings {
  return { schema_version: "manual-personal-settings-v1", portfolio_revision_id: revision,
    cash_basis: null, budget_basis: null, tax_year: null, accounts: portfolio.accounts.map(item => blankAccount(item.id)),
    nisa_capacity_basis: "remaining_purchase_notional_no_same_day_sale_restore",
    cost_assumptions: { commission_fixed_yen: null, commission_bps: null, minimum_commission_yen: null,
      zero_commission_confirmed: false, full_spread_bps: null, slippage_bps: null, impact_bps_at_full_adv: null },
    tax_assumptions: { effective_from: null, taxable_rate_percent: null, nisa_opportunity_cost_percent: null },
    research_decision_policy: "daily-decision-engine-v2", research_conditions_reviewed: false };
}
export function validateSettingsPortfolio(settings: PersonalSettings, revision: string, portfolio: ManualPortfolio): string | null {
  if (settings.portfolio_revision_id !== revision) return "口座・保有が更新されています。最新の内容を読み直してください。";
  const expected = new Set(portfolio.accounts.map(item => item.id));
  if (settings.accounts.length !== expected.size || settings.accounts.some(item => !expected.has(item.account_id)))
    return "すべての口座の補足設定を確認してください。";
  for (const item of settings.accounts) {
    const source = portfolio.accounts.find(source => source.id === item.account_id)!;
    if (source.account_type !== "nisa" && (item.nisa_annual_capacity_user_input !== null || item.nisa_lifetime_capacity_user_input !== null))
      return `${source.name}の口座区分とNISA枠が一致していません。`;
    if (settings.cash_basis === "total_including_reserved" && source.available_cash_yen !== null
        && item.reserved_cash_yen !== null && moneyUnits(item.reserved_cash_yen) > moneyUnits(source.available_cash_yen))
      return `${source.name}の確保中の現金が総現金額を超えています。`;
  }
  return null;
}
export function inputGaps(settings: PersonalSettings, portfolio: ManualPortfolio): string[] {
  const missing: string[] = [];
  if (!portfolio.accounts.length) missing.push("口座の登録");
  if (portfolio.investment_budget_yen === null) missing.push("投資上限");
  if (portfolio.maximum_drawdown_percent === null) missing.push("許容下落率の希望");
  if (portfolio.holdings_status === "unrecorded") missing.push("現在の保有状況");
  if (!settings.cash_basis) missing.push("現金額の意味");
  if (!settings.budget_basis) missing.push("投資上限の意味の確認");
  if (settings.tax_year === null) missing.push("損益の対象年");
  for (const source of portfolio.accounts) {
    const item = settings.accounts.find(item => item.account_id === source.id);
    if (!item) { missing.push(`${source.name}の補足設定`); continue; }
    if (source.account_type === "unknown_manual" || source.withholding_mode === "unknown") missing.push(`${source.name}の口座区分・源泉徴収`);
    if (source.available_cash_yen === null || item.reserved_cash_yen === null) missing.push(`${source.name}の現金・確保中の金額`);
    if (item.pending_activity !== "none") missing.push(`${source.name}の未反映取引・決済の確認`);
    if (item.realized_gain_ytd === null || item.realized_loss_ytd === null || item.loss_carryforward_user_input === null) missing.push(`${source.name}の実現損益・繰越損失`);
    if (source.account_type === "nisa" && (item.nisa_annual_capacity_user_input === null || item.nisa_lifetime_capacity_user_input === null)) missing.push(`${source.name}のNISA残り枠`);
  }
  if (portfolio.holdings.some(item => item.average_acquisition_price_yen === null)) missing.push("全保有株の取得単価");
  if (Object.keys(costLabels).some(key => settings.cost_assumptions[key as keyof typeof costLabels] === null)) missing.push("費用の計算条件");
  if (Object.values(settings.tax_assumptions).some(value => value === null)) missing.push("税の計算条件");
  if (!settings.research_conditions_reviewed) missing.push("研究用比較条件の確認");
  return missing;
}

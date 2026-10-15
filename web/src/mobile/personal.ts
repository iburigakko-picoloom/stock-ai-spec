export interface LocalPortfolio {
  schema_version: "manual-portfolio-v1";
  holdings_status: "unrecorded" | "none" | "recorded";
  investment_budget_yen: string | null;
  maximum_drawdown_percent: number | null;
  accounts: { id: string; name: string; account_type: "unknown_manual" | "taxable_specified" | "taxable_general" | "nisa"; withholding_mode: "unknown" | "withholding" | "no_withholding" | "not_applicable"; available_cash_yen: string | null }[];
  holdings: { account_id: string; symbol: string; shares: number; average_acquisition_price_yen: string | null }[];
}
export interface SavedPortfolio { revision_id: string; saved_at: string; portfolio: LocalPortfolio }
export interface AccountSettings {
  account_id: string; reserved_cash_yen: string | null; pending_activity: "unknown" | "none" | "pending";
  realized_gain_ytd: string | null; realized_loss_ytd: string | null; loss_carryforward_user_input: string | null;
  nisa_annual_capacity_user_input: string | null; nisa_lifetime_capacity_user_input: string | null;
}
export const costLabels = {
  commission_fixed_yen: "1注文の固定手数料（円）", commission_bps: "売買代金に対する手数料（bps）",
  minimum_commission_yen: "最低手数料（円）", full_spread_bps: "売値と買値の差・全幅（bps）",
  slippage_bps: "想定価格からのずれ（bps）", impact_bps_at_full_adv: "1日売買代金と同額の取引に対する価格影響（bps）",
} as const;
export const taxLabels = {
  realized_gain_ytd: "今年の実現利益（円）", realized_loss_ytd: "今年の実現損失（正の円額）",
  loss_carryforward_user_input: "利用する繰越損失（円）", nisa_annual_capacity_user_input: "NISA・今年の残り購入枠（円）",
  nisa_lifetime_capacity_user_input: "NISA・生涯の残り購入枠（円）",
} as const;
export interface PersonalSettings {
  schema_version: "manual-personal-settings-v1"; portfolio_revision_id: string;
  cash_basis: "total_including_reserved" | "deployable_after_reserved" | null;
  budget_basis: "maximum_total_equity_market_value" | null;
  nisa_capacity_basis: "remaining_purchase_notional_no_same_day_sale_restore";
  tax_year: number | null; accounts: AccountSettings[];
  cost_assumptions: Record<keyof typeof costLabels, string | null> & { zero_commission_confirmed: boolean };
  tax_assumptions: { effective_from: string | null; taxable_rate_percent: string | null; nisa_opportunity_cost_percent: string | null };
  research_decision_policy: "daily-decision-engine-v2"; research_conditions_reviewed: boolean;
}
export interface SavedSettings { revision_id: string; saved_at: string; settings: PersonalSettings }
export interface SettingsResponse { saved: SavedSettings | null; current_portfolio: SavedPortfolio | null }
export interface InitialLedgerPreview {
  preview_id: string; created_at: string; blocking_reasons: string[];
  prices: { date: string | null; prices: Record<string, string>; source_hash: string | null };
  portfolio: { portfolio_id: string; accounts: { account_id: string; display_name: string }[];
    cash: { account_bucket_id: string; available_cash: string; reserved_cash: string }[];
    positions: { symbol: string; account_bucket_id: string; shares: number; average_acquisition_price: string; market_price: string }[] } | null;
}
export interface Readiness {
  input_gaps: string[]; initial_ledger: InitialLedgerPreview;
  comparison: { ledger_portfolio_id: string | null; blocking_reasons: { code: string }[]; research_only: true };
}
export function blankAccount(account_id: string): AccountSettings {
  return { account_id, reserved_cash_yen: null, pending_activity: "unknown", realized_gain_ytd: null,
    realized_loss_ytd: null, loss_carryforward_user_input: null, nisa_annual_capacity_user_input: null,
    nisa_lifetime_capacity_user_input: null };
}
export function emptySettings(profile: SavedPortfolio): PersonalSettings {
  return { schema_version: "manual-personal-settings-v1", portfolio_revision_id: profile.revision_id,
    cash_basis: null, budget_basis: null, nisa_capacity_basis: "remaining_purchase_notional_no_same_day_sale_restore",
    tax_year: null, accounts: profile.portfolio.accounts.map(x => blankAccount(x.id)),
    cost_assumptions: { commission_fixed_yen: null, commission_bps: null, minimum_commission_yen: null,
      zero_commission_confirmed: false, full_spread_bps: null, slippage_bps: null, impact_bps_at_full_adv: null },
    tax_assumptions: { effective_from: null, taxable_rate_percent: null, nisa_opportunity_cost_percent: null },
    research_decision_policy: "daily-decision-engine-v2", research_conditions_reviewed: false };
}
const gapLabels: Record<string, string> = {
  manual_input: "口座・保有の保存", personal_settings: "補足設定の保存", settings_outdated: "更新後の口座・保有に合わせた補足設定の見直し",
  holdings_status: "現在の保有状況", investment_budget_yen: "投資上限", maximum_drawdown_percent: "希望する最大下落率",
  accounts: "口座の登録", available_cash_yen: "各口座の現金", account_classification: "口座区分・源泉徴収の確認",
  average_acquisition_price_yen: "全保有株の取得単価", account_settings: "全口座の補足設定", cash_basis: "現金額の意味",
  budget_basis: "投資上限の意味の確認", tax_year: "損益の対象年", tax_year_outdated: "今年の損益・税状態の確認",
  tax_policy_future: "税の計算条件の適用開始日", reserved_cash_yen: "各口座の確保中の現金", pending_activity: "未反映取引・決済の確認",
  input_timestamp_future: "端末の時計と保存日時の確認",
  realized_tax_state: "実現損益・繰越損失", nisa_remaining_capacity: "NISAの残り購入枠", cost_assumptions: "費用の計算条件",
  tax_assumptions: "税の計算条件", research_conditions_reviewed: "研究用比較条件の確認",
  held_prices_missing: "保有株の同じ日付の未調整終値", held_prices_stale: "保有株の新しい日足価格", held_prices_invalid: "保存価格の整合性確認",
  ledger_already_initialized: "初回台帳は確定済みです。入力欄の編集では台帳を上書きしません。",
  executions_already_recorded: "記録済み約定の照合（初回台帳では上書きできません）",
  MANUAL_INPUT_MISSING: "口座・保有の保存", LEDGER_MISSING: "初回台帳の確認と確定", FORECAST_MISSING: "採用・一致確認を通した最新予測",
  SETTINGS_MISSING: "補足設定の完了", MARKET_MISSING: "比較時点の価格・銘柄・流動性の確認",
  MANUAL_INPUT_STALE_OR_AFTER_FORECAST: "予測時点に合う口座・保有の入力", LEDGER_STALE_OR_AFTER_FORECAST: "予測時点に合う台帳の照合",
};
export function gapLabel(code: string): string {
  if (code.startsWith("INPUT_MISSING_")) return gapLabel(code.slice(14).toLowerCase());
  return gapLabels[code] ?? "入力・台帳・予測の追加照合が必要です";
}

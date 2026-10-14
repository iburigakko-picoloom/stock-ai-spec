import { z } from "zod";

const money = z.string().trim().regex(/^(0|[1-9]\d{0,11})(\.\d{1,4})?$/, "金額は0以上の数字で入力してください").nullable();
export const accountTypeLabels = {
  unknown_manual: "未確認", taxable_specified: "特定口座", taxable_general: "一般口座", nisa: "NISA",
} as const;
export const withholdingLabels = {
  unknown: "未確認", withholding: "源泉徴収あり", no_withholding: "源泉徴収なし", not_applicable: "対象外（NISA）",
} as const;
const account = z.object({
  id: z.string().uuid(), name: z.string().trim().min(1, "口座の呼び名を入力してください").max(60),
  account_type: z.enum(["unknown_manual", "taxable_specified", "taxable_general", "nisa"]),
  withholding_mode: z.enum(["unknown", "withholding", "no_withholding", "not_applicable"]),
  available_cash_yen: money,
}).strict().superRefine((value, ctx) => {
  if ((value.account_type === "nisa") !== (value.withholding_mode === "not_applicable"))
    ctx.addIssue({ code: "custom", message: "NISAの源泉徴収は対象外にしてください" });
  if (value.account_type !== "taxable_specified" && value.withholding_mode === "withholding")
    ctx.addIssue({ code: "custom", message: "源泉徴収ありは特定口座に指定してください" });
});
const holding = z.object({
  account_id: z.string().uuid(), symbol: z.string().trim().toUpperCase().regex(/^[0-9A-Z]{4,5}$/, "銘柄コードは4〜5文字の英数字で入力してください"),
  shares: z.number({ invalid_type_error: "株数を数字で入力してください" })
    .int("株数は整数で入力してください").positive("株数は1株以上で入力してください")
    .max(1_000_000_000, "株数が大きすぎます"), average_acquisition_price_yen: money,
}).strict();
export const portfolioInput = z.object({
  schema_version: z.literal("manual-portfolio-v1"),
  holdings_status: z.enum(["unrecorded", "none", "recorded"]),
  investment_budget_yen: money,
  maximum_drawdown_percent: z.number().positive("最大下落率は0より大きい値にしてください")
    .max(100, "最大下落率は100%以下にしてください").nullable(),
  accounts: z.array(account).max(30), holdings: z.array(holding).max(200),
}).strict().superRefine((value, ctx) => {
  const accounts = value.accounts.map(item => item.id);
  if (new Set(accounts).size !== accounts.length)
    ctx.addIssue({ code: "custom", message: "同じ口座が重複しています" });
  const keys = value.holdings.map(item => `${item.account_id}:${item.symbol}`);
  if (new Set(keys).size !== keys.length)
    ctx.addIssue({ code: "custom", message: "同じ口座・銘柄は1行にまとめてください" });
  if (value.holdings.some(item => !accounts.includes(item.account_id)))
    ctx.addIssue({ code: "custom", message: "保有銘柄の口座を登録してください" });
  if ((value.holdings_status === "recorded") !== (value.holdings.length > 0))
    ctx.addIssue({ code: "custom", message: "保有ありなら銘柄を登録し、保有なしなら銘柄を空にしてください" });
});
export const portfolioSave = z.object({
  expected_revision_id: z.string().regex(/^[0-9a-f]{64}$/).nullable(),
  portfolio: portfolioInput,
}).strict();
export type ManualPortfolio = z.infer<typeof portfolioInput>;
export const savedPortfolio = z.object({
  revision_id: z.string().regex(/^[0-9a-f]{64}$/), saved_at: z.string().datetime(), portfolio: portfolioInput,
});
export const portfolioResponse = z.object({ saved: savedPortfolio.nullable() });
export type SavedPortfolio = z.infer<typeof savedPortfolio>;
export const emptyPortfolio: ManualPortfolio = {
  schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: null,
  maximum_drawdown_percent: null, accounts: [], holdings: [],
};

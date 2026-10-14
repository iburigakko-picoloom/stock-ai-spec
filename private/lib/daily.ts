import { z } from "zod";

const timestamp = z.string().datetime({ offset: true });
const hash = z.string().regex(/^[0-9a-f]{64}$/);
const finite = z.number().finite();
export const criteria = [
  "earnings_quality", "valuation_expectations", "balance_sheet_dilution",
  "catalyst_timing", "industry", "liquidity_portfolio_risk", "contrary_facts",
] as const;
export const criterionLabels = [
  "利益の質", "期待とバリュエーション", "財務・希薄化", "材料と時期", "業界環境",
  "流動性・保有リスク", "反対材料",
];
const forecast = z.object({
  symbol: z.string().min(1).max(16), holding: z.boolean(),
  expected_return_1d: z.null(), expected_return_5d: finite, expected_return_20d: finite,
  downside_quantile: finite, large_loss_probability: finite.min(0).max(1),
  uncertainty: finite.nonnegative(),
}).strict();
const finding = z.object({
  criterion: z.enum(criteria), assessment: z.enum(["support", "caution", "defer"]),
  note: z.string().min(1).max(4000),
  sources: z.array(z.object({
    title: z.string().min(1).max(500), url: z.string().url().startsWith("https://"),
    published_at: timestamp, checked_at: timestamp,
  }).strict()).max(30),
}).strict();
const research = z.object({
  research_id: hash, symbol: z.string().min(1).max(16), reviewed_at: timestamp,
  conclusion: z.enum(["support", "caution", "defer"]), findings: z.array(finding).length(7),
}).strict().superRefine((value, context) => {
  if (value.findings.some((item, index) => item.criterion !== criteria[index]))
    context.addIssue({ code: "custom", message: "seven ordered research criteria required" });
  if (value.findings.some((item) => item.assessment !== "defer" && !item.sources.length))
    context.addIssue({ code: "custom", message: "sources required" });
  if (value.conclusion === "support" && value.findings.some((item) => item.assessment === "defer"))
    context.addIssue({ code: "custom", message: "incomplete research cannot support" });
  if (value.findings.some((item) => item.sources.some((source) => Date.parse(source.published_at) > Date.parse(source.checked_at) || Date.parse(source.checked_at) > Date.parse(value.reviewed_at))))
    context.addIssue({ code: "custom", message: "invalid source timestamps" });
});
export const cloudPayload = z.object({
  schema_version: z.literal("daily-cloud-v1"), kind: z.enum(["readiness", "predictions"]),
  source_snapshot_id: hash.nullable(), as_of: timestamp, generated_at: timestamp,
  data_as_of: timestamp.nullable(), mode: z.enum(["research", "paper", "owner_approved"]),
  model_version: z.string().max(200).nullable(), feature_version: z.string().max(200).nullable(),
  unit: z.literal("fractional_return"), risk_horizon: z.literal(20),
  price_semantics: z.literal("daily_close_research_proxy"),
  label_definition: z.literal("next_session_adjusted_close_to_h_sessions_later"),
  large_loss_threshold: finite.gt(-1).lt(0).nullable(),
  downside_quantile_alpha: finite.gt(0).lt(.5).nullable(), adoption_review_id: hash.nullable(),
  training_completed: z.number().int().min(0).max(18), training_total: z.literal(18),
  blockers: z.array(z.string().min(1).max(1000)).max(30),
  forecasts: z.array(forecast).max(200), research: z.array(research).max(400),
}).strict().superRefine((value, context) => {
  const symbols = value.forecasts.map((item) => item.symbol);
  if (new Set(symbols).size !== symbols.length || value.forecasts.filter((item) => !item.holding).length > 20)
    context.addIssue({ code: "custom", message: "unique holdings and at most 20 new candidates required" });
  if (value.research.some((item) => !symbols.includes(item.symbol)))
    context.addIssue({ code: "custom", message: "research must reference a displayed original forecast" });
  if (value.kind === "readiness" && (value.forecasts.length || value.source_snapshot_id !== null || value.research.length))
    context.addIssue({ code: "custom", message: "readiness cannot contain model forecasts" });
  if (value.kind === "predictions" && (!value.source_snapshot_id || !symbols.length || !value.data_as_of || !value.model_version || !value.feature_version))
    context.addIssue({ code: "custom", message: "forecast provenance is required" });
  if (value.kind === "predictions" && (value.large_loss_threshold === null || value.downside_quantile_alpha === null))
    context.addIssue({ code: "custom", message: "risk event definitions required" });
  if ((value.mode === "owner_approved") !== Boolean(value.adoption_review_id) || (value.mode === "owner_approved" && (value.blockers.length || value.kind !== "predictions")))
    context.addIssue({ code: "custom", message: "owner review and resolved gates required" });
  if (value.research.some((item) => Date.parse(item.reviewed_at) < Date.parse(value.generated_at)))
    context.addIssue({ code: "custom", message: "research cannot precede original forecast" });
  if (Date.parse(value.generated_at) < Date.parse(value.as_of) || (value.data_as_of && Date.parse(value.data_as_of) > Date.parse(value.as_of)))
    context.addIssue({ code: "custom", message: "invalid timestamp order" });
});
export const syncInput = z.object({ snapshot_id: hash, payload_json: z.string().min(1).max(1_000_000) }).strict();
export type CloudPayload = z.infer<typeof cloudPayload>;
export async function sha256(text: string): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
export async function validateSync(input: unknown) {
  const request = syncInput.parse(input);
  if (await sha256(request.payload_json) !== request.snapshot_id) throw new Error("content hash mismatch");
  const payload = cloudPayload.parse(JSON.parse(request.payload_json));
  return { request, payload };
}

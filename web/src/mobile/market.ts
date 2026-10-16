import { apiGet, apiPost } from "../api";
import { StockAI } from "./native";

export interface MarketStatus {
  latest_data_date: string | null; completed_dates: string[];
  committed_acquisitions?: { date: string; acquisitionId: string }[];
}
export interface MarketPlan { first_day: string; last_day: string }
export type AcquisitionMode = "pending" | "corrections" | "restart";
export interface UniversePreview {
  as_of: string; latest_source_date: string | null; window_dates: string[];
  new_candidates: { symbol: string; company_name: string; rank: number }[];
  decision_symbols: string[]; held_only: string[]; blocking_reasons: string[];
  holdings_recorded?: boolean;
}
export function shiftDate(day: string, count: number): string {
  const value = new Date(`${day}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(value.getTime()) || value.toISOString().slice(0, 10) !== day)
    throw new Error("取得する日付を確認してください。");
  value.setUTCDate(value.getUTCDate() + count);
  return value.toISOString().slice(0, 10);
}
export function defaultPlan(): MarketPlan {
  const today = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  return { first_day: shiftDate(today, -420), last_day: shiftDate(today, -1) };
}
export function pendingDates(plan: MarketPlan, completed: string[]): string[] {
  const days: string[] = [];
  shiftDate(plan.first_day, 0); shiftDate(plan.last_day, 0);
  if (plan.first_day > plan.last_day) throw new Error("取得範囲の開始日と終了日を確認してください。");
  if ((Date.parse(plan.last_day) - Date.parse(plan.first_day)) / 86400000 > 730)
    throw new Error("取得範囲は最大2年分で指定してください。");
  const known = new Set(completed);
  for (let day = plan.first_day; day <= plan.last_day; day = shiftDate(day, 1)) {
    if (!known.has(day)) days.push(day);
  }
  return days;
}
let active = false;
export async function acquireRange(plan: MarketPlan, progress: (day: string, done: number, total: number, saved?: MarketStatus) => void,
  stopped: () => boolean, mode: AcquisitionMode = "pending"): Promise<{ stopped: boolean; status: MarketStatus }> {
  if (active) throw new Error("市場データは取得中です。");
  active = true;
  try {
    let status = await apiGet<MarketStatus>("/api/v1/mobile/market");
    const days = pendingDates(plan, mode === "pending" ? status.completed_dates : []);
    for (const receipt of status.committed_acquisitions ?? []) await StockAI.acknowledgeMarket(receipt);
    if (mode === "pending") await apiPost("/api/v1/mobile/market/plan", plan);
    if (mode === "restart") {
      if (days.length !== 1) throw new Error("取り直す日付を1日指定してください。");
      await StockAI.restartMarket({ date: days[0] });
    }
    let done = 0;
    for (const day of days) {
      if (stopped()) return { stopped: true, status };
      progress(day, done, days.length);
      const result = await StockAI.fetchMarket({ date: day });
      if (result.status !== 200) {
        if (result.status === 403) throw new Error("API 403：契約プラン・APIキー・対象期間を確認してください。取得済みページから再開できます。");
        if (result.status === 429) throw new Error("APIの取得上限です。時間をおいて再開してください。取得済みページは保持しています。");
        throw new Error(`データ取得に失敗しました（HTTP ${result.status}）。続きから再開できます。`);
      }
      if (result.date !== day || !result.acquisitionId || !result.received_at || !result.datasets || !result.valuations)
        throw new Error("取得結果が不完全です。保存日を進めず停止しました。");
      // mobileRequest resolves only after the encrypted native state commits.
      status = await apiPost<MarketStatus>("/api/v1/mobile/market/ingest", result);
      await StockAI.acknowledgeMarket({ date: day, acquisitionId: result.acquisitionId });
      progress(day, ++done, days.length, status);
    }
    return { stopped: stopped(), status };
  } finally { active = false; }
}

import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { StockAI } from "./native";

interface ModelStatus {
  approved_bundle_count: number; imported_bundle_count: number; bundle_ready: boolean;
  model_adopted: boolean; bundle_blocking_reason?: string | null;
  research_bundle_count?: number; return_only_research?: boolean; ensemble_research?: boolean; risk_available?: boolean;
}
interface ForecastRun {
  run_id: string; phase: string; outcome: string; checked_at: string;
  scope: { as_of: string; universe?: { latest_source_date?: string | null; policy?: string } };
  snapshot: { generated_at: string; data_as_of: string; predictions: { symbol: string;
    expected_return_5d: number | null; expected_return_20d: number | null }[];
    candidate_symbols?: string[]; holding_symbols?: string[] } | null;
  outputs: { horizon: number; task?: string; role?: string; values: [string, number][] }[];
  excluded_candidates: { symbol: string; reason: string }[]; blocking_reasons: string[];
}
interface DecisionRun {
  run_id: string; phase: string; outcome: string; checked_at: string;
  is_active: boolean; blocking_reasons: string[];
}
function reason(code: string): string {
  if (code.startsWith("HELD_FORECAST_MISSING:")) return `保有${code.split(":")[1]}の予測に必要な履歴が不足しています。`;
  const messages: Record<string, string> = {
    ALPHA_CUTOFF_OPEN: "11:30の締切後に計算できます。",
    PERSONAL_HOLDINGS_UNCONFIRMED: "口座・保有と初回台帳を確認してください。",
    PERSONAL_INPUT_AFTER_ALPHA_CUTOFF: "締切後に更新された口座・保有は次の営業日の計算対象になります。",
    LEDGER_RECEIVED_AFTER_ALPHA_CUTOFF: "締切後に確認した台帳は次の営業日の計算対象になります。",
    HOLDINGS_NEED_RECONCILIATION: "入力した保有と約定台帳を照合してください。",
    UNIVERSE_CURRENT_MEMBERSHIP_MISSING: "11:30までに受領した当日の銘柄一覧がありません。",
    UNIVERSE_CURRENT_MEMBERSHIP_MISSING_NO_VERIFIED_FALLBACK: "11:30までに受領した当日の銘柄一覧がありません。構成を確認できる一覧が必要です。",
    UNIVERSE_TOPIX500_SCALE_CATEGORIES_UNAVAILABLE: "TOPIX500の規模区分を確認できません。銘柄一覧の受領内容を確認してください。",
    UNIVERSE_HELD_INSTRUMENT_UNSUPPORTED_OR_NOT_LISTED: "対応する国内普通株として確認できない保有があります。銘柄と上場状況を確認してください。",
    UNIVERSE_NON_BUSINESS_DAY: "当日は休場日です。",
    CALIBRATED_MODEL_BUNDLE_UNAVAILABLE: "締切までに取り込まれた、利用条件を確認済みのモデル一式が必要です。",
    ENSEMBLE_REQUIRES_ALL_MARKET_FEATURES: "この合成モデルは全市場の順位を必要とします。現在の対象限定入力では計算できません。",
    ENSEMBLE_UNIVERSE_RULE_MISMATCH: "合成モデルと銘柄の対象方式が異なります。対応する研究用モデルを確認してください。",
    ENSEMBLE_UNSUPPORTED_RISK_HORIZON: "この研究用モデルのリスク対象期間には対応していません。",
    FORECAST_RISK_UNAVAILABLE: "株数の自動判定に必要なリスク情報・検証がそろっていません。ChatGPTへの相談と回答の検算を利用できます。",
    NO_USABLE_FORECAST: "候補銘柄の予測に必要な履歴が不足しています。",
    NUMERICAL_FORECAST_INCOMPLETE: "数値予測の保存を完了してから株数を計算します。",
    NUMERICAL_FORECAST_NOT_CURRENT_DAY: "当日の数値予測が必要です。",
    PERSONAL_INPUTS_INCOMPLETE: "口座・保有、補足設定と初回台帳を確認してください。",
    PERSONAL_INPUTS_DIFFER_FROM_NUMERICAL: "口座・保有が変わりました。当日の数値予測から計算し直してください。",
    PERSONAL_SETTINGS_AFTER_ALPHA_CUTOFF: "締切後に変更した補足設定は次の営業日の計算対象になります。",
    PERSONAL_INPUTS_STALE_OR_AFTER_FORECAST: "口座・保有と台帳の確認時点が古いか、当日の締切後です。",
    MODEL_SELECTION_DIFFERS_FROM_NUMERICAL: "数値予測とモデル一式が異なります。数値予測から計算し直してください。",
    FROZEN_MARKET_EVIDENCE_INVALID: "保存済みの価格・出来高の根拠を確認できません。",
    CASH_EXECUTIONS_UNRECONCILED: "約定記録と台帳を照合してください。",
  };
  return messages[code] ?? "保存済みの履歴・原予測・口座・保有・補足設定を確認してください。";
}
const percent = (value: number | undefined): string => value === undefined ? "未提供" : new Intl.NumberFormat("ja-JP", { style: "percent", maximumFractionDigits: 2 }).format(value);
const clock = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short" });
function timestamp(value: string): ReactNode {
  const date = new Date(value);
  return <time dateTime={value} title={value}>{Number.isNaN(date.valueOf()) ? "未確認" : clock.format(date)}</time>;
}

export function MobileModelPanel({ disabled, inputsSaved, onBusy }: {
  disabled: boolean; inputsSaved: boolean; onBusy: (value: boolean) => void;
}): ReactNode {
  const [model, setModel] = useState<ModelStatus | null>(null);
  const [run, setRun] = useState<ForecastRun | null>(null);
  const [decision, setDecision] = useState<DecisionRun | null>(null);
  const [message, setMessage] = useState("");
  useEffect(() => {
    void Promise.all([apiGet<ModelStatus>("/api/v1/mobile/models"), apiGet<ForecastRun | null>("/api/v1/mobile/daily"), apiGet<DecisionRun | null>("/api/v1/mobile/decision")])
      .then(([status, saved, shares]) => { setModel(status); setRun(saved); setDecision(shares); })
      .catch(() => setMessage("保存済みのモデル・予測を確認できません。アプリを再起動してください。"));
  }, []);
  async function perform(task: () => Promise<void>): Promise<void> {
    onBusy(true); setMessage("");
    try { await task(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "計算・保存を完了できませんでした。"); }
    finally { onBusy(false); }
  }
  const five = new Map(run?.outputs.find(x => x.horizon === 5 && (x.task === "regression" || x.role === "return"))?.values ?? []);
  const twenty = new Map(run?.outputs.find(x => x.horizon === 20 && (x.task === "regression" || x.role === "return"))?.values ?? []);
  const ranking = new Map(run?.outputs.find(x => x.horizon === 20 && x.role === "ranking")?.values ?? []);
  const priority = ranking.size ? ranking : twenty;
  const available = [...priority.keys()];
  const holdings = new Set(run?.snapshot?.holding_symbols ?? []);
  const top = run?.snapshot?.candidate_symbols?.filter(symbol => priority.has(symbol))
    .sort((a, b) => priority.get(b)! - priority.get(a)! || a.localeCompare(b)).slice(0, 20);
  const symbols = top ? [...new Set([...top, ...[...holdings].sort()])].filter(symbol => available.includes(symbol)) : available.sort();
  const researchConsultation = decision?.blocking_reasons.length === 1 && decision.blocking_reasons[0] === "FORECAST_RISK_UNAVAILABLE";
  const bundleCount = (model?.approved_bundle_count ?? 0) + (model?.research_bundle_count ?? 0);
  return <section className="section model-panel" aria-label="端末内のモデルと予測">
    <h2>モデルと計算</h2>
    <p>確認済みの一式：{bundleCount}件／端末へ取込済み：{model?.imported_bundle_count ?? 0}件</p>
    <p>実運用の採用確認：{model?.model_adopted ? "確認済み" : "未完了・研究用"}</p>
    <details className="settings-disclosure"><summary>予測について</summary><p>5日・20日のモデルを一式で取り込みます。研究用の一式に含まれない下振れ・下落確率・校正情報は未提供です。</p></details>
    {!inputsSaved && <p>口座・保有の編集を保存してから予測を計算します。</p>}
    {model?.bundle_blocking_reason && <p>保存済みの一式を利用できません。確認済みのファイルを取り込んでください。</p>}
    <div className="button-stack">
      <button className="button button--secondary" disabled={disabled || !bundleCount} onClick={() => void perform(async () => {
        const content = await StockAI.importModel(); await apiPost("/api/v1/mobile/models/import", content);
        setModel(await apiGet("/api/v1/mobile/models")); setMessage("確認済みのモデル一式を保存しました。");
      })}>モデル一式を取り込む</button>
      <button className="button button--primary" disabled={disabled || !inputsSaved || !model?.bundle_ready} onClick={() => void perform(async () => {
        setDecision(null);
        const value = await apiPost<ForecastRun>("/api/v1/mobile/daily/generate", {}); setRun(value);
        const shares = await apiPost<DecisionRun>("/api/v1/mobile/decision/generate", {}); setDecision(shares);
        setMessage(shares.is_active ? "当日の予測と株数の判定を保存しました。" : shares.blocking_reasons.length === 1 && shares.blocking_reasons[0] === "FORECAST_RISK_UNAVAILABLE" ? "研究用の予測を保存しました。ChatGPTへの相談で株数案を検討できます。" : "計算状況と不足項目を保存しました。");
      })}>{model?.return_only_research || model?.ensemble_research ? "当日の予測を計算・保存" : "当日の予測・株数を計算・保存"}</button>
    </div>
    <p role="status">{message}</p>
    {run && <div className="forecast-state">
      <p>判定時点：{timestamp(run.scope.as_of)}</p>
      <p>推奨株数：{researchConsultation ? "自動判定なし・ChatGPTで案を検討" : decision?.is_active ? (decision.outcome === "cash_only" ? "全現金維持・判定完了" : "保存済み・研究用") : decision?.phase === "computed" ? "保存の確定待ち" : decision ? "未完了・入力確認が必要" : "未作成"}</p>
      {decision?.is_active && <Link className="button button--secondary" to="/today">今日の判定を見る</Link>}
      {researchConsultation && <Link className="button button--secondary" to="/today/chatgpt">予測を使ってChatGPTへ相談する</Link>}
      {decision?.phase === "published" && !decision.is_active && <p>保存後に入力や計算対象が変わっています。最新の条件を確認して再実行してください。</p>}
      {decision?.phase === "computed" && <p>株数の保存が途中です。同じ計算を実行すると保存を再開します。</p>}
      {decision && decision.blocking_reasons.length > 0 && <ul>{decision.blocking_reasons.map(code => <li key={code}>{reason(code)}</li>)}</ul>}
      {run.outcome === "cash_only" && <p>対象銘柄と保有がないため、銘柄の数値予測はありません。</p>}
      {run.phase === "computed" && <p>保存の確定を確認できません。同じ計算を実行すると保存を再開します。</p>}
      {run.blocking_reasons.length > 0 && <ul>{run.blocking_reasons.map(code => <li key={code}>{reason(code)}</li>)}</ul>}
      <details><summary>計算時刻・参照情報</summary>
        <p>確認：{timestamp(run.checked_at)}</p>
        <p>この予測の対象方式：{run.scope.universe?.policy === "jquants-scalecat-topix500-v1" ? "TOPIX500" : run.scope.universe?.policy?.startsWith("cap30bn-adv20-top300-") ? "従来300" : "記録を確認してください"}</p>
        <p>最終株価日：{run.scope.universe?.latest_source_date ?? "未確認"}</p>
        {run.snapshot && <><p>数値生成：{timestamp(run.snapshot.generated_at)}</p><p>参照情報の受領：{timestamp(run.snapshot.data_as_of)}</p></>}
        {decision && <p>株数判定の生成：{timestamp(decision.checked_at)}</p>}
      </details>
      {run.excluded_candidates.length > 0 && <details><summary>履歴不足で予測を見送った候補 {run.excluded_candidates.length}社</summary>
        <p>{run.excluded_candidates.map(x => x.symbol).join("、")}</p></details>}
      {symbols.length > 0 && <details><summary>{top ? "上位20と全保有の予測を見る" : "算出できた予測を見る"} {symbols.length}社</summary>
        {ranking.size > 0 && <p>順位スコアは期待リターン率ではありません。20日の順位で表示します。</p>}
        <table><thead><tr><th>銘柄</th>{ranking.size > 0 && <th>20日順位スコア</th>}<th>5日リターン</th><th>20日リターン</th></tr></thead><tbody>{symbols.map(symbol => <tr key={symbol}>
          <td><Link to={`/stocks/${symbol}`}>{symbol}</Link>{holdings.has(symbol) && "（保有）"}</td>{ranking.size > 0 && <td>{ranking.get(symbol)?.toFixed(4) ?? "未提供"}</td>}<td>{percent(five.get(symbol))}</td><td>{percent(twenty.get(symbol))}</td></tr>)}</tbody></table>
      </details>}
    </div>}
  </section>;
}

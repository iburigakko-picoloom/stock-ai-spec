import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { isAndroid, StockAI } from "./native";
import { visibleReads } from "./visibleReads";
import { AnalysisProgress } from "./AnalysisProgress";
import { ReferenceAnalysis } from "./ReferenceAnalysis";
import { Field, KV } from "../Adopted";

interface ModelStatus {
  approved_bundle_count: number; imported_bundle_count: number; bundle_ready: boolean;
  model_adopted: boolean; bundle_blocking_reason?: string | null;
  research_bundle_count?: number; return_only_research?: boolean; ensemble_research?: boolean; risk_available?: boolean;
}
interface ForecastRun {
  manual_decision?: DecisionRun;
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
  return messages[code] ?? `処理を完了できませんでした。診断コード：${code}`;
}
const percent = (value: number | undefined): string => value === undefined ? "未提供" : new Intl.NumberFormat("ja-JP", { style: "percent", maximumFractionDigits: 2 }).format(value);
const clock = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short" });
function timestamp(value: string): ReactNode {
  const date = new Date(value);
  return <time dateTime={value} title={value}>{Number.isNaN(date.valueOf()) ? "未確認" : clock.format(date)}</time>;
}

export function MobileModelPanel({ disabled, inputsSaved, inputStatus, onBusy }: {
  disabled: boolean; inputsSaved: boolean; inputStatus?: string; onBusy: (value: boolean) => void;
}): ReactNode {
  const [model, setModel] = useState<ModelStatus | null>(null);
  const [run, setRun] = useState<ForecastRun | null>(null);
  const [decision, setDecision] = useState<DecisionRun | null>(null);
  const [modelReady, setModelReady] = useState(false);
  const [runReady, setRunReady] = useState(false);
  const [decisionReady, setDecisionReady] = useState(false);
  const [readError, setReadError] = useState(false);
  const modelRevision = useRef(0);
  const [message, setMessage] = useState("");
  const [calculating, setCalculating] = useState(false);
  const [referenceSaved, setReferenceSaved] = useState(false);
  useEffect(() => {
    let active = true;
    setModelReady(false); setRunReady(false); setDecisionReady(false); setReadError(false);
    const revision = modelRevision.current;
    const status = () => apiGet<ModelStatus>("/api/v1/mobile/models").then(value => {
      if (active && revision === modelRevision.current) { setModel(value); setModelReady(true); }
    });
    const saved = () => apiGet<ForecastRun | null>("/api/v1/mobile/daily").then(value => { if (active) { setRun(value); setRunReady(true); } });
    const shares = () => apiGet<DecisionRun | null>("/api/v1/mobile/decision").then(value => { if (active) { setDecision(value); setDecisionReady(true); } });
    void visibleReads([status, saved, shares], () => active, isAndroid(), () => setReadError(true));
    return () => { active = false; };
  }, []);
  const initialReady = modelReady && runReady && decisionReady && !readError;
  async function perform(task: () => Promise<void>): Promise<void> {
    onBusy(true); setMessage("");
    try { await task(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "計算・保存を完了できませんでした。"); }
    finally { setCalculating(false); onBusy(false); }
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
  const currentDecision = runReady && decisionReady ? decision : null;
  const researchConsultation = currentDecision?.blocking_reasons.length === 1 && currentDecision.blocking_reasons[0] === "FORECAST_RISK_UNAVAILABLE";
  const blockingMessages = [...new Set([...(runReady ? run?.blocking_reasons ?? [] : []), ...(currentDecision?.blocking_reasons ?? [])].map(reason))];
  return <div className="subscreen advanced-domain stack model-panel" aria-label="端末内のモデルと予測">
    <section className="card"><h3 className="section-title">1. 採用モデル</h3>
    <KV label="モデルファイル" value={modelReady && model ? `${model.imported_bundle_count}件取込済み` : readError ? "未確認" : "モデルを確認中…"} />
    <KV label="状態" value={!modelReady || !model ? readError ? "未確認" : "確認中" : model.model_adopted ? "採用確認済み" : "研究用・正式採用前"} />
    {!inputsSaved && <p>{inputStatus ?? "口座・保有の編集を保存してから予測を計算します。"}</p>}
    {modelReady && model?.bundle_blocking_reason && <p>保存済みの一式を利用できません。確認済みのファイルを取り込んでください。</p>}
    <Field label="予測期間"><input className="input" readOnly value="5日・20日" /></Field></section>
    <section className="card"><h3 className="section-title">2. モデル取り込み</h3><div className="button-stack">
      <button className="button button--secondary" disabled={disabled} onClick={() => void perform(async () => {
        const content = await StockAI.importModel(); await apiPost("/api/v1/mobile/models/import", content); modelRevision.current++; setModelReady(false);
        setModel(await apiGet("/api/v1/mobile/models")); setModelReady(true); setMessage("確認済みのモデル一式を保存しました。");
      })}>モデル一式を取り込む</button></div></section>
    <section className="card"><h3 className="section-title">3. 予測・株数</h3><div className="button-stack">
      <button className="button button--primary" disabled={disabled || !initialReady || !inputsSaved || !model?.bundle_ready} onClick={() => void perform(async () => {
        setCalculating(true);
        setDecision(null);
        const value = await apiPost<ForecastRun>("/api/v1/mobile/daily/generate", {}); setRun(value);
        const shares = value.manual_decision ?? await apiPost<DecisionRun>("/api/v1/mobile/decision/generate", {}); setDecision(shares);
        setMessage(shares.is_active ? "当日の予測と株数の判定を保存しました。" : shares.blocking_reasons.length === 1 && shares.blocking_reasons[0] === "FORECAST_RISK_UNAVAILABLE" ? "研究用の予測を保存しました。ChatGPTへの相談で株数案を検討できます。" : value.phase === "published" && value.snapshot ? "予測は保存済みです。株数の判定は未完了です。" : "予測は未完了です。下の理由を確認してください。");
      })}>{modelReady && (model?.return_only_research || model?.ensemble_research) ? "当日の予測を計算・保存" : "当日の予測・株数を計算・保存"}</button>
    </div>
    <AnalysisProgress busy={calculating} />
    <p role="status">{message}</p>
    {readError && <p role="alert">保存済みのモデル・予測を確認できません。アプリを再起動してください。</p>}
    {run?.blocking_reasons.some(code => ["PERSONAL_INPUT_AFTER_ALPHA_CUTOFF", "LEDGER_RECEIVED_AFTER_ALPHA_CUTOFF", "ALPHA_CUTOFF_OPEN", "UNIVERSE_NON_BUSINESS_DAY"].includes(code)) &&
      <ReferenceAnalysis hasSaved={referenceSaved} disabled={disabled || calculating || !initialReady} onBusy={onBusy} onSaved={() => setReferenceSaved(true)} />}
    {referenceSaved && <Link className="button button--secondary" to="/ranking">保存したランキングを見る</Link>}
    {run && <section className="forecast-state"><h3 className="plain-section-title">計算結果</h3>
      {!runReady && <p role="status">前回の表示・閲覧用。更新を確認中…</p>}
      <p>当日予測の記録：{timestamp(run.scope.as_of)}</p>
      <p>推奨株数：{!runReady || !decisionReady ? readError ? "未確認" : "確認中" : researchConsultation ? "自動判定なし・ChatGPTで案を検討" : currentDecision?.is_active ? (currentDecision.outcome === "cash_only" ? "全現金維持・判定完了" : "保存済み・研究用") : currentDecision?.phase === "computed" ? "保存の確定待ち" : currentDecision ? "未完了・入力確認が必要" : "未作成"}</p>
      {currentDecision?.is_active && <Link className="button button--secondary" to="/today">今日の判定を見る</Link>}
      {researchConsultation && <Link className="button button--secondary" to="/today/chatgpt">予測を使ってChatGPTへ相談する</Link>}
      {currentDecision?.phase === "published" && !currentDecision.is_active && <p>保存後に入力や計算対象が変わっています。最新の条件を確認して再実行してください。</p>}
      {currentDecision?.phase === "computed" && <p>株数の保存が途中です。同じ計算を実行すると保存を再開します。</p>}
      {run.outcome === "cash_only" && <p>対象銘柄と保有がないため、銘柄の数値予測はありません。</p>}
      {run.phase === "computed" && <p>保存の確定を確認できません。同じ計算を実行すると保存を再開します。</p>}
      {blockingMessages.length > 0 && <ul>{blockingMessages.map(message => <li key={message}>{message}</li>)}</ul>}
      <section><h3 className="plain-section-title">計算時刻・参照情報</h3>
        <p>確認：{timestamp(run.checked_at)}</p>
        <p>この予測の対象方式：{run.scope.universe?.policy === "jquants-scalecat-topix500-v1" ? "TOPIX500" : run.scope.universe?.policy?.startsWith("cap30bn-adv20-top300-") ? "従来300" : "記録を確認してください"}</p>
        <p>最終株価日：{run.scope.universe?.latest_source_date ?? "未確認"}</p>
        {run.snapshot && <><p>数値生成：{timestamp(run.snapshot.generated_at)}</p><p>参照情報の受領：{timestamp(run.snapshot.data_as_of)}</p></>}
        {currentDecision && <p>株数判定の生成：{timestamp(currentDecision.checked_at)}</p>}
      </section>

      {symbols.length > 0 && <section><h3 className="plain-section-title">{top ? "上位20と全保有の予測を見る" : "算出できた予測を見る"} {symbols.length}社</h3>
        {ranking.size > 0 && <p>順位スコアは期待リターン率ではありません。20日の順位で表示します。</p>}
        <table><thead><tr><th>銘柄</th>{ranking.size > 0 && <th>20日順位スコア</th>}<th>5日リターン</th><th>20日リターン</th></tr></thead><tbody>{symbols.map(symbol => <tr key={symbol}>
          <td><Link to={`/stocks/${symbol}`}>{symbol}</Link>{holdings.has(symbol) && "（保有）"}</td>{ranking.size > 0 && <td>{ranking.get(symbol)?.toFixed(4) ?? "未提供"}</td>}<td>{percent(five.get(symbol))}</td><td>{percent(twenty.get(symbol))}</td></tr>)}</tbody></table>
      </section>}
    </section>}</section>
    <section className="card"><h3 className="section-title">4. 除外銘柄</h3>{!run ? <p className="setting-footnote">{runReady ? "計算後に表示します。" : readError ? "計算結果を確認できません。" : "計算結果を確認中…"}</p> : run.excluded_candidates.length ? <table className="subtable"><thead><tr><th>銘柄</th><th>理由</th></tr></thead><tbody>{run.excluded_candidates.map(row=><tr key={row.symbol}><td>{row.symbol}</td><td>{reason(row.reason)}</td></tr>)}</tbody></table> : <p className="setting-footnote">保存された計算に除外銘柄はありません。</p>}<Link className="quiet-link" to="/settings?edit=repair">履歴を修復</Link></section>
  </div>;
}

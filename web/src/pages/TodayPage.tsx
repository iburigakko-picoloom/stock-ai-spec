import { type ReactNode, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ActionBadge, Metric, PageHeader, RuntimeBanner, StatePanel, dateTime, yen } from "../components";
import { useApiData } from "../hooks";
import type { ProposalLine, SavedAnalysis, TodayResponse } from "../types";
import { DailyPanel, DailyStatusLink } from "../mobile/DailyPanel";
import { TabBar } from "../components";
import { apiGet } from "../api";
import type { ConsultationFindings } from "../ConsultationReport";

interface ConsultationView {
  lines: { symbol: string; account: string; current_shares: number; target_shares: number }[];
  estimated_cost_yen: string; estimated_cash_after: Record<string,string>;
}

function MarketOutlook({ findings }: { findings: ConsultationFindings | null }) {
  return <section className="today-market" aria-label="市場の見通し">
    <div className="link-row"><strong>市場の見通し</strong><small>ChatGPT{findings ? "・保存済み" : "・未相談"}</small></div>
    <p>5日 <strong>{findings?.market_5d || "未確認"}</strong> ／ 20日 <strong>{findings?.market_20d || "未確認"}</strong></p>
    <div className="link-row"><small>{findings ? `出典 ${findings.sources?.length ?? 0}件` : "相談結果を保存すると表示します"}</small><Link className="quiet-link" to="/today/chatgpt/history">相談履歴 ›</Link></div>
  </section>;
}
import { ProposalReadiness, proposalBlockLabel } from "../mobile/ProposalReadiness";
import { isAndroid } from "../mobile/native";
import { ReferenceAnalysis } from "../mobile/ReferenceAnalysis";

const priority = new Map([
  ["SELL", 0],
  ["REDUCE", 1],
  ["BUY", 2],
  ["HOLD", 3],
  ["SKIP", 4],
]);

function ProposalRow({ line }: { line: ProposalLine }): ReactNode {
  return (
    <Link className="proposal-row" state={{ from: "/today" }} to={`/stocks/${line.symbol}`}>
      <ActionBadge action={line.action} />
      <div className="proposal-row__body">
        <strong>{line.companyName}</strong>
        <span>{line.symbol} ・ {line.accountBucketId}</span>
      </div>
      <div className="proposal-row__shares">
        <strong>{line.currentShares.toLocaleString("ja-JP")}株 <span aria-label="から">→</span> {line.recommendedShares.toLocaleString("ja-JP")}株</strong>
        <span className={line.shareDifference > 0 ? "text-positive" : line.shareDifference < 0 ? "text-negative" : undefined}>{line.shareDifference === 0 ? "変更なし" : `${line.shareDifference > 0 ? "+" : ""}${line.shareDifference.toLocaleString("ja-JP")}株`}</span>
      </div>
    </Link>
  );
}

function SavedAnalysisPanel({ analysis }: { analysis: SavedAnalysis }): ReactNode {
  const percent = (value: number | null) => value === null ? "—" : `${(value * 100).toFixed(2)}%`;
  const dated = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", year: "numeric", month: "numeric", day: "numeric" }).format(new Date(analysis.asOf));
  const ranked = analysis.predictions.some(row => row.rank_score_20d != null);
  return <section className="section saved-analysis" aria-label="保存済み分析">
    <h2>{analysis.analysisKind === "latest_available_reference" ? `${analysis.priceDate}の終値によるランキング` : `${dated}の分析`}</h2>
    <p>{analysis.analysisKind === "latest_available_reference" ? "株価日を確認し、ランキングからChatGPTに相談できます。" : "保存済み・閲覧用。当日の更新が完了すると切り替わります。"}</p>
    <Link className="button button--secondary" to="/ranking">ランキングを見る・相談する</Link>
    {!isAndroid() && <table><thead><tr><th>銘柄</th>{ranked && <th>20日順位</th>}<th>5日予測</th><th>20日予測</th></tr></thead>
      <tbody>{analysis.predictions.map(row => <tr key={row.symbol}>
        <td>{row.symbol}{analysis.holdingSymbols.includes(row.symbol) && <small className="saved-analysis__holding">（保有）</small>}</td>
        {ranked && <td>{row.rank_score_20d?.toFixed(2) ?? "—"}</td>}
        <td>{percent(row.expected_return_5d)}</td><td>{percent(row.expected_return_20d)}</td>
      </tr>)}</tbody></table>}
    <p className="setting-footnote">作成 {dateTime(analysis.generatedAt)} JST</p>
  </section>;
}

export function TodayPage(): ReactNode {
  const detailed = useLocation().pathname === "/today/details";
  const [source, setSource] = useState("model");
  const [findings, setFindings] = useState<ConsultationFindings | null>(null);
  const [consultation, setConsultation] = useState<ConsultationView | null>(null);
  useEffect(() => {
    if (!isAndroid()) return;
    let active=true;
    void apiGet<{research?: {research?: ConsultationFindings}}>("/api/v1/mobile/ranking/20d").then(value=>{if(active) setFindings(value.research?.research ?? null);}).catch(()=>{});
    void apiGet<{answers: ConsultationView[]}>("/api/v1/mobile/chatgpt-manual/status").then(value=>{if(active) setConsultation(value.answers[0] ?? null);}).catch(()=>{});
    return ()=>{active=false;};
  }, []);
  const { data, error, loading, savedAt, reload } = useApiData<TodayResponse>("/api/v1/today");
  if ((loading && !data) || error || !data) return <div className="page"><PageHeader eyebrow="毎日の投資判断" title="今日" /><StatePanel tone={loading ? "neutral" : "error"} title={loading ? "今日の状態を確認しています" : "今日の提案を取得できません"} detail={error} /></div>;
  const previous = isAndroid() && (loading || !!savedAt);
  const proposal = (!previous && (loading || data.isStale)) ? null : data.proposal;
  const visible = proposal?.lines
    .filter((line) => line.action !== "SKIP" && line.action !== "HOLD")
    .sort((a, b) => (priority.get(a.action) ?? 9) - (priority.get(b.action) ?? 9));
  const holds = proposal?.lines.filter((line) => line.action === "HOLD") || [];
  const cashValues = Object.values(proposal?.estimatedCashAfter || {});
  const cashAfter = cashValues.length > 0 && cashValues.every((value) => value.trim() !== "" && Number.isFinite(Number(value)))
    ? cashValues.reduce((sum, value) => sum + Number(value), 0) : null;

  return <div className="page today-page">
    <PageHeader title={detailed ? "提案の計算詳細" : "今日"} backTo={detailed ? "/today" : undefined} actions={!detailed && <DailyStatusLink />} />
    {data.runtimeMode === "DETERMINISTIC_FIXTURE_ONLY" && <RuntimeBanner mode={data.runtimeMode} />}
    {previous && <p role="status" className="setting-footnote">前回の表示・閲覧用{savedAt ? `（${dateTime(savedAt, true)} JST）` : ""}。更新を確認中…</p>}
    {!detailed && <MarketOutlook findings={findings} />}
    {!detailed && <><h2>今日の提案</h2><TabBar label="提案元" options={[["model","数値モデル"],["chatgpt","ChatGPT"]]} value={source} onChange={setSource} panelId="today-source" /></>}
    <div id="today-source" role="tabpanel" aria-labelledby={`today-source-${source}`}>
    {source === "chatgpt" && !detailed ? <>
      {consultation ? <section className="mock-card"><h2>保存したChatGPT提案</h2>{consultation.lines.map(line=><Link className="proposal-row" to={`/stocks/${line.symbol}`} state={{from:"/today"}} key={`${line.symbol}:${line.account}`}><span className="action">{line.target_shares>line.current_shares ? "購入" : line.target_shares<line.current_shares ? "売却" : "継続"}</span><div className="proposal-row__body"><strong>{line.symbol}</strong><span>{line.account}</span></div><div className="proposal-row__shares"><strong>{line.current_shares} → {line.target_shares}</strong><span>株・保存時の提案</span></div></Link>)}<p className="setting-footnote">最新の資金・保有条件で検算してから判断してください。</p><Link className="button button--secondary" to="/today/chatgpt">最新条件で検算</Link></section> : <StatePanel title="保存したChatGPT提案はありません" detail="相談への回答を保存・検算すると、数値モデルの提案と分けて確認できます。" />}
    </> : !loading && !data.isStale && data.pipelineState === "CASH_ONLY" ? <StatePanel title="分析完了・全現金維持" detail="対象銘柄と保有がないため、今日は株数の変更がありません。" /> : !proposal ? <>
      {((loading && !data.savedAnalysis) || !isAndroid()) && <StatePanel tone={data.isStale ? "warning" : "neutral"} title={data.savedAnalysis ? "保存済みの分析を表示しています" : "今日の提案をまだ表示できません"} detail={loading ? "更新状況を確認中…" : proposalBlockLabel(data.blockingReason)} />}
      {data.savedAnalysis && <SavedAnalysisPanel analysis={data.savedAnalysis} />}
      {!loading && <ReferenceAnalysis onSaved={reload} hasSaved={!!data.savedAnalysis} />}
      {!loading && !data.savedAnalysis && <ProposalReadiness reason={data.blockingReason} />}
      <Link className="quiet-link" to="/settings?edit=market">データの更新状況を確認</Link>
      {detailed && <DailyPanel />}
    </> : <>
      {!detailed && <section className="mock-card" aria-label="株数の変更">
        {visible && visible.length>0 ? visible.map(line=><ProposalRow key={line.lineId} line={line} />) : <StatePanel title="今日は株数変更なし" detail={proposal.noTradeReason || "HOLD比較後の純改善が基準に届きませんでした。"} />}
        {holds.length>0 && <section className="hold-section"><h3>保有継続 {holds.length}銘柄</h3>{holds.map(line=><ProposalRow key={line.lineId} line={line} />)}</section>}
      </section>}
      <section className={detailed ? "section" : "mock-card today-summary"} aria-label="提案サマリー"><h2>提案サマリー</h2>
        <div className="metric-grid metric-grid--2"><Metric label="推定購入額" value={yen(proposal.estimatedBuyValue)} /><Metric label="推定売却額" value={yen(proposal.estimatedSellValue)} /></div>
        <div className="summary-total"><span>取引後の推定現金</span><strong>{yen(cashAfter)}</strong></div>
        <p className="setting-footnote">費用 {yen(proposal.estimatedTransactionCost)} · 税 {yen(proposal.estimatedTaxEffect)}（推定） · {dateTime(proposal.asOf)} JST{proposal.isResearchOnly && " · 研究用"}</p>
      </section>
      {!detailed && !previous && <Link className="button button--primary" to="/today/review">判断を確認</Link>}
      {detailed && <><section className="section"><h2>口座別の現金・推定改善</h2><dl className="summary-list">
        {Object.entries(proposal.estimatedCashAfter).map(([bucket,cash])=><div key={bucket}><dt>{bucket}</dt><dd>{yen(cash)}</dd></div>)}
        <div><dt>推定取引コスト</dt><dd>{yen(proposal.estimatedTransactionCost)}</dd></div><div><dt>推定税影響</dt><dd>{yen(proposal.estimatedTaxEffect)}</dd></div>
        <div><dt>売却時の源泉徴収見込み</dt><dd>{yen(proposal.estimatedTaxCashWithholding)}</dd></div><div><dt>何もしない場合に対する推定純改善</dt><dd className={Number(proposal.netImprovement)<0 ? "text-negative" : undefined}>{yen(proposal.netImprovement)}</dd></div>
      </dl><p className="explain">税影響と源泉徴収見込みは別の推定です。提案後の現金には源泉徴収見込みを反映しています。</p></section>
      <section className="section"><h2>提案の基準時刻・モデル詳細</h2><dl className="summary-list"><div><dt>基準時刻</dt><dd>{dateTime(proposal.asOf)} JST</dd></div><div><dt>モデル</dt><dd>{proposal.modelBundleVersion}</dd></div><div><dt>意思決定エンジン</dt><dd>{proposal.decisionEngineVersion}</dd></div></dl></section></>}
    </>}
    </div>
    {!detailed && <><div className="two-actions"><Link className="button button--secondary" to="/today/chatgpt">ChatGPTに相談 ↗</Link><Link className="button button--secondary" to="/today/executions">取引を記録 ＋</Link></div><div className="link-row"><Link className="quiet-link" to="/today/chatgpt/history">相談履歴を見る</Link><Link className="quiet-link" to="/today/details">提案の計算詳細</Link></div></>}
  </div>;
}

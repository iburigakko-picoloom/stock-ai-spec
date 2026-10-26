import { type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { PageHeader, RuntimeBanner, StatePanel, dateTime, currency as yen } from "../components";
import { useApiData } from "../hooks";
import type { ProposalLine, SavedAnalysis, TodayResponse } from "../types";
import { DailyPanel, DailyStatusLink } from "../mobile/DailyPanel";

function MarketOutlook() {
  return <section className="today-market" aria-label="市場の見通し">
    <b>市場の見通し</b><p>市場全体と保有株・候補の分析は、ChatGPTの会話で確認できます。</p>
    <Link className="button ghost" to="/today/chatgpt">ChatGPTに相談 ↗</Link>
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
    <div className="today-change">
      <span className={`today-side ${line.shareDifference>0 ? "today-buy" : "today-sell"}`}>{line.shareDifference>0 ? "購入" : "売却"}</span>
      <Link className="today-stock" state={{ from: "/today" }} to={`/stocks/${line.symbol}`}>
        <strong>{line.companyName}</strong>
        <small>{line.positiveReasons[0] || `${line.symbol} ・ ${line.accountBucketId}`}</small>
      </Link>
      <div className="today-num">
        {line.currentShares.toLocaleString("ja-JP")} → {line.recommendedShares.toLocaleString("ja-JP")}<small>株・提案</small>
      </div>
    </div>
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
    <div className="screen-today">
    {data.runtimeMode === "DETERMINISTIC_FIXTURE_ONLY" && <RuntimeBanner mode={data.runtimeMode} />}
    {previous && <p role="status" className="setting-footnote">前回の表示・閲覧用{savedAt ? `（${dateTime(savedAt, true)} JST）` : ""}。更新を確認中…</p>}
    {!detailed && <MarketOutlook />}
    {!detailed && <div className="today-heading"><h3>今日の提案</h3></div>}
    <div id="today-source">
    {!loading && !data.isStale && data.pipelineState === "CASH_ONLY" ? <StatePanel title="分析完了・全現金維持" detail="対象銘柄と保有がないため、今日は株数の変更がありません。" /> : !proposal ? <>
      {((loading && !data.savedAnalysis) || !isAndroid()) && <StatePanel tone={data.isStale ? "warning" : "neutral"} title={data.savedAnalysis ? "保存済みの分析を表示しています" : "今日の提案をまだ表示できません"} detail={loading ? "更新状況を確認中…" : proposalBlockLabel(data.blockingReason)} />}
      {data.savedAnalysis && <SavedAnalysisPanel analysis={data.savedAnalysis} />}
      {!loading && <ReferenceAnalysis onSaved={reload} hasSaved={!!data.savedAnalysis} />}
      {!loading && !data.savedAnalysis && <ProposalReadiness reason={data.blockingReason} />}
      <Link className="quiet-link" to="/settings?edit=market">データの更新状況を確認</Link>
      {detailed && <DailyPanel />}
    </> : <>
      {!detailed && <section className="card" style={{marginTop:12}} aria-label="株数の変更">
        {visible && visible.length>0 ? visible.map(line=><ProposalRow key={line.lineId} line={line} />) : <StatePanel title="今日は株数変更なし" detail={proposal.noTradeReason || "HOLD比較後の純改善が基準に届きませんでした。"} />}
        {holds.length>0 && <section><h3 className="small">保有継続 {holds.length}銘柄</h3><div className="today-detail">{holds.map(line=><div className="row spread" style={{padding:"8px 0"}} key={line.lineId}><Link className="today-stock" to={`/stocks/${line.symbol}`} state={{from:"/today"}}><strong>{line.companyName}</strong></Link><span>{line.currentShares}株を継続</span></div>)}</div></section>}
      </section>}
      <section className="card" style={{marginTop:12}} aria-label="提案サマリー"><div className="today-narrow-title">提案サマリー</div>
        <div className="today-finance"><div><span>推定購入額</span><b>{yen(proposal.estimatedBuyValue)}</b></div><div><span>推定売却額</span><b>{yen(proposal.estimatedSellValue)}</b></div><div className="wide"><span>取引後の推定現金</span><b>{yen(cashAfter)}</b></div></div>
        <div className="today-caption">費用 {yen(proposal.estimatedTransactionCost)} · 税 {yen(proposal.estimatedTaxEffect)}（推定） · {dateTime(proposal.asOf)} JST{proposal.isResearchOnly && " · 研究用"}</div>
      </section>
      {detailed && <><section className="section"><h2>口座別の現金・推定改善</h2><dl className="summary-list">
        {Object.entries(proposal.estimatedCashAfter).map(([bucket,cash])=><div key={bucket}><dt>{bucket}</dt><dd>{yen(cash)}</dd></div>)}
        <div><dt>推定取引コスト</dt><dd>{yen(proposal.estimatedTransactionCost)}</dd></div><div><dt>推定税影響</dt><dd>{yen(proposal.estimatedTaxEffect)}</dd></div>
        <div><dt>売却時の源泉徴収見込み</dt><dd>{yen(proposal.estimatedTaxCashWithholding)}</dd></div><div><dt>何もしない場合に対する推定純改善</dt><dd className={Number(proposal.netImprovement)<0 ? "text-negative" : undefined}>{yen(proposal.netImprovement)}</dd></div>
      </dl><p className="explain">税影響と源泉徴収見込みは別の推定です。提案後の現金には源泉徴収見込みを反映しています。</p></section>
      <section className="section"><h2>提案の基準時刻・モデル詳細</h2><dl className="summary-list"><div><dt>基準時刻</dt><dd>{dateTime(proposal.asOf)} JST</dd></div><div><dt>モデル</dt><dd>{proposal.modelBundleVersion}</dd></div><div><dt>意思決定エンジン</dt><dd>{proposal.decisionEngineVersion}</dd></div></dl></section></>}
    </>}
    </div>
    {!detailed && <div className="today-actions">{proposal && !previous && <Link className="button" to="/today/review">判断を確認</Link>}<div className="today-taskbar"><Link to="/today/chatgpt">ChatGPTに相談 ↗</Link><Link to="/today/executions">取引を記録 ＋</Link></div><Link className="quiet-link" to="/today/chatgpt/history">保存済み記録（閲覧のみ）</Link><Link className="quiet-link" to="/today/details">提案の計算詳細</Link></div>}
    </div>
  </div>;
}

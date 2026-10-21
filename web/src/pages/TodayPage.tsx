import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ActionBadge, Metric, PageHeader, RuntimeBanner, StatePanel, dateTime, yen } from "../components";
import { useApiData } from "../hooks";
import type { ProposalLine, TodayResponse } from "../types";
import { DailyPanel } from "../mobile/DailyPanel";

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

export function TodayPage(): ReactNode {
  const { data, error, loading } = useApiData<TodayResponse>("/api/v1/today");
  if (loading || error || !data) return <div className="page"><PageHeader eyebrow="毎日の投資判断" title="今日" /><StatePanel tone={loading ? "neutral" : "error"} title={loading ? "今日の状態を確認しています" : "今日の提案を取得できません"} detail={error} /></div>;
  const proposal = data.isStale ? null : data.proposal;
  const visible = proposal?.lines
    .filter((line) => line.action !== "SKIP" && line.action !== "HOLD")
    .sort((a, b) => (priority.get(a.action) ?? 9) - (priority.get(b.action) ?? 9));
  const holds = proposal?.lines.filter((line) => line.action === "HOLD") || [];
  const cashValues = Object.values(proposal?.estimatedCashAfter || {});
  const cashAfter = cashValues.length > 0 && cashValues.every((value) => value.trim() !== "" && Number.isFinite(Number(value)))
    ? cashValues.reduce((sum, value) => sum + Number(value), 0) : null;

  return (
    <div className="page">
      <PageHeader eyebrow={data.businessDate} title="今日" meta={proposal ? `更新 ${dateTime(proposal.generatedAt)} JST` : undefined} actions={<Link className="button button--secondary consultation-link" to="/today/chatgpt"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M4 18 3 22l5-2a9 9 0 1 0-4-2Z" /></svg>ChatGPTと相談</Link>} />
      <RuntimeBanner mode={data.runtimeMode} />
      <DailyPanel />
      {!data.isStale && data.pipelineState === "CASH_ONLY" ? (
        <StatePanel title="分析完了・全現金維持" detail="対象銘柄と保有がないため、今日は株数の変更がありません。" />
      ) : !proposal ? (
        <><StatePanel
          tone={data.isStale ? "warning" : "neutral"}
          title={data.isStale ? "今日は提案を表示できません" : "次回の分析を待っています"}
          detail={data.blockingReason || "データとモデルの準備が整い、当日の分析が完了すると提案を表示します。"}
        /><Link className="button button--secondary" to="/settings/data">データの更新状況を確認</Link></>
      ) : (
        <>
          <section className="proposal-hero" aria-label="今日の提案概要">
            <div><span>今日の変更</span><strong>{proposal.changeCount}<small>件</small></strong></div>
            <span className="status-pill">{proposal.isResearchOnly ? "研究用の提案" : "提案を確認できます"}</span>
          </section>
          <section className="section">
            <div className="section-title"><div><span>TODAY'S ACTIONS</span><h2>株数の変更</h2></div><small>現在 → 提案</small></div>
            {visible && visible.length > 0 ? visible.map((line) => <ProposalRow key={line.lineId} line={line} />) : (
              <StatePanel title="今日は株数変更なし" detail={proposal.noTradeReason || "HOLD比較後の純改善が基準に届きませんでした。"} />
            )}
            {holds.length > 0 && (
              <details className="hold-section">
                <summary>HOLD {holds.length}件を確認</summary>
                {holds.map((line) => <ProposalRow key={line.lineId} line={line} />)}
              </details>
            )}
          </section>
          <section className="section summary-panel">
            <div className="section-title"><div><span>ESTIMATE</span><h2>提案サマリー</h2></div></div>
            <div className="metric-grid metric-grid--2">
              <Metric label="推定売却額" value={yen(proposal.estimatedSellValue)} />
              <Metric label="推定購入額" value={yen(proposal.estimatedBuyValue)} />
              <Metric label="推定取引コスト" value={yen(proposal.estimatedTransactionCost)} />
              <Metric label="推定税影響" value={yen(proposal.estimatedTaxEffect)} />
            </div>
            <div className="summary-total"><span>取引後の推定現金（合計）</span><strong>{yen(cashAfter)}</strong></div>
            <details className="metadata-details"><summary>口座別の現金・推定改善を確認</summary>
              <dl className="summary-list">
                {Object.entries(proposal.estimatedCashAfter).map(([bucket, cash]) => <div key={bucket}><dt>{bucket}</dt><dd>{yen(cash)}</dd></div>)}
                <div><dt>売却時の源泉徴収見込み</dt><dd>{yen(proposal.estimatedTaxCashWithholding)}</dd></div>
                <div><dt>何もしない場合に対する推定純改善</dt><dd className={Number(proposal.netImprovement) < 0 ? "text-negative" : undefined}>{yen(proposal.netImprovement)}</dd></div>
              </dl>
              <p className="explain">税影響と源泉徴収見込みは別の推定です。提案後の現金には源泉徴収見込みを反映しています。</p>
              <p className="explain">推定値です。将来の利益や実際の約定価格を保証しません。</p>
            </details>
            <Link className="button button--primary summary-review-link" to="/today/review">判断を確認<span aria-hidden="true">›</span></Link>
            <p className="explain">保存しても証券会社への注文は行われません</p>
          </section>
          <details className="metadata-details proposal-metadata"><summary>提案の基準時刻・モデル詳細</summary>
            <dl className="summary-list">
              <div><dt>基準時刻</dt><dd>{dateTime(proposal.asOf)} JST</dd></div>
              <div><dt>モデル</dt><dd>{proposal.modelBundleVersion}</dd></div>
              <div><dt>意思決定エンジン</dt><dd>{proposal.decisionEngineVersion}</dd></div>
            </dl>
          </details>
        </>
      )}
    </div>
  );
}

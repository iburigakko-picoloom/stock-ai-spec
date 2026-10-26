import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, apiGet, apiPost } from "../api";
import { ActionBadge, PageHeader, StatePanel, yen } from "../components";
import { useApiData } from "../hooks";
import type { DecisionReview, TodayResponse } from "../types";

interface SavedDecision {
  version: number;
}

export function DecisionReviewPage(): ReactNode {
  const [savedKey, setSavedKey] = useState<string | null>(null);
  const { data, error, loading } = useApiData<TodayResponse>("/api/v1/today");
  const [targets, setTargets] = useState<Record<string, number>>({});
  const [reviewState, setReview] = useState<{ key: string; value: DecisionReview } | null>(null);
  const [draftProposal, setDraftProposal] = useState("");
  const flight = useRef(false);
  const attempt = useRef<{ key: string; path: string; body: unknown } | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const proposal = data?.isStale ? null : data?.proposal;

  const proposalKey = proposal ? JSON.stringify([proposal.proposalId,
    proposal.lines.map(line => [line.lineId, line.recommendedShares]).sort()]) : "";
  const targetKey = JSON.stringify([proposalKey, Object.entries(targets).sort(([a], [b]) => a.localeCompare(b))]);
  const review = reviewState?.key === targetKey && draftProposal === proposalKey ? reviewState.value : null;
  useEffect(() => {
    if (!proposalKey) { setReview(null); return; }
    const [, lines] = JSON.parse(proposalKey) as [string, [string, number][]];
    setDraftProposal(proposalKey); setReview(null); attempt.current = null;
    setTargets(Object.fromEntries(lines));
  }, [proposalKey]);

  useEffect(() => {
    if (!proposalKey || draftProposal !== proposalKey) return;
    const [id, lines] = JSON.parse(proposalKey) as [string, [string, number][]];
    const [, entries] = JSON.parse(targetKey) as [string, [string, number][]];
    if (entries.length !== lines.length || lines.some(([key]) => !entries.some(([entry]) => key === entry))) return;
    let active = true;
    setReview(null); setReviewError(null);
    void apiPost<DecisionReview>(`/api/v1/proposals/${id}/review`, { selectedTargets: Object.fromEntries(entries) })
      .then(value => { if (active) setReview({ key: targetKey, value }); })
      .catch((reason: unknown) => {
        if (active) setReviewError(reason instanceof Error ? reason.message : "再計算に失敗しました");
      });
    return () => { active = false; };
  }, [proposalKey, draftProposal, targetKey]);

  if (loading || error || !proposal) return <div className="page"><Link className="back-link" to="/today">← 今日へ戻る</Link><PageHeader title="判断を確認" /><StatePanel tone={loading ? "neutral" : error ? "error" : "warning"} title={loading ? "判断内容を準備しています" : error ? "提案を取得できません" : "有効な当日提案がありません"} detail={error || data?.blockingReason} /></div>;

  async function save(): Promise<void> {
    if (flight.current || !proposal || !review || review.constraint_violations.length > 0) return;
    flight.current = true;
    setSaving(true);
    setReviewError(null);
    try {
      if (!attempt.current || attempt.current.key !== targetKey) {
      const existing = await apiGet<SavedDecision | null>(`/api/v1/proposals/${proposal.proposalId}/decision`);
      attempt.current = { key: targetKey, path: `/api/v1/proposals/${proposal.proposalId}/decisions`, body: {
        decisionId: `decision-${crypto.randomUUID()}`,
        version: (existing?.version || 0) + 1,
        savedAt: new Date().toISOString(),
        confirmsManualOrderOnly: true,
        lines: proposal.lines.map((line) => ({
          proposalLineId: line.lineId,
          selectedTargetShares: targets[line.lineId],
        })),
      } };
      }
      await apiPost(attempt.current.path, attempt.current.body);
      attempt.current = null;
      setSavedKey(targetKey);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) { attempt.current = null; setReview(null); }
      setReviewError(reason instanceof Error ? reason.message : "判断を保存できませんでした");
    } finally {
      flight.current = false; setSaving(false);
    }
  }

  return (
    <div className="page page--with-sticky">
      <PageHeader title="判断を確認" backTo="/today" />
      {savedKey === targetKey && <section role="status" className="save-result"><h2>判断を保存しました</h2><p>保有・現金は変更していません。</p><Link className="button button--secondary" to="/today/executions">実行結果を記録</Link></section>}
      <p className="setting-footnote">数値モデルの提案をもとに、銘柄ごとの判断を保存します。</p>
      <section className="mock-card review-list"><h2>銘柄ごとの判断</h2>
        {proposal.lines.filter((line) => line.action !== "SKIP").map((line) => (
          <article className="review-row" key={line.lineId}>
            <div className="review-row__title">
              <div><strong>{line.companyName}</strong><span>{line.accountBucketId}</span></div>
              <ActionBadge action={line.action} />
            </div>
            <div className="ai-target"><span>AI提案</span><strong>{line.currentShares}株 → {line.recommendedShares}株</strong></div>
            <label>
              あなたの判断（100株単位）
              <select
                disabled={saving}
                aria-label={`${line.companyName}の目標株数`}
                value={targets[line.lineId] ?? line.recommendedShares}
                onChange={(event) => setTargets((current) => ({ ...current, [line.lineId]: Number(event.target.value) }))}
              >
                <option value={line.recommendedShares}>AI提案 {line.recommendedShares}株</option>
                {line.currentShares !== line.recommendedShares && <option value={line.currentShares}>取引しない {line.currentShares}株</option>}
              </select>
            </label>
            <small>参考価格 {yen(line.referencePrice)}</small>
          </article>
        ))}
      </section>
      <section className="mock-card summary-panel">
        <div className="section-title"><div><span>RECALCULATED</span><h2>判断後の見込み</h2></div></div>
        {review ? (
          <>
            <dl className="summary-list">
              <div><dt>推定購入額</dt><dd>{yen(review.estimated_buy_value)}</dd></div>
              <div><dt>推定売却額</dt><dd>{yen(review.estimated_sell_value)}</dd></div>
              <div><dt>推定取引コスト</dt><dd>{yen(review.estimated_transaction_cost)}</dd></div>
              <div><dt>推定税影響</dt><dd>{yen(review.estimated_tax_effect)}</dd></div>
              <div><dt>判断後の保有明細</dt><dd>{review.resulting_positions}件</dd></div>
            </dl>
            {Object.entries(review.estimated_cash_after).map(([bucket, cash]) => (
              <div className="cash-line" key={bucket}><span>{bucket} 推定現金</span><strong>{yen(cash)}</strong></div>
            ))}
            {review.constraint_violations.length > 0 && (
              <div className="violation" role="alert">
                <strong>このままでは保存できません</strong>
                {review.constraint_violations.map((item) => <span key={item}>{item}</span>)}
              </div>
            )}
          </>
        ) : <p>再計算中…</p>}
        {reviewError && <StatePanel tone="error" title="再計算または保存に失敗しました" detail={reviewError} />}
      </section>
      <div className="sticky-action">
        <p>保存しても証券会社への注文は行われません</p>
        <button className="button button--primary" disabled={saving || savedKey === targetKey || !review || review.constraint_violations.length > 0} onClick={() => void save()}>
          {saving ? "保存中…" : savedKey === targetKey ? "判断を保存済み" : "判断を保存"}
        </button>
        <div className="link-row"><Link className="text-link" to="/today/executions">取引を記録</Link><Link className="text-link" to="/today">提案へ戻る</Link></div>
      </div>
    </div>
  );
}

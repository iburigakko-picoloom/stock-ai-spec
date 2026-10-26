import { Fragment, type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, apiGet, apiPost } from "../api";
import { PageHeader, StatePanel, currency as yen } from "../components";
import { KV } from "../Adopted";
import { useApiData } from "../hooks";
import type { DecisionReview, TodayResponse } from "../types";
import { isAndroid } from "../mobile/native";

interface SavedDecision {
  version: number;
}
interface ConsultationSource {recordId:string;checkedAt:string;lines:{symbol:string;accountBucketId:string;currentShares:number;targetShares:number}[]}

export function DecisionReviewPage(): ReactNode {
  const [params,setParams]=useSearchParams();
  const [source,setSource]=useState(params.get("source")==="chatgpt" ? "chatgpt" : "model");
  const [consultation,setConsultation]=useState<ConsultationSource|null>(null);
  const [consultationReady,setConsultationReady]=useState(false);
  useEffect(()=>{const requested=params.get("source");if(requested==="model" || requested==="chatgpt")setSource(requested);},[params]);
  const chooseSource=(value:string)=>{setSource(value);setParams({source:value},{replace:true});};
  const [savedKey, setSavedKey] = useState<string | null>(null);
  const { data, error, loading } = useApiData<TodayResponse>("/api/v1/today");
  const [targets, setTargets] = useState<Record<string, number>>({});
  const [reviewState, setReview] = useState<{ key: string; value: DecisionReview } | null>(null);
  const [draftProposal, setDraftProposal] = useState("");
  const flight = useRef(false);
  const attempt = useRef<{ key: string; path: string; body: unknown } | null>(null);
  const initialized=useRef("");
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const proposal = data?.isStale ? null : data?.proposal;
  useEffect(()=>{if(!isAndroid())return;let active=true;setConsultationReady(false);void apiGet<{decision_source?:ConsultationSource|null}>("/api/v1/mobile/chatgpt-manual/status").then(value=>{if(active){setConsultation(value.decision_source ?? null);setConsultationReady(true);}}).catch(()=>{if(active)setConsultationReady(false);});return()=>{active=false;};},[]);
  const consultationMatches=!!proposal && !!consultation && consultation.lines.every(item=>proposal.lines.some(line=>line.symbol===item.symbol && line.accountBucketId===item.accountBucketId && line.currentShares===item.currentShares));
  const sourceBlocked=source==="chatgpt" && (!consultationReady || !consultationMatches);
  const referenceTargets=Object.fromEntries((proposal?.lines ?? []).map(line=>[line.lineId,source==="chatgpt" ? consultationMatches ? consultation?.lines.find(item=>item.symbol===line.symbol && item.accountBucketId===line.accountBucketId)?.targetShares ?? line.currentShares : line.currentShares : line.recommendedShares]));
  const sourceKey=source==="chatgpt" ? consultationMatches ? consultation!.recordId : "chatgpt-unavailable" : "model";

  const proposalKey = proposal ? JSON.stringify([proposal.proposalId,
    proposal.lines.map(line => [line.lineId, line.recommendedShares]).sort()]) : "";
  const targetKey = JSON.stringify([proposalKey, Object.entries(targets).sort(([a], [b]) => a.localeCompare(b)),sourceKey]);
  const referenceKey=JSON.stringify(referenceTargets);
  const draftIdentity=JSON.stringify([proposalKey,sourceKey]);
  const review = !sourceBlocked && reviewState?.key === targetKey && draftProposal === draftIdentity ? reviewState.value : null;
  useEffect(() => {
    if (!proposalKey) { setReview(null); return; }
    const identity=JSON.stringify([draftIdentity,referenceKey]);
    if(initialized.current===identity)return;
    initialized.current=identity;
    setDraftProposal(draftIdentity); setReview(null); attempt.current = null;
    setTargets(JSON.parse(referenceKey) as Record<string,number>);
  }, [proposalKey,referenceKey,sourceKey,draftIdentity]);

  useEffect(() => {
    if (!proposalKey || draftProposal !== draftIdentity || sourceBlocked) return;
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
  }, [proposalKey, draftProposal, targetKey,sourceBlocked,draftIdentity]);

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
          ...(source==="chatgpt" ? {note:`ChatGPT検算記録 ${consultation!.recordId}`} : {}),
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
      <div className="subscreen stack"><div className="subtabs"><button className={`button ${source==="model" ? "" : "secondary"}`} aria-pressed={source==="model"} onClick={()=>chooseSource("model")}>数値モデル</button><button className={`button ${source==="chatgpt" ? "" : "secondary"}`} aria-pressed={source==="chatgpt"} onClick={()=>chooseSource("chatgpt")}>ChatGPT</button></div>
      {sourceBlocked && <StatePanel title="ChatGPT提案の最新検算が必要です" detail="原予測・口座・保有が一致する保存済み提案を確認してください。" />}
      {source==="chatgpt" && <Link className="quiet-link" to="/today/chatgpt">ChatGPT提案を検算 ›</Link>}
      <section className="card"><h3 className="section-title">銘柄ごとの判断</h3><table className="subtable"><tbody>
        {proposal.lines.filter((line) => !sourceBlocked && line.currentShares!==referenceTargets[line.lineId]).map((line) => (
          <Fragment key={line.lineId}><tr><td><Link to={`/stocks/${line.symbol}`} state={{from:`/today/review?source=${source}`}}>{line.companyName}</Link><small className="block muted">{line.symbol} · {data?.accountLabels?.[line.accountBucketId] ?? line.accountBucketId}</small></td><td>{line.currentShares} → {targets[line.lineId] ?? referenceTargets[line.lineId]}株</td><td><button className="button" aria-label={`${line.companyName}の提案を採用`} disabled={saving} aria-pressed={(targets[line.lineId] ?? referenceTargets[line.lineId])===referenceTargets[line.lineId]} onClick={()=>setTargets(current=>({...current,[line.lineId]:(targets[line.lineId] ?? referenceTargets[line.lineId])===referenceTargets[line.lineId] ? line.currentShares : referenceTargets[line.lineId]}))}>{(targets[line.lineId] ?? referenceTargets[line.lineId])===referenceTargets[line.lineId] ? "採用" : "保有維持"}</button></td></tr><tr><td colSpan={3} className="small muted">{line.positiveReasons[0] || line.negativeReasons[0]}</td></tr></Fragment>
        ))}
      </tbody></table></section>
      <div className="subgrid"><section className="card"><h3 className="section-title">判断後の試算・確認中</h3>
        {review ? (
          <>
            <div className="metric-grid"><div>購入<strong>{yen(review.estimated_buy_value)}</strong></div><div>売却<strong>{yen(review.estimated_sell_value)}</strong></div><div>費用（推定）<strong>{yen(review.estimated_transaction_cost)}</strong></div><div>推定税<strong>{yen(review.estimated_tax_effect)}</strong></div></div>
            {Object.entries(review.estimated_cash_after).map(([bucket, cash]) => (
              <KV key={bucket} label={`${bucket} 推定現金`} value={yen(cash)} />
            ))}
            {review.constraint_violations.length > 0 && (
              <div className="violation" role="alert">
                <strong>このままでは保存できません</strong>
                {review.constraint_violations.map((item) => <span key={item}>{item}</span>)}
              </div>
            )}
          </>
        ) : <p>{sourceBlocked ? "最新検算待ち" : "再計算中…"}</p>}
        {reviewError && <StatePanel tone="error" title="再計算または保存に失敗しました" detail={reviewError} />}
      </section><section className="card"><h3 className="section-title">判断後の保有・制約</h3><table className="subtable"><thead><tr><th>銘柄</th><th>実保有</th><th>試算</th></tr></thead><tbody>{proposal.lines.filter(line=>line.action!=="SKIP").map(line=><tr key={line.lineId}><td>{line.companyName}</td><td>{line.currentShares}株</td><td>{targets[line.lineId] ?? referenceTargets[line.lineId]}株</td></tr>)}</tbody></table><KV label="判断後の保有明細" value={review ? `${review.resulting_positions}件` : "確認中"} /><KV label="制約" value={!review ? "確認中" : review.constraint_violations.length ? "要確認" : "違反なし"} /></section></div>
      <div className="subactions">
        <button className="button button--primary" disabled={saving || savedKey === targetKey || !review || review.constraint_violations.length > 0} onClick={() => void save()}>
          {saving ? "保存中…" : savedKey === targetKey ? "判断を保存済み" : "判断を保存"}
        </button>
        <Link className="button secondary" to="/today/executions">取引を記録</Link>
      </div></div>
    </div>
  );
}

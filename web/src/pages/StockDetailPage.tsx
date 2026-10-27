import { type ReactNode, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { ActionBadge, Metric, PageHeader, StatePanel, dateTime, pct, currency as yen } from "../components";
import { useApiData } from "../hooks";
import { StockMemo } from "../StockMemo";
import { StockChart } from "../StockChart";
import type { StockDetail } from "../types";

export function StockDetailPage(): ReactNode {
  const { symbol = "" } = useParams();
  const location = useLocation();
  const from: unknown = location.state?.from;
  const backTo = from === "/" || from === "/ranking" || from === "/assets" || (typeof from==="string" && /^\/today\/review(?:\?source=(?:model|chatgpt))?$/.test(from)) || from === "/today/chatgpt" || (typeof from === "string" && /^\/transactions(?:\?[^#]*)?$/.test(from)) ? from : "/today";
  const { data, error, loading, savedAt } = useApiData<StockDetail>(`/api/v1/stocks/${symbol}`);
  const [selectedBucket, setSelectedBucket] = useState<string>(location.state?.bucket ?? "ALL");
  if ((loading && !data) || error || !data) return <div className="page"><Link className="back-link" to={backTo}>← 戻る</Link><PageHeader eyebrow={symbol} title="銘柄詳細" /><StatePanel tone={loading ? "neutral" : "error"} title={loading ? "銘柄情報を読み込んでいます" : "銘柄情報を取得できません"} detail={error} /><div className="subscreen detail-foot"><Link className="button" to={`/today/executions?symbol=${encodeURIComponent(symbol)}`} state={{from:backTo,bucket:selectedBucket}}>この銘柄の取引を記録</Link></div><StockMemo key={symbol} symbol={symbol} /></div>;

  const bucketIds = Array.from(new Set([
    ...data.positions.map((item) => item.account_bucket_id),
    ...data.proposalLines.map((item) => item.accountBucketId),
  ])).sort();
  const selectedPositions = selectedBucket === "ALL"
    ? data.positions
    : data.positions.filter((item) => item.account_bucket_id === selectedBucket);
  const selectedLines = selectedBucket === "ALL"
    ? data.proposalLines
    : data.proposalLines.filter((item) => item.accountBucketId === selectedBucket);
  const company = data.proposalLines[0]?.companyName || symbol;
  const totalShares = selectedPositions.reduce((sum, item) => sum + item.shares, 0);
  const weightedAverage = totalShares === 0
    ? null
    : selectedPositions.reduce(
      (sum, item) => sum + Number(item.average_acquisition_price) * item.shares,
      0,
    ) / totalShares;

  const marketValue=selectedPositions.reduce((sum,item)=>sum+item.shares*Number(item.market_price),0);
  const research=data.chatgptResearch?.at(-1) ?? data.researchRuns?.filter(run=>run.record).at(-1)?.record;
  const prediction=data.forecast?.prediction;
  return <div className="page stock-detail">
    <PageHeader title="銘柄詳細" backTo={backTo} />
    {(loading || savedAt) && <p role="status" className="setting-footnote">{savedAt ? `${dateTime(savedAt,true)}の保存済み表示・閲覧用。` : "前回の表示です・"}更新を確認中…</p>}
    <div className="screen-detail"><header className="detail-identity"><div className="detail-code">{symbol}</div><h2>{company}</h2><span className="badge">{totalShares ? "保有中" : "未保有"}</span></header><div className="stack">
    {bucketIds.length>1 && <div className="account-tabs" role="tablist" aria-label="口座の表示"><button role="tab" aria-selected={selectedBucket === "ALL"} className={selectedBucket === "ALL" ? "active" : ""} onClick={()=>setSelectedBucket("ALL")}>合計</button>{bucketIds.map(id=><button role="tab" aria-selected={selectedBucket === id} className={selectedBucket === id ? "active" : ""} key={id} onClick={()=>setSelectedBucket(id)}>{data.accountLabels?.[id] ?? id}</button>)}</div>}
    <section className="card"><h3 className="section-title">実際の保有{selectedBucket!=="ALL" && ` / ${selectedBucket}`}</h3>
      <div className="metric-grid metric-grid--2"><Metric label="現在保有" value={`${totalShares}株`} /><Metric label="評価額" value={yen(marketValue)} /></div>
      <p>加重平均取得 {yen(weightedAverage)}{selectedPositions.length === 1 && ` · 株価 ${yen(selectedPositions[0].market_price)}`}</p>
      <small>{selectedBucket === "ALL" ? bucketIds.join(" · ") : selectedBucket}</small>
    </section>
    <section className="card" aria-labelledby="numerical-forecast-title"><h3 className="section-title" id="numerical-forecast-title">数値モデルの予測</h3><div className="detail-model-list">
      {([["5日・値予測",pct(prediction?.expected_return_5d),"予測リターン",data.forecast?.ranks?.return5d],["20日・値予測",pct(prediction?.expected_return_20d),"予測リターン",data.forecast?.ranks?.return20d],["20日・ランキング",prediction?.rank_score_20d?.toFixed(2) ?? "未算出","順位スコア",data.forecast?.ranks?.rank20d]] as const).map(([label,value,unit,rank])=><div className="detail-model-row" key={label}><div><span className="label">{label}</span>{rank!=null && <span className="small muted">{rank}位 / {data.forecast?.ranks?.total}銘柄</span>}</div><div><strong className="detail-return">{value}</strong><span className="small muted">{unit}</span></div></div>)}
      </div><p className="small muted">{data.forecast ? `${dateTime(data.forecast.generatedAt,true)} 作成${data.forecast.isStale ? " · 過去の予測" : ""}` : "予測はまだ保存されていません"}</p>
      <div className="link-row"><Link className="quiet-link" to="/ranking">予測ランキング</Link>{data.forecast?.mode !== "owner_approved" && <small>研究用・正式採用前</small>}</div>
    </section>
    <StockChart key={symbol} symbol={symbol} />
    <section className="card"><h3 className="section-title">提案と理由</h3>
      {selectedLines.length===0 ? <p className="setting-footnote">当日の提案はありません。</p> : selectedLines.map(line=><div className="detail-view" key={line.lineId}><div className="link-row"><strong>数値モデル</strong><ActionBadge action={line.action} /></div><small>{line.accountBucketId}</small><p className="detail-qty">{line.currentShares}株 → {line.recommendedShares}株</p>
        {line.positiveReasons.length ? line.positiveReasons.map(reason=><p key={reason}>{reason}</p>) : <p className="setting-footnote">構造化された追加理由はありません。</p>}
        {line.negativeReasons.map(reason=><p className="setting-footnote" key={reason}>{reason}</p>)}
        <p className="setting-footnote">この口座行のコスト {yen(line.estimatedTransactionCost)} · 推定税影響 {yen(line.estimatedTaxEffect)} · 源泉徴収見込み {yen(line.estimatedTaxCashWithholding)}</p>
      </div>)}
      <Link className="button ghost" to="/today">全体の提案 ›</Link>
    </section>
    <section className="card"><div className="row spread"><h3 className="section-title">ChatGPT調査</h3><span className="badge">{research ? "保存済み" : "未調査"}</span></div>
      {research ? <><small>{dateTime(research.comparison.completed_at,true)}</small><p>{research.comparison.text.split("\n")[0]}</p></> : <p className="setting-footnote">保存した調査・中断した処理は調査履歴で確認できます。</p>}
      <Link className="button secondary" to={`/stocks/${symbol}/research`} state={{from:backTo,bucket:selectedBucket}}>調査履歴 ›</Link>
    </section>
    <div className="detail-foot"><Link className="button" to={`/today/executions?symbol=${encodeURIComponent(symbol)}`} state={{from:backTo,bucket:selectedBucket}}>この銘柄の取引を記録</Link></div>
    {data.proposal && <Link className="quiet-link" to="/today/details">現在維持・提案全体の計算詳細 ›</Link>}
    </div></div>
    <StockMemo key={symbol} symbol={symbol} />
    {data.forecast && <section className="section"><h2>予測の条件</h2><p className="setting-footnote">入力締切 {dateTime(data.forecast.asOf,true)} JST</p><p className="setting-footnote">{data.forecast.labelDefinitionSupported ? "入力に使った株価日の翌営業日終値から、5・20営業日先までの研究予測です。実約定による損益ではありません。" : "この予測の起点は現在のモデル契約に対応していません。新しい判断には使えません。"}</p>
      {prediction?.rank_score_5d != null && <p className="setting-footnote">5日順位スコア {prediction.rank_score_5d.toFixed(4)}</p>}
      {prediction?.large_loss_probability === null && <p className="setting-footnote">下落確率は未提供です。リスクがないという意味ではありません。</p>}
      {data.forecast.blockingReasons.length>0 && <ul>{data.forecast.blockingReasons.map(reason=><li key={reason}>{reason}</li>)}</ul>}
    </section>}
  </div>;
}

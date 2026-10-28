import { useState } from "react";
import { apiGet, apiPost } from "../api";
import { dateTime } from "../components";
import { useApiData } from "../hooks";
import { isAndroid } from "../mobile/native";

type Registration = {registration_id:string;model_version:string;eligible_from:string;registered_at:string};
type Observation = {observation_id:string;run_id:string;horizon:number;count:number;scored_count:number;mean_absolute_error:number|null;rank_scored_count?:number;conditional_rank_correlation?:number|null;observed_at:string};
type DailyEvidence = {runs:{run_id:string;model_version:string;as_of:string;generated_at:string;prediction_count:number;excluded_candidates:unknown[];has_5d_return:boolean;has_20d_return:boolean;has_20d_rank:boolean}[];registrations?:Registration[];observations?:Observation[]};
type ObservationResult = {evidence:{count:number;scored_count:number;mean_absolute_error:number|null;rank_scored_count?:number;conditional_rank_correlation?:number|null}};
type ObservationDetail = {observation_id:string;evidence:{horizon:number;results:{symbol:string;expected_return:number|null;rank_score:number|null;actual_return:number|null;status:string}[]}};
const labels:Record<string,string>={available:"比較可能",pending:"期間未到達",calendar_missing:"営業日不足",price_missing:"株価不足",adjustment_missing:"調整情報不足",corporate_action:"権利処理あり",forecast_after_entry_close:"予測の作成が取引基準後",entry_close_unverified:"取引基準時刻未確認"};
const pct=(value:number|null)=>value===null ? "未提供" : `${(value*100).toFixed(2)}%`;

/** Read the immutable forecasts on demand; this is not an outcome evaluation. */
export function ForwardEvidencePanel() {
  const [started,setStarted]=useState(false);
  const [busy,setBusy]=useState(false);
  const [visibleCount,setVisibleCount]=useState(10);
  const [detail,setDetail]=useState<ObservationDetail|null>(null);
  const [detailCount,setDetailCount]=useState(20);
  const [message,setMessage]=useState("");
  const [saveError,setSaveError]=useState("");
  const {data,loading,error,reload}=useApiData<DailyEvidence>("/api/v1/mobile/forward-evidence",{enabled:started && isAndroid(),pollMs:0,refreshOnFocus:false});
  if(!isAndroid())return null;
  const recent=data?.runs.slice(-visibleCount).reverse() ?? [];
  const registrations=data?.registrations ?? [];
  const observations=data?.observations ?? [];
  async function register(){
    setBusy(true);setMessage("");setSaveError("");
    try{
      const result=await apiPost<Registration>("/api/v1/mobile/forward-evidence/register",{});
      setMessage(`検証記録を開始しました。対象は ${dateTime(result.eligible_from,true)} 以降の予測です。`);reload();
    }catch(reason){setSaveError(reason instanceof Error ? reason.message : "検証を開始できませんでした。");}
    finally{setBusy(false);}
  }
  async function observe(registration:Registration,runId:string,horizon:5|20){
    setBusy(true);setMessage("");setSaveError("");
    try{
      const result=await apiPost<ObservationResult>("/api/v1/mobile/forward-evidence/observe",{registration_id:registration.registration_id,run_id:runId,horizon});
      const {count,scored_count,mean_absolute_error}=result.evidence;
      setMessage(`${horizon}日の結果を記録しました。比較可能 ${scored_count} / ${count}銘柄${mean_absolute_error===null ? "" : ` · 平均誤差 ${(mean_absolute_error*100).toFixed(2)}ポイント`}。`);reload();
    }catch(reason){setSaveError(reason instanceof Error ? reason.message : "実績を記録できませんでした。");}
    finally{setBusy(false);}
  }
  async function showDetail(identity:string){
    setBusy(true);setSaveError("");setDetail(null);setDetailCount(20);
    try{setDetail(await apiGet<ObservationDetail>(`/api/v1/mobile/forward-evidence/observations/${identity}`));}
    catch(reason){setSaveError(reason instanceof Error ? reason.message : "実績記録を読み込めませんでした。");}
    finally{setBusy(false);}
  }
  return <section className="card" aria-label="日次予測の記録">
    <h3 className="section-title">日次予測の記録</h3>
    <p className="setting-footnote">保存した通常予測と入力の記録を確認します。正式な採用評価は行っていません。</p>
    {!started ? <button className="button secondary" onClick={()=>setStarted(true)}>記録を確認</button> : <>
      {loading && <p role="status">保存記録を確認しています…</p>}
      {error && <><p role="alert">{error}</p><button className="button secondary" onClick={reload}>再読み込み</button></>}
      {data && !error && <>
        <p className="setting-footnote">現在のモデルを固定し、開始翌日以降の予測を記録します。終値による参考比較であり、実際の取引損益や正式な採用評価ではありません。端末時刻は外部で検証していません。順位の相関は比較可能な銘柄に限ります。</p>
        <button className="button secondary" disabled={busy} onClick={()=>void register()}>{busy ? "処理中…" : "現在のモデルで検証を開始"}</button>
        {registrations.map(item=><p key={item.registration_id} className="small">対象開始 {dateTime(item.eligible_from,true)}</p>)}
        {message && <p role="status">{message}</p>}{saveError && <p role="alert">{saveError}</p>}
        <p>保存済み {data.runs.length}件{data.runs.length>visibleCount && `（直近${visibleCount}件）`}</p>
        {!recent.length ? <p>通常の日次予測はまだ保存されていません。</p> : <ul>{recent.map(run=><li key={run.run_id}>
          {dateTime(run.as_of,true)} 時点（作成 {dateTime(run.generated_at,true)}） · {run.prediction_count}銘柄 · 予測対象外 {run.excluded_candidates.length}銘柄
          {(!run.has_5d_return || !run.has_20d_return || !run.has_20d_rank) && " · 一部モデル未提供"}
          {registrations.filter(item=>item.model_version===run.model_version && Date.parse(run.as_of)>=Date.parse(item.eligible_from) && Date.parse(run.generated_at)>=Date.parse(item.eligible_from)).map(item=><div key={item.registration_id} className="stack">
            <button className="button secondary" disabled={busy} onClick={()=>void observe(item,run.run_id,5)}>5日結果を記録</button>
            <button className="button secondary" disabled={busy} onClick={()=>void observe(item,run.run_id,20)}>20日結果を記録</button>
          </div>)}
        </li>)}</ul>}
        {data.runs.length>visibleCount && <button className="button secondary" onClick={()=>setVisibleCount(count=>count+10)}>過去の記録をさらに表示</button>}
        {observations.length>0 && <><p>記録した参考結果（直近{observations.length}件）</p><ul>{observations.map(item=><li key={item.observation_id}>{dateTime(item.observed_at,true)} · {item.horizon}日 · 比較可能 {item.scored_count} / {item.count}銘柄{item.mean_absolute_error!==null && ` · 平均誤差 ${(item.mean_absolute_error*100).toFixed(2)}ポイント`}{item.conditional_rank_correlation!=null && ` · 順位相関 ${item.conditional_rank_correlation.toFixed(2)}（${item.rank_scored_count}銘柄）`} <button className="button secondary" disabled={busy} onClick={()=>void showDetail(item.observation_id)}>銘柄別を見る</button></li>)}</ul></>}
        {detail && <section aria-label="銘柄別の参考結果"><h4>{detail.evidence.horizon}日の銘柄別結果</h4><ul>{detail.evidence.results.slice(0,detailCount).map(row=><li key={row.symbol}>{row.symbol} · 値予測 {pct(row.expected_return)} · 実績 {pct(row.actual_return)}{row.rank_score!==null && ` · 順位スコア ${row.rank_score.toFixed(3)}`} · {labels[row.status] ?? "確認できません"}</li>)}</ul>{detail.evidence.results.length>detailCount && <button className="button secondary" onClick={()=>setDetailCount(count=>count+20)}>銘柄をさらに表示</button>}</section>}
      </>}
    </>}
  </section>;
}

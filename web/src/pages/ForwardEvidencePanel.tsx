import { useState } from "react";
import { dateTime } from "../components";
import { useApiData } from "../hooks";
import { isAndroid } from "../mobile/native";

type DailyEvidence = {runs:{run_id:string;as_of:string;generated_at:string;prediction_count:number;excluded_candidates:unknown[];has_5d_return:boolean;has_20d_return:boolean;has_20d_rank:boolean}[]};

/** Read the immutable forecasts on demand; this is not an outcome evaluation. */
export function ForwardEvidencePanel() {
  const [started,setStarted]=useState(false);
  const {data,loading,error,reload}=useApiData<DailyEvidence>("/api/v1/mobile/forward-evidence",{enabled:started && isAndroid(),pollMs:0,refreshOnFocus:false});
  if(!isAndroid())return null;
  const recent=data?.runs.slice(-10).reverse() ?? [];
  return <section className="card" aria-label="日次予測の記録">
    <h3 className="section-title">日次予測の記録</h3>
    <p className="setting-footnote">保存した通常予測と入力の記録を確認します。実績との比較や最終評価はまだ行っていません。</p>
    {!started ? <button className="button secondary" onClick={()=>setStarted(true)}>記録を確認</button> : <>
      {loading && <p role="status">保存記録を確認しています…</p>}
      {error && <><p role="alert">{error}</p><button className="button secondary" onClick={reload}>再読み込み</button></>}
      {data && !error && <><p>保存済み {data.runs.length}件{data.runs.length>10 && "（直近10件）"}</p>
        {!recent.length ? <p>通常の日次予測はまだ保存されていません。</p> : <ul>{recent.map(run=><li key={run.run_id}>
          {dateTime(run.as_of,true)} 時点（作成 {dateTime(run.generated_at,true)}） · {run.prediction_count}銘柄 · 予測対象外 {run.excluded_candidates.length}銘柄
          {(!run.has_5d_return || !run.has_20d_return || !run.has_20d_rank) && " · 一部モデル未提供"}
        </li>)}</ul>}
      </>}
    </>}
  </section>;
}

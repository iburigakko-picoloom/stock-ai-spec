import { useState } from "react";
import { useApiData } from "./hooks";
import { isAndroid } from "./mobile/native";

type Point = {date:string;close:number|null;volume:number|null};
type Outcome = {horizon:number;expectedReturn:number|null;status:string;return:number|null;entryDate:string|null;exitDate:string|null};
type Forecast = {runId:string;kind:"daily"|"reference"|"archive";priceDate:string|null;asOf:string;generatedAt:string;horizons:Outcome[]};
type Data = {symbol:string;firstDate:string;lastDate:string;observedAt:string;prices:Point[];calendar:Record<string,boolean>;forecasts:Forecast[]};

const day = (value:string) => Date.parse(`${value}T00:00:00Z`);
const percent = (value:number|null) => value === null ? "—" : `${(value*100).toFixed(2)}%`;
const status:Record<string,string> = {available:"参考値",pending:"結果待ち",calendar_missing:"営業日情報不足",price_missing:"株価不足",adjustment_missing:"調整情報不足",corporate_action:"企業行動の確認が必要",label_unsupported:"予測期間の定義を確認できません",prediction_missing:"値予測なし",price_date_missing:"基準の株価日が未確認"};

function Charts({data,horizon}:{data:Data;horizon:number}) {
  const start=day(data.firstDate), end=day(data.lastDate), span=Math.max(1,end-start);
  const x=(d:string)=>12+296*(day(d)-start)/span;
  const closes=data.prices.filter(p=>p.close!==null);
  const low=closes.length ? Math.min(...closes.map(p=>p.close!)) : 0;
  const high=closes.length ? Math.max(...closes.map(p=>p.close!)) : 0;
  const y=(value:number)=>10+92*(high===low ? .5 : (high-value)/(high-low));
  const priceDates=new Set(closes.map(p=>p.date));
  const canJoin=(left:string,right:string)=>{
    for(let d=day(left)+86400000;d<day(right);d+=86400000){
      const key=new Date(d).toISOString().slice(0,10);
      if (!(key in data.calendar) || (data.calendar[key] && !priceDates.has(key))) return false;
    }
    return true;
  };
  const maxVolume=Math.max(0,...data.prices.map(p=>p.volume??0));
  const results=data.forecasts.flatMap(f=>f.horizons.filter(h=>h.horizon===horizon).map(h=>({forecast:f,outcome:h})));
  const plottable=results.filter(({forecast})=>forecast.priceDate!==null);
  const returns=plottable.flatMap(({outcome})=>[outcome.expectedReturn,outcome.return]).filter((v):v is number=>v!==null);
  const minReturn=Math.min(0,...returns),maxReturn=Math.max(0,...returns);
  const ry=(v:number)=>10+95*(maxReturn===minReturn ? .5 : (maxReturn-v)/(maxReturn-minReturn));
  return <>
    <h4>株価・出来高</h4>
    {closes.length===0 ? <p>表示できる終値はありません。</p> : <>
      <p className="small muted">終値 {low.toLocaleString("ja-JP")}〜{high.toLocaleString("ja-JP")}円・出来高は株数</p>
      <svg className="stock-chart-plot" viewBox="0 0 320 155" role="img" aria-label="保存済み終値と出来高の推移">
        {closes.slice(1).map((p,index)=>canJoin(closes[index].date,p.date) && <line key={`l${p.date}`} x1={x(closes[index].date)} y1={y(closes[index].close!)} x2={x(p.date)} y2={y(p.close!)} stroke="#2859a6" strokeWidth="2" />)}
        {closes.map(p=><circle key={`p${p.date}`} cx={x(p.date)} cy={y(p.close!)} r="2" fill="#2859a6"><title>{p.date} 終値 {p.close}円</title></circle>)}
        {data.prices.filter(p=>p.volume!==null).map(p=><line key={`v${p.date}`} x1={x(p.date)} x2={x(p.date)} y1="150" y2={150-(maxVolume ? 30*p.volume!/maxVolume : 0)} stroke="#8492a5" strokeWidth="2"><title>{p.date} 出来高 {p.volume}株</title></line>)}
      </svg>
      <p className="small muted">{data.firstDate}〜{data.lastDate}。記録のない日は表示しません。終値は確認時点の未調整株価です。確認 {new Date(data.observedAt).toLocaleString("ja-JP",{timeZone:"Asia/Tokyo"})} JST</p>
    </>}
    <h4>{horizon}営業日の予測と実績</h4>
    {returns.length===0 ? <p>株価日を確認できる保存予測はありません。</p> : <>
      <p className="small muted">予測 ● / 実績 ○（{percent(minReturn)}〜{percent(maxReturn)}）</p>
      <svg className="stock-chart-plot" viewBox="0 0 320 115" role="img" aria-label={`${horizon}営業日予測と実績の比較`}>
        <line x1="12" x2="308" y1={ry(0)} y2={ry(0)} stroke="#ccd2dc" />
        {plottable.map(({forecast,outcome})=><g key={forecast.runId}>
          {outcome.expectedReturn!==null && <circle cx={x(forecast.priceDate!)} cy={ry(outcome.expectedReturn)} r="3" fill="#2859a6"><title>{forecast.priceDate} 予測 {percent(outcome.expectedReturn)}</title></circle>}
          {outcome.return!==null && <circle cx={x(forecast.priceDate!)} cy={ry(outcome.return)} r="4" fill="white" stroke="#15243a" strokeWidth="1.5"><title>{forecast.priceDate} 実績 {percent(outcome.return)}</title></circle>}
        </g>)}
      </svg>
      <p className="small muted">横軸は予測入力の株価日。実績は翌営業日終値から{horizon}営業日後までの調整済み終値の変化を示す研究用の参考値です。実取引の損益ではありません。後日の訂正を含む表示時点の株価を使用し、配当や企業行動は個別に確認していません。</p>
    </>}
    {results.length>0 && <div className="stock-chart-results" aria-label={`${horizon}営業日の保存予測一覧`}>
      {results.slice().reverse().map(({forecast,outcome})=><div key={forecast.runId}>
        <strong>{forecast.priceDate ? `${forecast.priceDate} 基準` : "基準の株価日が未確認"}</strong><span>{forecast.kind==="reference" ? "参考分析" : forecast.kind==="archive" ? "保存予測" : "日次予測"}・作成 {new Date(forecast.generatedAt).toLocaleString("ja-JP",{timeZone:"Asia/Tokyo"})}</span>
        <span>予測 {percent(outcome.expectedReturn)} / 実績 {percent(outcome.return)}（{status[outcome.status] ?? "未確認"}）</span>
        {outcome.entryDate && outcome.exitDate && <span>実績期間 {outcome.entryDate}〜{outcome.exitDate}</span>}
      </div>)}
    </div>}
  </>;
}

export function StockChart({symbol}:{symbol:string}) {
  const [started,setStarted]=useState(false), [days,setDays]=useState(90), [horizon,setHorizon]=useState(5);
  const android=isAndroid();
  const {data,error,loading,reload}=useApiData<Data>(`/api/v1/mobile/stocks/${encodeURIComponent(symbol)}/chart?days=${days}`,{enabled:started&&android,pollMs:0,refreshOnFocus:false});
  return <section className="card stock-chart" aria-label="株価と予測のグラフ">
    <h3 className="section-title">株価と予測</h3>
    {!android ? <p>このグラフは端末版で利用できます。</p> : !started ? <><p>保存済みの株価と予測から表示します。</p><button className="button secondary" onClick={()=>setStarted(true)}>グラフを表示</button></> : <>
      <div className="stock-chart-options" role="group" aria-label="表示期間">{([[30,"1か月"],[90,"3か月"],[180,"6か月"],[366,"1年"]] as const).map(([n,label])=><button key={n} aria-pressed={days===n} onClick={()=>setDays(n)}>{label}</button>)}</div>
      {loading && <p role="status">グラフを読み込んでいます…</p>}
      {error && <><p role="alert">{error}</p><button className="button secondary" onClick={reload}>再読み込み</button></>}
      {data && !error && <><div className="stock-chart-options" role="group" aria-label="予測期間">{[5,20].map(n=><button key={n} aria-pressed={horizon===n} onClick={()=>setHorizon(n)}>{n}日</button>)}</div><Charts data={data} horizon={horizon} /></>}
    </>}
  </section>;
}

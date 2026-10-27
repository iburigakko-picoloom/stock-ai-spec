import { useEffect, useRef, useState } from "react";
import { useApiData } from "./hooks";
import { isAndroid } from "./mobile/native";

type Forecast = {runId:string; date:string; generatedAt:string; kind:"daily"|"reference"|"archive"; return5d:number|null; return20d:number|null};
type History = {symbol:string;firstDate:string;lastDate:string;forecasts:Forecast[]};
const percent=(value:number|null)=>value===null ? "未提供" : `${value>0?"+":""}${(value*100).toFixed(2)}%`;
const time=(value:string)=>new Date(value).toLocaleString("ja-JP",{timeZone:"Asia/Tokyo",month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit"});

function ForecastLines({forecasts}:{forecasts:Forecast[]}) {
  const scrollRef=useRef<HTMLDivElement>(null);
  const [selection,setSelection]=useState("");
  useEffect(()=>{if(scrollRef.current)scrollRef.current.scrollLeft=scrollRef.current.scrollWidth;},[forecasts]);
  const values=forecasts.flatMap(item=>[item.return5d,item.return20d]).filter((value):value is number=>value!==null);
  if (!values.length) return <p>表示できる値予測はありません。</p>;
  const lower=Math.min(0,...values), upper=Math.max(0,...values);
  const min=lower===upper ? -.01 : lower, max=lower===upper ? .01 : upper;
  const y=(value:number)=>14+126*(max-value)/(max-min);
  const width=Math.max(240,48+forecasts.length*58);
  const ticks=[...new Set([max,0,min])];
  const key=(item:Forecast)=>`${item.kind}:${item.runId}`;
  const current=forecasts.find(item=>key(item)===selection) ?? forecasts.at(-1)!;
  return <>
    <p className="small muted"><span className="forecast-key forecast-key--five" />5日値予測 {" / "}<span className="forecast-key forecast-key--twenty" />20日値予測</p>
    <div className="forecast-plot-frame">
      <svg className="forecast-axis" width="58" height="190" viewBox="0 0 58 190" aria-hidden="true">{ticks.map(value=><text key={value} x="54" y={y(value)+4} textAnchor="end" fontSize="10">{percent(value)}</text>)}</svg>
      <div className="forecast-plot-scroll" ref={scrollRef} tabIndex={0} aria-label="予測グラフを横にスクロール">
      <svg className="forecast-plot" width={width} height="190" viewBox={`0 0 ${width} 190`} role="img" aria-label="5日と20日の保存予測の折れ線グラフ">
        {ticks.map(value=><line key={value} x1="0" x2={width} y1={y(value)} y2={y(value)} stroke="#dfe4e8" />)}
        {([[
          "return5d","#2859a6","5日"],["return20d","#8194ac","20日"]] as const).flatMap(([field,color,label])=>forecasts.slice(1).map((item,index)=>{
          const previous=forecasts[index], before=previous[field], after=item[field];
          return before===null || after===null ? null : <line key={`${field}:${key(item)}`} className="forecast-line-segment" data-series={label} x1={24+58*index} y1={y(before)} x2={24+58*(index+1)} y2={y(after)} stroke={color} strokeWidth="2" />;
        }))}
        {forecasts.map((item,index)=>{
          const x=24+58*index;
          return <g key={key(item)} onClick={()=>setSelection(key(item))} className="forecast-point-group">
            {item.return5d!==null && <circle data-series="5日" cx={x} cy={y(item.return5d)} r="4" fill="#2859a6"><title>{item.date} 5日 {percent(item.return5d)} / 作成 {time(item.generatedAt)}</title></circle>}
            {item.return20d!==null && <polygon data-series="20日" points={`${x},${y(item.return20d)-6} ${x+6},${y(item.return20d)} ${x},${y(item.return20d)+6} ${x-6},${y(item.return20d)}`} fill="none" stroke="#8194ac" strokeWidth="2"><title>{item.date} 20日 {percent(item.return20d)} / 作成 {time(item.generatedAt)}</title></polygon>}
            <text x={x} y="157" textAnchor="middle" fontSize="9">{item.date.slice(5).replace("-","/")}</text>
            <text x={x} y="170" textAnchor="middle" fontSize="8">{time(item.generatedAt).split(" ").at(-1)}</text>
          </g>;
        })}
      </svg>
      </div>
    </div>
    <p className="small muted">横軸は予測の基準日、下段は作成時刻です。保存結果を等間隔に並べ、同じ日の結果も分けて直線で結びます。実績ではありません。未提供の値をまたぐ線は描きません。</p>
    <label className="forecast-selection">数値を見る日<select value={key(current)} onChange={event=>setSelection(event.target.value)}>{forecasts.slice().reverse().map(item=><option key={key(item)} value={key(item)}>{item.date} · {time(item.generatedAt)} · {item.kind==="reference" ? "参考分析" : item.kind==="archive" ? "保存予測" : "日次予測"}</option>)}</select></label>
    <p className="forecast-selected-values">5日 {percent(current.return5d)} / 20日 {percent(current.return20d)}</p>
  </>;
}

export function ForecastHistory({symbol}:{symbol:string}) {
  const [days,setDays]=useState(90), [started,setStarted]=useState(false);
  const android=isAndroid();
  useEffect(()=>{
    if(!android)return;
    let active=true, frame=0;
    const start=()=>{if(active){active=false;window.clearTimeout(timer);window.cancelAnimationFrame(frame);setStarted(true);}};
    const timer=window.setTimeout(start,120);
    frame=window.requestAnimationFrame(()=>{frame=window.requestAnimationFrame(start);});
    return ()=>{active=false;window.clearTimeout(timer);window.cancelAnimationFrame(frame);};
  },[android]);
  const {data,error,loading,reload}=useApiData<History>(`/api/v1/mobile/stocks/${encodeURIComponent(symbol)}/forecast-history?days=${days}`,{enabled:android&&started,pollMs:0,refreshOnFocus:false});
  return <section className="card stock-chart" aria-label="モデル予測の推移">
    <h3 className="section-title">モデル予測の推移</h3>
    {!android ? <p>このグラフは端末版で利用できます。</p> : <>
      <div className="stock-chart-options" role="group" aria-label="表示期間">{([[30,"1か月"],[90,"3か月"],[180,"6か月"],[366,"1年"]] as const).map(([n,label])=><button key={n} aria-pressed={days===n} onClick={()=>setDays(n)}>{label}</button>)}</div>
      {loading && <p role="status">予測の推移を読み込んでいます…</p>}
      {error && <><p role="alert">{error}</p><button className="button secondary" onClick={reload}>再読み込み</button></>}
      {data && !error && (data.forecasts.length ? <ForecastLines forecasts={data.forecasts} /> : <p>この期間の保存予測はありません。</p>)}
    </>}
  </section>;
}

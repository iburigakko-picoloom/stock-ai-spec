import { useState } from "react";
import { useApiData } from "./hooks";
import { isAndroid } from "./mobile/native";

type Effect = {feature:string;difference:number;rankChange:number|null};
type Model = {horizon:number;role:"return"|"ranking";available:boolean;prediction?:number;originalRank?:number|null;positive?:Effect[];negative?:Effect[]};
type Explanation = {symbol:string;snapshotId:string;asOf:string;method:string;models:Model[]};

const labels:Record<string,string>={
  "price.return_1d":"1日の騰落率","price.return_5d":"5日の騰落率","price.return_20d":"20日の騰落率","price.return_60d":"60日の騰落率","price.return_120d":"120日の騰落率",
  "price.distance_52w_high":"52週高値からの距離","risk.realized_vol_20d":"20日の変動率","risk.realized_vol_60d":"60日の変動率","risk.atr_14":"14日の値幅","risk.natr_14":"14日の値幅率",
  "risk.downside_vol_20d":"20日の下方変動","risk.max_drawdown_60d":"60日の最大下落","risk.max_drawdown_120d":"120日の最大下落","risk.return_skew_60d":"60日の騰落の偏り","risk.return_quantile_10_60d":"60日の下位騰落率",
  "volume.ratio_20d":"20日平均に対する出来高","volume.ratio_5_60":"5日・60日の出来高比","volume.obv_slope_5d":"5日のOBV傾き","volume.obv_slope_20d":"20日のOBV傾き","volume.mfi_14":"14日の資金流入指標","volume.zscore_20d":"20日の出来高偏差","volume.cmf_20":"20日の資金流入指標",
  "liquidity.trading_value":"売買代金","liquidity.trading_value_mean_20d":"20日平均売買代金","liquidity.turnover_20d":"20日の売買回転率","liquidity.trading_value_ratio_20_60":"20日・60日の売買代金比",
  "relative.topix_5d":"TOPIXに対する5日の騰落","relative.topix_20d":"TOPIXに対する20日の騰落","relative.topix_60d":"TOPIXに対する60日の騰落","relative.sector_5d":"業種に対する5日の騰落","relative.sector_20d":"業種に対する20日の騰落","relative.sector_60d":"業種に対する60日の騰落",
  "fundamental.per":"PER","fundamental.pbr":"PBR","fundamental.roe":"ROE","fundamental.operating_margin":"営業利益率","fundamental.revenue_growth_yoy":"売上高の前年比","fundamental.operating_profit_growth_yoy":"営業利益の前年比","fundamental.forecast_revision":"会社予想の修正",
  "macd.value_pct_price":"株価に対するMACD","macd.signal_pct_price":"株価に対するMACDシグナル","macd.histogram_pct_price":"株価に対するMACD差","macd.golden_cross":"MACDの上抜け","macd.dead_cross":"MACDの下抜け","macd.days_since_golden_cross":"MACD上抜けからの日数","macd.days_since_dead_cross":"MACD下抜けからの日数",
  "market.volatility_20d":"市場の20日変動率","market.breadth":"市場の値上がり銘柄の広がり","candle.body_pct_close":"終値に対する実体","candle.body_to_range":"値幅に対する実体","candle.upper_wick_ratio":"上ひげの比率","candle.lower_wick_ratio":"下ひげの比率","candle.close_location":"値幅内の終値位置","candle.gap_pct":"前日からの窓",
  "breakout.above_20d_high":"20日高値の上抜け","breakout.below_20d_low":"20日安値の下抜け","breakout.above_60d_high":"60日高値の上抜け","breakout.below_60d_low":"60日安値の下抜け",
};
const variants=[{key:"5-return",label:"5日・値予測",horizon:5,role:"return"},{key:"20-return",label:"20日・値予測",horizon:20,role:"return"},{key:"20-ranking",label:"20日・ランキング",horizon:20,role:"ranking"}] as const;
function difference(value:number,role:Model["role"]){
  const number=role==="return" ? value*100 : value;
  const amount=Math.abs(number)<0.0001 ? number.toExponential(2) : number.toFixed(4);
  return `${number>0 ? "+" : ""}${amount}${role==="return" ? "パーセントポイント" : "スコア"}`;
}
function Effects({title,items,role}:{title:string;items:Effect[];role:Model["role"]}){
  return <div><h4>{title}</h4>{items.length ? <ul className="stock-effect-list">{items.map(item=><li key={item.feature}><span>{labels[item.feature] ?? item.feature}</span><span>{difference(item.difference,role)}{item.rankChange!==null && ` / 順位${item.rankChange>0 ? `${item.rankChange}位上` : item.rankChange<0 ? `${-item.rankChange}位下` : "変化なし"}`}</span></li>)}</ul> : <p className="small muted">この比較ではありません。</p>}</div>;
}
export function StockExplanation({symbol,snapshotId,fromRanking=false}:{symbol:string;snapshotId:string;fromRanking?:boolean}){
  const [started,setStarted]=useState(false), [selected,setSelected]=useState(variants[0].key as string);
  const android=isAndroid(), valid=/^[0-9a-f]{64}$/.test(snapshotId);
  const {data,loading,error,reload}=useApiData<Explanation>(`/api/v1/mobile/stocks/${encodeURIComponent(symbol)}/explanation?snapshot=${snapshotId}`,{enabled:started&&android&&valid,pollMs:0,refreshOnFocus:false});
  const current=variants.find(item=>item.key===selected)!;
  const model=data?.models.find(item=>item.horizon===current.horizon && item.role===current.role);
  return <section className="card stock-explanation" aria-label="予測に影響した特徴量">
    <h3 className="section-title">予測に影響した要因</h3>
    {fromRanking && <p className="small muted">ランキングで選択した保存予測の要因です。</p>}
    {!android ? <p>この機能は端末版で利用できます。</p> : !valid ? <p>保存した予測を確認できません。</p> : !started ? <><p>保存時のデータを再確認して計算します。時間がかかることがあります。</p><button className="button secondary" onClick={()=>setStarted(true)}>予測の要因を見る</button></> : <>
      {loading && <p role="status">保存時の入力とモデルを確認しています…</p>}
      {error && <><p role="alert">{error}</p><button className="button secondary" onClick={reload}>再読み込み</button></>}
      {data && !error && <>
        <p className="small muted">{new Date(data.asOf).toLocaleString("ja-JP",{timeZone:"Asia/Tokyo"})} 時点の保存予測</p>
        <p className="small muted">各項目だけを学習時の中央値に置き換えた場合との差です。他の項目は固定します。項目同士の関係があるため、差を合計できず、原因を証明するものでもありません。</p>
        <div className="stock-chart-options" role="group" aria-label="予測モデル">{variants.map(item=><button key={item.key} aria-pressed={selected===item.key} onClick={()=>setSelected(item.key)}>{item.label}</button>)}</div>
        {!model?.available ? <p>このモデルの要因は確認できません。</p> : <>
          <p className="small muted">{current.role==="return" ? `予測 ${(model.prediction!*100).toFixed(2)}%` : `順位スコア ${model.prediction!.toFixed(4)}${model.originalRank ? ` / ${model.originalRank}位` : ""}`}</p>
          <Effects title="押し上げた項目" items={model.positive ?? []} role={model.role} />
          <Effects title="押し下げた項目" items={model.negative ?? []} role={model.role} />
        </>}
      </>}
    </>}
  </section>;
}

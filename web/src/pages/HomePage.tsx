import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../api";
import { PageHeader, RuntimeBanner, StatePanel, dateTime, currency as yen } from "../components";
import { useApiData } from "../hooks";
import type { HoldingView, HomeResponse } from "../types";
import { DailyStatusLink } from "../mobile/DailyPanel";
import { isAndroid } from "../mobile/native";

type HoldingMarket = {portfolioId:string;names:Record<string,string>;prices?:Record<string,string>;priceDate?:string|null};
const amount = (value:unknown):number|null => {
  if (typeof value !== "string" && typeof value !== "number") return null;
  if (typeof value === "string" && !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 && number <= Number.MAX_SAFE_INTEGER ? number : null;
};
const price = (value:number|null):string => value === null ? "未確認" : `¥${value.toLocaleString("ja-JP",{maximumFractionDigits:2})}`;
const signedMoney = (value:number|null):string => {
  if (value === null) return "未確認";
  const rounded=Math.round(Math.abs(value));
  return `${rounded && value < 0 ? "−" : rounded && value > 0 ? "+" : ""}¥${rounded.toLocaleString("ja-JP")}`;
};
const signedPercent = (value:number|null):string => {
  if (value === null) return "未確認";
  const rounded=Math.round(Math.abs(value)*100)/100;
  return `${rounded && value < 0 ? "−" : rounded && value > 0 ? "+" : ""}${rounded.toFixed(2)}%`;
};
const japanDate = (value:string|undefined):string|null => {
  if(!value)return null;
  const instant=new Date(value);
  if(!Number.isFinite(instant.getTime()))return null;
  const parts=new Intl.DateTimeFormat("en-US",{timeZone:"Asia/Tokyo",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(instant);
  const part=(name:string)=>parts.find(item=>item.type===name)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
};

function holdingTotals(holdings:HoldingView[]) {
  let shares=0, book:number|null=0, market:number|null=0;
  const prices:number[]=[];
  for(const item of holdings){
    const acquisition=amount(item.averageAcquisitionPrice), current=amount(item.currentPrice);
    if(!Number.isSafeInteger(item.shares) || item.shares <= 0)
      return {shares:null,book:null,market:null,current:null,pricesDiffer:false};
    shares+=item.shares;
    book=book === null || acquisition === null ? null : book+acquisition*item.shares;
    market=market === null || current === null ? null : market+current*item.shares;
    if(current !== null)prices.push(current);
  }
  if(!shares || !Number.isSafeInteger(shares))
    return {shares:null,book:null,market:null,current:null,pricesDiffer:false};
  if(book !== null && (!Number.isFinite(book) || book>Number.MAX_SAFE_INTEGER))book=null;
  if(market !== null && (!Number.isFinite(market) || market>Number.MAX_SAFE_INTEGER))market=null;
  const pricesDiffer=prices.length===holdings.length && prices.some(value=>value!==prices[0]);
  return {shares,book,market,current:pricesDiffer || prices.length!==holdings.length ? null : prices[0],pricesDiffer};
}

export function HomePage(): ReactNode {
  const { data, error, loading, savedAt } = useApiData<HomeResponse>(isAndroid() ? "/api/v1/home/ledger" : "/api/v1/home");
  const [resolvedMarket,setResolvedMarket]=useState<HoldingMarket|null>(null);
  const groups = useMemo(() => {
    const result = new Map<string, HoldingView[]>();
    for (const holding of data?.holdings || []) {
      result.set(holding.symbol, [...(result.get(holding.symbol) || []), holding]);
    }
    return [...result.entries()];
  }, [data]);
  const portfolioId=data?.portfolioId;
  useEffect(()=>{
    if(!isAndroid() || !portfolioId || groups.length===0 || loading || error || resolvedMarket?.portfolioId===portfolioId)return;
    let active=true, dispatched=false, frame=0;
    const dispatch=()=>{
      if(!active || dispatched)return;
      dispatched=true;window.clearTimeout(timer);window.cancelAnimationFrame(frame);
      void apiGet<HoldingMarket>("/api/v1/mobile/holdings/market").then(result=>{
        if(active && result?.portfolioId===portfolioId)setResolvedMarket(result);
      }).catch(()=>{if(active)setResolvedMarket({portfolioId,names:{},prices:{},priceDate:null});});
    };
    const timer=window.setTimeout(dispatch,120);
    frame=window.requestAnimationFrame(()=>{frame=window.requestAnimationFrame(dispatch);});
    return ()=>{active=false;window.clearTimeout(timer);window.cancelAnimationFrame(frame);};
  },[portfolioId,groups.length,loading,error,resolvedMarket]);

  if ((loading && !data) || error || !data) return <div className="page home-page"><PageHeader title="ホーム" /><div className="screen-home"><div className="stack"><StatePanel tone={loading ? "neutral" : "error"} title={loading ? "実資産を読み込んでいます" : "資産データを取得できません"} detail={error} /><div className="home-heading"><h3>保有株</h3><Link className="home-link" to="/assets">資産を管理 ›</Link></div><Link className="button" to="/today/executions">＋ 取引を記録</Link><div className="row spread"><Link className="home-link" to="/transactions">取引履歴 ›</Link><Link className="home-link" to="/today">今日の提案を見る →</Link></div></div></div></div>;
  const portfolio = data.portfolio;
  const ledgerPriceDate=data.initialLedger?.referencePriceDate || japanDate(portfolio?.asOf);

  return <div className="page home-page">
    <PageHeader title="ホーム" actions={<DailyStatusLink />} />
    {loading && <p role="status" className="setting-footnote">{savedAt ? `${dateTime(savedAt, true)} JSTの保存済み表示・閲覧用。` : "前回の表示です・"}更新を確認中…</p>}
    {data.runtimeMode === "DETERMINISTIC_FIXTURE_ONLY" && <RuntimeBanner mode={data.runtimeMode} />}
    <div className="screen-home"><div className="stack"><div className="muted small">実際の資産</div>
    <section className="card" aria-label="資産残高">
      <div className="home-balance-line"><span className="muted small">総資産</span><b>{portfolio ? yen(portfolio.totalAssets) : "—"}</b></div>
      <div className="home-inline-metrics"><span>株式 <b>{portfolio ? yen(portfolio.equityValue) : "—"}</b></span><span>現金 <b>{portfolio ? yen(portfolio.cashValue) : "—"}</b></span></div>
      <div className="home-demo" style={{marginTop:10}}>{data.initialLedger?.referencePriceDate ? `株価：${data.initialLedger.referencePriceDate} 終値` : portfolio ? `残高：${dateTime(portfolio.asOf, true)} JST` : "資産はまだ登録されていません"}</div>
      {portfolio ? <div className="home-account"><div className="row spread"><span>現金総額</span><b>{yen(portfolio.cashValue)}</b></div>
        {portfolio.reservedCash !== undefined && <div className="row spread"><span>確保中</span><b>{yen(portfolio.reservedCash)}</b></div>}
        {portfolio.buyingPower !== undefined && <div className="row spread"><span>運用可能</span><b>{yen(portfolio.buyingPower)}</b></div>}
      </div> : <div className="home-account">
        <Link className="button secondary full" to={isAndroid() ? "/holdings?initial=1" : "/settings"}>初回資産登録</Link>
      </div>
      }
    </section>
    <div className="home-heading"><h3>保有株 <span className="muted small">{groups.length}銘柄</span></h3><Link className="home-link" to="/assets">資産を管理 ›</Link></div>
    <section className="card" aria-label="実保有"><div>
      {groups.length === 0 ? <p className="setting-footnote">保有株はありません。</p> : groups.map(([symbol, holdings]) => {
        const market=resolvedMarket && resolvedMarket.portfolioId===portfolioId ? resolvedMarket : null;
        const quote=amount(market?.prices?.[symbol]);
        const quoteDate=typeof market?.priceDate === "string" && /^\d{4}-\d{2}-\d{2}$/.test(market.priceDate) && ledgerPriceDate && market.priceDate>=ledgerPriceDate && quote !== null && quote > 0 ? market.priceDate : null;
        const effective=quoteDate ? holdings.map(item=>({...item,currentPrice:String(quote)})) : holdings;
        const totals=holdingTotals(effective);
        const gain=totals.market === null || totals.book === null ? null : totals.market-totals.book;
        const gainRate=gain === null || !totals.book ? null : gain/totals.book*100;
        const ownName=holdings.map(item=>item.companyName?.trim()).find(name=>name && name!==symbol);
        const resolved=market?.names[symbol]?.trim();
        const company=(resolved && resolved!==symbol ? resolved : ownName) || "銘柄名未確認";
        return <article className="home-held" key={symbol}>
          <div className="home-held-head"><Link className="home-stock-button" state={{from:"/"}} to={`/stocks/${symbol}`}><strong>{company} <span className="muted">›</span></strong><small>{symbol}</small></Link>
            <div className="home-amount">{totals.market === null ? "未確認" : yen(totals.market)}<small>{totals.shares === null ? "株数未確認" : `${totals.shares.toLocaleString("ja-JP")}株`}</small></div></div>
          <dl className="home-holding-metrics">
            <div><dt>平均取得単価</dt><dd>{price(totals.book === null || totals.shares === null ? null : totals.book/totals.shares)}</dd></div>
            <div><dt>現在値</dt><dd>{totals.pricesDiffer ? "口座ごとに異なる" : price(totals.current)}{totals.current !== null && <small className="home-price-date">{quoteDate ? `${quoteDate} 終値` : "保存値"}</small>}</dd></div>
            <div><dt>評価損益</dt><dd>{signedMoney(gain)}</dd></div><div><dt>損益率</dt><dd>{signedPercent(gainRate)}</dd></div>
          </dl>
          {holdings.length===1 ? <div className="muted small">{data.accountLabels?.[holdings[0].accountBucketId] ?? holdings[0].accountBucketId}</div> : <div className="home-account">{effective.map(holding=><div className="home-account-detail" key={holding.accountBucketId}><span>{data.accountLabels?.[holding.accountBucketId] ?? holding.accountBucketId} · {holding.shares}株</span><span>取得 {price(amount(holding.averageAcquisitionPrice))} · {quoteDate ? "終値" : "保存株価"} {price(amount(holding.currentPrice))}</span></div>)}</div>}
        </article>;
      })}
      {groups.length>0 && <p className="setting-footnote">保有株の損益は取得済み終値または保存株価による参考値です。上の総資産は保存残高で、税・売却費用・配当は含みません。</p>}
    </div></section>
    <Link className="button" to="/today/executions">＋ 取引を記録</Link>
    <div className="row spread"><Link className="home-link" to="/transactions">取引履歴 ›</Link><Link className="home-link" to="/today">今日の提案を見る →</Link></div></div></div>
  </div>;
}

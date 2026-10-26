import { type ReactNode, useMemo } from "react";
import { Link } from "react-router-dom";
import { PageHeader, RuntimeBanner, StatePanel, dateTime, currency as yen } from "../components";
import { useApiData } from "../hooks";
import type { HoldingView, HomeResponse } from "../types";
import { DailyStatusLink } from "../mobile/DailyPanel";
import { isAndroid } from "../mobile/native";

export function HomePage(): ReactNode {
  const { data, error, loading, savedAt } = useApiData<HomeResponse>("/api/v1/home");
  const groups = useMemo(() => {
    const result = new Map<string, HoldingView[]>();
    for (const holding of data?.holdings || []) {
      result.set(holding.symbol, [...(result.get(holding.symbol) || []), holding]);
    }
    return [...result.entries()];
  }, [data]);

  if ((loading && !data) || error || !data) return <div className="page"><PageHeader eyebrow="実際の状態" title="ホーム" /><StatePanel tone={loading ? "neutral" : "error"} title={loading ? "実資産を読み込んでいます" : "資産データを取得できません"} detail={error} /></div>;
  const portfolio = data.portfolio;

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
        const marketValue=holdings.reduce((sum,item)=>sum+Number(item.marketValue),0);
        const shares=holdings.reduce((sum,item)=>sum+item.shares,0);
        return <article className="home-held" key={symbol}>
          <div className="home-held-head"><Link className="home-stock-button" state={{from:"/"}} to={`/stocks/${symbol}`}><small>{symbol}</small><strong>{holdings[0].companyName} <span className="muted">›</span></strong></Link>
            <div className="home-amount">{yen(marketValue)}<small>{shares.toLocaleString("ja-JP")}株</small></div></div>
          {holdings.length===1 ? <div className="muted small">{data.accountLabels?.[holdings[0].accountBucketId] ?? holdings[0].accountBucketId}</div> : <div className="home-account">{holdings.map(holding=><div className="row spread" key={holding.accountBucketId}><span>{data.accountLabels?.[holding.accountBucketId] ?? holding.accountBucketId} · {holding.shares}株</span><b>{yen(holding.marketValue)}</b></div>)}</div>}
        </article>;
      })}
    </div></section>
    <Link className="button" to="/today/executions">＋ 取引を記録</Link>
    <div className="row spread"><Link className="home-link" to="/transactions">取引履歴 ›</Link><Link className="home-link" to="/today">今日の提案を見る →</Link></div></div></div>
  </div>;
}

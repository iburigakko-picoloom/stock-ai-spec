import { type ReactNode, useMemo } from "react";
import { Link } from "react-router-dom";
import { Metric, PageHeader, RuntimeBanner, StatePanel, dateTime, yen } from "../components";
import { useApiData } from "../hooks";
import type { HoldingView, HomeResponse } from "../types";
import { DailyPanel, DailyStatusLink } from "../mobile/DailyPanel";
import { ProposalReadiness } from "../mobile/ProposalReadiness";
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

  if ((loading && !data) || error) return <div className="page"><PageHeader eyebrow="実際の状態" title="ホーム" /><StatePanel tone={loading ? "neutral" : "error"} title={loading ? "実資産を読み込んでいます" : "資産データを取得できません"} detail={error} /></div>;
  if (!data?.portfolio) {
    return (
      <div className="page">
        <PageHeader eyebrow="実際の状態" title="ホーム" />
        {savedAt && <p role="status">{dateTime(savedAt, true)} JSTの保存済み表示・閲覧用。最新情報を確認中…</p>}
        {data?.runtimeMode === "DETERMINISTIC_FIXTURE_ONLY" && <RuntimeBanner mode={data.runtimeMode} />}
        <DailyPanel />
        {(loading || !isAndroid()) && <StatePanel title={loading ? "最新の資産状態を確認中です" : "表示できる資産台帳がありません"} detail={loading ? "登録状態を確認しています。" : "入力の保存後に、残高の確定が必要です。"} />}
        {!loading && <ProposalReadiness />}
        {isAndroid() && <Link className="button button--secondary" to="/holdings">実保有を登録・編集</Link>}
        {!isAndroid() && <Link className="button button--secondary" to="/settings">登録・口座の設定を確認</Link>}
      </div>
    );
  }

  return <div className="page home-page">
    <PageHeader title="ホーム" actions={<DailyStatusLink />} />
    {loading && <p role="status" className="setting-footnote">{savedAt ? `${dateTime(savedAt, true)} JSTの保存済み表示・閲覧用。` : "前回の表示です・"}更新を確認中…</p>}
    {data.runtimeMode === "DETERMINISTIC_FIXTURE_ONLY" && <RuntimeBanner mode={data.runtimeMode} />}
    <p className="home-caption">実際の資産</p>
    <section className="mock-card" aria-label="資産残高">
      <div className="home-assets-total"><span>総資産</span><strong>{yen(data.portfolio.totalAssets)}</strong></div>
      <div className="home-assets-breakdown"><Metric label="株式" value={yen(data.portfolio.equityValue)} /><Metric label="現金" value={yen(data.portfolio.cashValue)} /></div>
      <small>{data.initialLedger?.referencePriceDate ? `株価：${data.initialLedger.referencePriceDate} 終値` : `残高：${dateTime(data.portfolio.asOf, true)} JST`}</small>
      <div className="home-assets-cash"><div><span>現金総額</span><b>{yen(data.portfolio.cashValue)}</b></div>
        {data.portfolio.reservedCash !== undefined && <div><span>確保中</span><b>{yen(data.portfolio.reservedCash)}</b></div>}
        {data.portfolio.buyingPower !== undefined && <div><span>運用可能</span><b>{yen(data.portfolio.buyingPower)}</b></div>}
      </div>
    </section>
    <div className="home-held-heading"><h2>保有株 <small>{groups.length}銘柄</small></h2><Link className="quiet-link" to="/assets">資産を管理 ›</Link></div>
    <section className="mock-card" aria-label="実保有">
      {groups.length === 0 ? <p className="setting-footnote">保有株はありません。</p> : groups.map(([symbol, holdings]) => {
        const marketValue=holdings.reduce((sum,item)=>sum+Number(item.marketValue),0);
        const shares=holdings.reduce((sum,item)=>sum+item.shares,0);
        return <article className="home-held" key={symbol}>
          <div className="home-held-title"><Link state={{from:"/"}} to={`/stocks/${symbol}`}><small>{symbol}</small><strong>{holdings[0].companyName} ›</strong></Link>
            <div className="home-held-amount">{yen(marketValue)}<small>{shares.toLocaleString("ja-JP")}株</small></div></div>
          {holdings.map(holding=><div className="home-held-account" key={holding.accountBucketId}><span>{holding.accountBucketId}{holdings.length>1 && ` · ${holding.shares}株`}</span>{holdings.length>1 && <span>{yen(holding.marketValue)}</span>}</div>)}
        </article>;
      })}
    </section>
    <Link className="button button--primary" to="/today/executions">＋ 取引を記録</Link>
    <div className="link-row"><Link className="quiet-link" to="/transactions">取引履歴 ›</Link><Link className="quiet-link" to="/today">今日の提案を見る →</Link></div>
  </div>;
}

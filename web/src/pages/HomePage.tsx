import { type ReactNode, useMemo } from "react";
import { Link } from "react-router-dom";
import { ActionBadge, Metric, PageHeader, RuntimeBanner, StatePanel, dateTime, yen } from "../components";
import { useApiData } from "../hooks";
import type { HoldingView, HomeResponse } from "../types";
import { DailyPanel } from "../mobile/DailyPanel";

export function HomePage(): ReactNode {
  const { data, error, loading } = useApiData<HomeResponse>("/api/v1/home");
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
        <RuntimeBanner mode={data?.runtimeMode || "UNCONFIGURED"} />
        <DailyPanel />
        <StatePanel title="資産データが未登録です" detail={data?.blockingReason || "保有株・口座区分・現金残高を登録すると、実資産を表示します。"} />
        <Link className="button button--secondary" to="/settings">登録・口座の設定を確認</Link>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader eyebrow="実際の状態" title="ホーム" meta={`更新 ${dateTime(data.portfolio.asOf)} JST`} />
      {loading && <p role="status">前回の表示です・更新を確認中…</p>}
      <RuntimeBanner mode={data.runtimeMode} />
      <DailyPanel />
      {data.initialLedger && <p className="explain">初回台帳の残高です。口座・保有の入力欄を編集しても、この台帳は更新されません。{data.initialLedger.referencePriceDate && `株価は${data.initialLedger.referencePriceDate}の日足終値を参照しています。`}</p>}
      <section className="hero-balance" aria-labelledby="assets-title">
        <p id="assets-title">総資産</p>
        <strong>{yen(data.portfolio.totalAssets)}</strong>
        <div className="metric-grid metric-grid--2">
          <Metric label="現金" value={yen(data.portfolio.cashValue)} />
          <Metric label="株式" value={yen(data.portfolio.equityValue)} />
        </div>
        <Link className="button button--primary home-proposal-link" to="/today">今日の提案を確認<span aria-hidden="true">›</span></Link>
      </section>

      <section className="section">
        <div className="section-title">
          <div><span>ACTUAL HOLDINGS</span><h2>実保有</h2></div>
          <small>約定を記録するまで保有は変わりません。</small>
        </div>
        {groups.length === 0 ? (
          <StatePanel title="保有株はありません" detail="AI提案だけでは実保有は変わりません。" />
        ) : (
          <div className="holding-list">
            {groups.map(([symbol, holdings]) => {
              const marketValue = holdings.reduce((sum, item) => sum + Number(item.marketValue), 0);
              const shares = holdings.reduce((sum, item) => sum + item.shares, 0);
              if (holdings.length === 1) return <Link className="holding-summary-row" state={{ from: "/" }} to={`/stocks/${symbol}`} key={symbol}>
                <div><strong>{holdings[0].companyName}</strong><span>{holdings[0].accountBucketId}</span>{holdings[0].latestAction && <ActionBadge action={holdings[0].latestAction} />}</div>
                <strong>{shares.toLocaleString("ja-JP")}株</strong><b>{yen(marketValue)}</b><span className="row-chevron" aria-hidden="true">›</span>
              </Link>;
              return (
                <details className="holding-group" key={symbol} open={holdings.length === 1}>
                  <summary>
                    <div>
                      <strong>{holdings[0].companyName}</strong>
                      <span>{symbol} ・ 合計 {shares.toLocaleString("ja-JP")}株</span>
                    </div>
                    <b>{yen(marketValue)}</b>
                    <span className="disclosure-chevron" aria-hidden="true">⌄</span>
                  </summary>
                  {holdings.map((holding) => (
                    <Link className="holding-row" state={{ from: "/" }} to={`/stocks/${holding.symbol}`} key={holding.accountBucketId}>
                      <div>
                        <span>{holding.accountBucketId}</span>
                        <strong>{holding.shares.toLocaleString("ja-JP")}株</strong>
                      </div>
                      <div className="holding-row__right">
                        <span>{yen(holding.marketValue)}</span>
                        {holding.latestAction && <ActionBadge action={holding.latestAction} />}
                      </div>
                    </Link>
                  ))}
                </details>
              );
            })}
          </div>
        )}
      </section>
      <details className="metadata-details">
        <summary>実状態を正本にしています</summary>
        <p className="explain">実約定を記録するまで、提案や保存済み判断は保有に反映されません。</p>
      </details>
    </div>
  );
}

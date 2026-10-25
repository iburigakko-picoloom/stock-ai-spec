import { type ReactNode, useMemo } from "react";
import { Link } from "react-router-dom";
import { ActionBadge, Metric, PageHeader, RuntimeBanner, StatePanel, dateTime, yen } from "../components";
import { useApiData } from "../hooks";
import type { HoldingView, HomeResponse } from "../types";
import { DailyPanel } from "../mobile/DailyPanel";
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

  return (
    <div className="page">
      <PageHeader eyebrow="実際の状態" title="ホーム" meta={`更新 ${dateTime(data.portfolio.asOf)} JST`} />
      {loading && <p role="status">{savedAt ? `${dateTime(savedAt, true)} JSTの保存済み表示・閲覧用。` : "前回の表示です・"}更新を確認中…</p>}
      <RuntimeBanner mode={data.runtimeMode} />
      <DailyPanel />
      {data.initialLedger && <p className="explain">初回登録時点の残高です。現金は設定、保有株は「実保有」から更新できます。{data.initialLedger.referencePriceDate && `株価は${data.initialLedger.referencePriceDate}の日足終値を参照しています。`}</p>}
      <section className="hero-balance" aria-labelledby="assets-title">
        <p id="assets-title">総資産</p>
        <strong>{yen(data.portfolio.totalAssets)}</strong>
        <div className="metric-grid metric-grid--2">
          <Metric label="現金残高" value={yen(data.portfolio.cashValue)} />
          <Metric label="株式" value={yen(data.portfolio.equityValue)} />
        </div>
        {data.portfolio.reservedCash !== undefined && <p className="explain">確保中 {yen(data.portfolio.reservedCash)} · 買付余力 {yen(data.portfolio.buyingPower ?? "0")}</p>}
        <Link className="button button--primary home-proposal-link" to="/today">今日の提案を確認<span aria-hidden="true">›</span></Link>
      </section>

      <section className="section">
        <div className="section-title">
          <div><span>ACTUAL HOLDINGS</span><h2>実保有</h2></div>
          <small>約定を記録するまで保有は変わりません。</small>
        </div>
        {isAndroid() && <Link className="button button--secondary" to="/holdings">保有株を追加・編集</Link>}
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

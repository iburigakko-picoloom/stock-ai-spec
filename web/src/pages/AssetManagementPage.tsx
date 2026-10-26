import { Link, useParams } from "react-router-dom";
import { PageHeader, StatePanel, yen } from "../components";
import { useApiData } from "../hooks";
import type { HomeResponse } from "../types";
import { CurrentAccountPanel } from "../mobile/CurrentAccountPanel";

export function AssetManagementPage() {
  const { section } = useParams();
  return <div className="page">
    <PageHeader title={section === "cash" ? "現金残高の変更" : "資産管理"} backTo={section ? "/assets" : "/"} />
    {section === "cash" ? <CurrentAccountPanel mode="cash" /> : <><AssetOverview /><nav className="two-actions" aria-label="資産の管理">
      <Link className="button button--secondary" to="/assets/cash">現金残高の変更</Link>
      <Link className="button button--secondary" to="/holdings">保有の訂正</Link>
      <Link className="button button--secondary" to="/holdings?initial=1">初回資産登録</Link>
      <Link className="button button--secondary" to="/assets/history">残高・修正履歴</Link>
      <Link className="button button--secondary" to="/today/executions">取引を記録</Link>
      <Link className="button button--secondary" to="/transactions">取引履歴</Link>
    </nav><AssetPositions /></>}
  </div>;
}

function AssetOverview() {
  const {data,error,loading}=useApiData<HomeResponse>("/api/v1/home");
  if (error) return <StatePanel tone="error" title="残高を取得できません" detail={error} />;
  const balance=data?.portfolio;
  return <section className="mock-card"><dl className="summary-list"><div><dt>実資産</dt><dd>{loading && !data ? "確認中…" : yen(balance?.totalAssets)}</dd></div><div><dt>株式 / 現金</dt><dd>{yen(balance?.equityValue)} / {yen(balance?.cashValue)}</dd></div><div><dt>確保中</dt><dd>{yen(balance?.reservedCash)}</dd></div><div><dt>運用可能現金</dt><dd>{yen(balance?.buyingPower)}</dd></div></dl></section>;
}
function AssetPositions() {
  const {data}=useApiData<HomeResponse>("/api/v1/home");
  return <section className="mock-card" aria-label="保有一覧">{data?.holdings.length ? data.holdings.map(row=><Link className="menu-link" to={`/stocks/${row.symbol}`} state={{from:"/"}} key={`${row.symbol}:${row.accountBucketId}`}><span>{row.symbol} {row.companyName}<small className="block">{row.accountBucketId}</small></span><span>{row.shares}株<small className="block">{yen(row.averageAcquisitionPrice)}</small></span></Link>) : <p className="setting-footnote">保存済みの保有株はありません。</p>}</section>;
}

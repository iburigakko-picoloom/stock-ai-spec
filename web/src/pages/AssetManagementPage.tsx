import { Link, useParams } from "react-router-dom";
import { PageHeader, StatePanel, currency as yen } from "../components";
import { KV } from "../Adopted";
import { useApiData } from "../hooks";
import type { HomeResponse } from "../types";
import { isAndroid } from "../mobile/native";
import { CurrentAccountPanel } from "../mobile/CurrentAccountPanel";

export function AssetManagementPage() {
  const { section } = useParams();
  return <div className="page">
    <PageHeader title={section === "cash" ? "現金残高の変更" : "資産管理"} backTo={section ? "/assets" : "/"} />
    {section === "cash" ? <CurrentAccountPanel mode="cash" /> : <AssetBody />}</div>;
}

function AssetBody() {
  const {data,error,loading}=useApiData<HomeResponse>(isAndroid() ? "/api/v1/home/ledger" : "/api/v1/home");
  return <div className="subscreen stack"><AssetOverview data={data} error={error} loading={loading} /><nav className="subgrid" aria-label="資産の管理">
      <Link className="button button--secondary" to="/assets/cash">現金残高の変更</Link>
      <Link className="button button--secondary" to="/holdings">保有の訂正</Link>
      <Link className="button button--secondary" to="/holdings?initial=1">初回資産登録</Link>
      <Link className="button button--secondary" to="/assets/history">残高・修正履歴</Link>
      <Link className="button button--secondary" to="/today/executions">取引を記録</Link>
      <Link className="button button--secondary" to="/transactions">取引履歴</Link>
    </nav><AssetPositions data={data} error={error} loading={loading} /></div>;
}

function AssetOverview({data,error,loading}:{data:HomeResponse|null;error:string|null;loading:boolean}) {
  if (error) return <StatePanel tone="error" title="残高を取得できません" detail={error} />;
  const balance=data?.portfolio;
  return <section className="card"><KV label="実資産" value={loading && !data ? "確認中…" : yen(balance?.totalAssets)} /><KV label="株式 / 現金" value={`${yen(balance?.equityValue)} / ${yen(balance?.cashValue)}`} /><KV label="確保中" value={yen(balance?.reservedCash)} /><KV label="運用可能現金" value={yen(balance?.buyingPower)} /></section>;
}
function AssetPositions({data,error,loading}:{data:HomeResponse|null;error:string|null;loading:boolean}) {
  return <section className="card" aria-label="保有一覧">{error ? <p className="setting-footnote">保有情報を確認できません。</p> : loading && !data ? <p className="setting-footnote">保有情報を確認しています。</p> : data?.holdings.length ? data.holdings.map(row=><Link className="subrow" to={`/stocks/${row.symbol}`} state={{from:"/"}} key={`${row.symbol}:${row.accountBucketId}`}><span>{row.symbol} {row.companyName} / {row.accountBucketId}</span><strong>{row.shares}株 / {yen(row.averageAcquisitionPrice)}</strong></Link>) : <p className="setting-footnote">保存済みの保有株はありません。</p>}</section>;
}

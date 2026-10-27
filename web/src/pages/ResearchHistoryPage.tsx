import { useLocation, useParams } from "react-router-dom";
import { PageHeader, StatePanel, dateTime } from "../components";
import { Link } from "react-router-dom";
import { useApiData } from "../hooks";
import { CompanyResearchPanel } from "../mobile/CompanyResearchPanel";
import type { StockDetail } from "../types";
export function ResearchHistoryPage() {
  const location = useLocation();
  const { symbol = "" } = useParams();
  const { data, loading, error, savedAt, reload } = useApiData<StockDetail>(`/api/v1/stocks/${symbol}`);
  return <div className="page"><PageHeader title="調査履歴" meta={symbol} backTo={`/stocks/${symbol}`} backState={location.state} />
    {error ? <StatePanel tone="error" title="調査履歴を取得できません" detail={error} /> : !data ? <StatePanel title="調査履歴を読み込んでいます" /> : <>{(loading || savedAt) && <p role="status" className="setting-footnote">{savedAt ? `${dateTime(savedAt,true)}の保存済み表示・閲覧用。` : "前回の表示・閲覧用。"}更新を確認中…</p>}<CompanyResearchPanel symbol={symbol} forecast={data.forecast ?? null} runs={data.researchRuns ?? []} records={data.chatgptResearch ?? []} onChanged={reload} readOnly={loading || !!savedAt} /></>}
    {data && <div className="subscreen analysis-domain"><Link className="button ghost" to={`/stocks/${symbol}`} state={location.state}>銘柄詳細に戻る</Link></div>}
  </div>;
}

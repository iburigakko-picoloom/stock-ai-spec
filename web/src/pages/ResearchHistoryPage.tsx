import { useLocation, useParams } from "react-router-dom";
import { PageHeader, StatePanel } from "../components";
import { useApiData } from "../hooks";
import { CompanyResearchPanel } from "../mobile/CompanyResearchPanel";
import type { StockDetail } from "../types";
export function ResearchHistoryPage() {
  const location = useLocation();
  const { symbol = "" } = useParams();
  const { data, loading, error, reload } = useApiData<StockDetail>(`/api/v1/stocks/${symbol}`);
  return <div className="page"><PageHeader title="調査履歴" meta={symbol} backTo={`/stocks/${symbol}`} backState={location.state} />
    {error ? <StatePanel tone="error" title="調査履歴を取得できません" detail={error} /> : loading || !data ? <StatePanel title="調査履歴を読み込んでいます" /> : <CompanyResearchPanel symbol={symbol} forecast={data.forecast ?? null} runs={data.researchRuns ?? []} records={data.chatgptResearch ?? []} onChanged={reload} />}
  </div>;
}

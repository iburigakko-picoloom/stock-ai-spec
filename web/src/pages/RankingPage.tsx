import { type ReactNode, useState } from "react";
import { Link } from "react-router-dom";
import { ActionBadge, PageHeader, StatePanel, TabBar } from "../components";
import { useApiData } from "../hooks";
import type { RankingRow } from "../types";
import { isAndroid } from "../mobile/native";
import { Rankings } from "../mobile/Rankings";

const tabs = [
  ["overall", "総合"],
  ["5d", "5日"],
  ["20d", "20日"],
  ["morning", "前場"],
] as const;

export function RankingPage(): ReactNode {
  return isAndroid() ? <Rankings /> : <WebRankingPage />;
}

function WebRankingPage(): ReactNode {
  const [rankType, setRankType] = useState("overall");
  const [search, setSearch] = useState("");
  const { data, error, loading, savedAt } = useApiData<RankingRow[]>(`/api/v1/ranking?rankType=${rankType}&limit=50`);
  const query = search.trim().toLowerCase();
  const rows = (data || []).filter((row) => `${row.symbol}${row.company_name}`.toLowerCase().includes(query));
  return (
    <div className="page">
      <PageHeader eyebrow="銘柄を探す" title="ランキング" />
      <TabBar label="ランキング期間" options={tabs} value={rankType} onChange={setRankType} panelId="ranking-panel" />
      <div id="ranking-panel" role="tabpanel" aria-labelledby={`ranking-panel-${rankType}`}>
      <label className="search"><span className="sr-only">銘柄名・コードで検索</span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><circle cx="10" cy="10" r="7" /><path d="m15 15 6 6" /></svg><input type="search" placeholder="表示中の上位50件から検索" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      {loading && data && <p role="status">{savedAt ? `${new Date(savedAt).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })} JSTの保存済み表示・閲覧用。` : "前回の表示です・"}更新を確認中…</p>}
      <p className="explain">予測順位です。売買の提案は「今日」で確認。</p>
      {!loading && !error && !!data?.length && <p className="list-count" role="status">{rows.length}件を表示 <span>取得した上位{data.length}件が対象</span></p>}
      {loading && !data ? <StatePanel title="ランキングを読み込んでいます" /> : error ? <StatePanel tone="error" title="ランキングを取得できません" detail={error} /> : rows.length === 0 ? <StatePanel title={query && data?.length ? "検索に一致する銘柄がありません" : "このランキングはまだありません"} detail={query && data?.length ? "表示対象の上位50件を検索しています。銘柄名またはコードを変えてください。" : "保存済みの分析は「今日」で確認できます。"} /> : (
        <div className="ranking-list">
          {rows.map((row) => <Link className="ranking-row" state={{ from: "/ranking" }} key={row.ranking_id} to={`/stocks/${row.symbol}`}>
            <strong className="rank-number">{row.rank >= 1 && row.rank <= 3 && <svg className={`rank-crown rank-crown--${row.rank}`} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="m2 6 6 4 4-7 4 7 6-4-3 14H5Z" /></svg>}<span>{row.rank}位</span><small>/ {row.total_universe}</small></strong>
            <div><strong>{row.company_name}</strong><span>{row.symbol}</span></div>
            <div className="ranking-row__labels"><span className="candidate-label">{row.candidate_status}</span>{row.portfolio_action && <ActionBadge action={row.portfolio_action} />}</div>
            <span className="row-chevron" aria-hidden="true">›</span>
          </Link>)}
        </div>
      )}
      </div>
    </div>
  );
}

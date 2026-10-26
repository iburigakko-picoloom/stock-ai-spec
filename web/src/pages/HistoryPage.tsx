import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { PageHeader, StatePanel, dateTime, yen } from "../components";
import { useApiData } from "../hooks";

interface Ledger { portfolio_id: string; as_of: string; positions: { symbol: string; shares: number; account_bucket_id: string; average_acquisition_price: string }[]; cash: { account_bucket_id: string; available_cash: string; reserved_cash: string }[]; applied_execution_ids: string[] }
interface Execution { execution_id: string; executed_at: string; symbol: string; account_bucket_id: string; side: string; status: string; ordered_shares: number; filled_shares: number; average_fill_price: string | null; actual_commission: string; actual_other_cost: string; tax_withheld: string }
export function HistoryPage() {
  return useLocation().pathname === "/transactions" ? <ExecutionHistory /> : <LedgerHistory />;
}
function ExecutionHistory() {
  const { data, error, loading } = useApiData<{ records: Execution[]; appliedIds: string[] }>("/api/v1/executions");
  const [id, setId] = useState("");
  const rows = [...(data?.records ?? [])].reverse();
  const selected = rows.find(row => row.execution_id === id) ?? rows[0];
  return <div className="page"><Link className="back-link" to="/assets">← 資産管理へ</Link><PageHeader title="取引履歴" />
    {error ? <StatePanel tone="error" title="取引履歴を取得できません" detail={error} /> : loading ? <StatePanel title="取引履歴を読み込んでいます" /> : !selected ? <StatePanel title="取引記録はまだありません" /> : <>
      <label>記録を選択<select className="history-select" value={selected.execution_id} onChange={e => setId(e.target.value)}>{rows.map(row => <option key={row.execution_id} value={row.execution_id}>{dateTime(row.executed_at)} · {row.symbol} · {row.filled_shares}株</option>)}</select></label>
      <section className="section"><h2>{selected.symbol} · {selected.side === "BUY" ? "購入" : "売却"}</h2><p>{selected.account_bucket_id}</p>
        <dl className="summary-list"><div><dt>約定株数</dt><dd>{selected.filled_shares}株 / 注文 {selected.ordered_shares}株</dd></div><div><dt>平均約定単価</dt><dd>{yen(selected.average_fill_price)}</dd></div><div><dt>手数料</dt><dd>{yen(selected.actual_commission)}</dd></div><div><dt>その他費用</dt><dd>{yen(selected.actual_other_cost)}</dd></div><div><dt>源泉徴収税</dt><dd>{yen(selected.tax_withheld)}</dd></div><div><dt>残高</dt><dd>{data?.appliedIds.includes(selected.execution_id) ? "反映済み" : "未反映"}</dd></div></dl>
        <Link className="button button--secondary" to={`/stocks/${selected.symbol}`} state={{ from: "/transactions" }}>銘柄詳細</Link>
      </section></>}
  </div>;
}
function LedgerHistory() {
  const { data, error, loading } = useApiData<Ledger[]>("/api/v1/portfolio/history");
  const [id, setId] = useState("");
  const selected = data?.find(row => row.portfolio_id === id) ?? data?.[0];
  return <div className="page"><Link className="back-link" to="/assets">← 資産管理へ</Link><PageHeader title="残高・修正履歴" />
    {error ? <StatePanel tone="error" title="残高履歴を取得できません" detail={error} /> : loading ? <StatePanel title="残高履歴を読み込んでいます" /> : !selected ? <StatePanel title="残高履歴はまだありません" /> : <>
      <label>保存した残高<select className="history-select" value={selected.portfolio_id} onChange={e => setId(e.target.value)}>{data?.map(row => <option key={row.portfolio_id} value={row.portfolio_id}>{dateTime(row.as_of, true)} · {row.positions.length}保有</option>)}</select></label>
      <p className="setting-footnote">初回登録・残高修正・約定反映を含む直近100件の台帳です。</p>
      <section className="section"><h2>保存時の現金</h2>{selected.cash.map(row => <div key={row.account_bucket_id}><h3>{row.account_bucket_id}</h3><p>現金 {yen(row.available_cash)} · うち確保中 {yen(row.reserved_cash)}</p></div>)}</section>
      <section className="section"><h2>保存時の保有</h2>{selected.positions.length ? selected.positions.map(row => <div className="list-row" key={`${row.symbol}:${row.account_bucket_id}`}><strong>{row.symbol} · {row.shares}株</strong><p>{row.account_bucket_id} · 取得単価 {yen(row.average_acquisition_price)}</p></div>) : <p>保有なし</p>}</section>
    </>}
  </div>;
}

import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ApiError, apiPost } from "../api";
import { PageHeader, StatePanel, dateTime } from "../components";
import { useApiData } from "../hooks";
import type { AppStatus } from "../types";
import { DailyPanel } from "../mobile/DailyPanel";
import { Field, KV } from "../Adopted";

interface Conflict { conflict_id: string; code: string; message: string; row_number: number }
interface ExecutionPreview { preview_id: string; conflicts: Conflict[]; execution_payloads: string[] }
interface PositionDifference { symbol: string; account_bucket_id: string; ledger_shares: number; imported_shares: number }
interface CashDifference { account_bucket_id: string; ledger_available_cash: string; imported_available_cash: string; ledger_reserved_cash: string; imported_reserved_cash: string }
interface PositionPreview { preview_id: string; differences: PositionDifference[]; cash_differences: CashDifference[]; imported_as_of: string }

export function DataOperationsPage(): ReactNode {
  const path = useLocation().pathname;
  const [kind, setKind] = useState<"executions" | "positions">("executions");
  const [csv, setCsv] = useState("");
  const [executionPreview, setExecutionPreview] = useState<ExecutionPreview | null>(null);
  const [positionPreview, setPositionPreview] = useState<PositionPreview | null>(null);
  const [accepted, setAccepted] = useState<string[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sequence = useRef(0);
  const mounted = useRef(true);
  const flight = useRef(false);
  const attempt = useRef<{ path: string; body: unknown } | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmLocked, setConfirmLocked] = useState(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  function invalidate(): void {
    sequence.current++; setExecutionPreview(null); setPositionPreview(null);
    setAccepted([]); setConfirmed(false); setMessage(null); setError(null); attempt.current = null; setConfirmLocked(false);
  }
  async function preview(): Promise<void> {
    if (flight.current) return;
    invalidate(); const ticket = sequence.current;
    flight.current = true; setBusy(true);
    try {
      const value = await apiPost<ExecutionPreview | PositionPreview>(`/api/v1/imports/${kind}/preview`, { csvText: csv });
      if (!mounted.current || ticket !== sequence.current) return;
      if (kind === "executions") setExecutionPreview(value as ExecutionPreview);
      else setPositionPreview(value as PositionPreview);
    } catch (reason) {
      if (mounted.current && ticket === sequence.current) setError(reason instanceof Error ? reason.message : "CSVを確認できませんでした");
    } finally { flight.current = false; if (mounted.current) setBusy(false); }
  }
  async function confirmImport(): Promise<void> {
    if (flight.current || (!executionPreview && !positionPreview)) return;
    if (!attempt.current) attempt.current = executionPreview ? {
      path: `/api/v1/imports/executions/${executionPreview.preview_id}/confirm`,
      body: { acceptedConflictIds: [...accepted] },
    } : {
      path: `/api/v1/imports/positions/${positionPreview!.preview_id}/confirm`,
      body: { nextPortfolioId: `reconciled-${crypto.randomUUID()}`, confirmAllDifferences: confirmed },
    };
    const request = attempt.current;
    setConfirmLocked(true);
    flight.current = true; setBusy(true); setError(null);
    try {
      const result = await apiPost<{ imported?: number; skipped?: number }>(request.path, request.body);
      if (!mounted.current) return;
      setMessage(executionPreview ? `${result.imported}件を追加。${result.skipped}件は未追加です。` : "確認した口座状態を保存しました。");
      setExecutionPreview(null); setPositionPreview(null); attempt.current = null; setConfirmLocked(false);
    } catch (reason) {
      if (!mounted.current) return;
      if (reason instanceof ApiError && reason.status === 409) {
        invalidate(); setError(`${reason.message} 差分を再確認してください。`);
      } else setError(reason instanceof ApiError ? reason.message : "保存結果を確認できません。同じ内容で再試行してください。");
    } finally { flight.current = false; if (mounted.current) setBusy(false); }
  }

  return (
    <div className="page">
      <PageHeader backTo="/settings" title={path.endsWith("/csv") ? "CSV取り込み" : path.endsWith("/logs") ? "処理状況・実行記録" : "データ・運用状態"} />
      <div className="subscreen advanced-domain">
      {!path.endsWith("/csv") && <OperationStatus />}<div hidden={path.endsWith("/logs")} className="card stack"><section className="advanced-section">
        <h3 className="section-title">CSV入力</h3>
        <Field label="CSVの種類"><select className="input" disabled={busy} value={kind} onChange={e=>{invalidate();setKind(e.target.value as "executions"|"positions");}}><option value="executions">約定CSV</option><option value="positions">口座状態CSV</option></select></Field>
        <Field label="CSV"><textarea aria-label="CSV内容" className="input" rows={7} value={csv} onChange={(event) => { if (!flight.current || !attempt.current) { invalidate(); setCsv(event.target.value); } }} placeholder={kind === "executions" ? "execution_id,decision_id,executed_at,..." : "as_of,record_type,symbol,account_bucket_id,...,available_cash,reserved_cash"} /></Field>
        <button className="button" disabled={busy || !csv.trim()} onClick={() => void preview()}>書き込まずに差分を確認</button>
      </section>
      <section className="advanced-section"><h3 className="section-title">検証</h3><KV label="状態" value={busy ? "処理中" : executionPreview || positionPreview ? "差分を作成済み" : csv ? "未検証" : "入力待ち"} /><KV label="形式" value={kind==="executions" ? "約定CSV" : "口座状態CSV"} /></section>
      <section className="advanced-section"><h3 className="section-title">差分プレビュー</h3>{!executionPreview && !positionPreview && <KV label="差分" value="未作成" />}

      {executionPreview && <section className="section preview-panel">
        <h2>約定preview</h2><p>候補 {executionPreview.execution_payloads.length}件 / conflict {executionPreview.conflicts.length}件</p>
        {executionPreview.conflicts.map((conflict) => <label className="conflict-row" key={conflict.conflict_id}><input type="checkbox" disabled={busy || confirmLocked} checked={accepted.includes(conflict.conflict_id)} onChange={(event) => setAccepted((current) => event.target.checked ? [...current, conflict.conflict_id] : current.filter((item) => item !== conflict.conflict_id))} /><span><strong>{conflict.code}</strong> 行{conflict.row_number}: {conflict.message}</span></label>)}
        <button className="button button--primary" disabled={busy} onClick={() => void confirmImport()}>確認した行だけ追加</button>
      </section>}

      {positionPreview && <section className="section preview-panel">
        <h2>保有差分preview</h2><p>取込時点 {positionPreview.imported_as_of}</p>
        {positionPreview.differences.map((difference) => <div className="difference-row" key={`${difference.symbol}-${difference.account_bucket_id}`}><span>{difference.symbol} / {difference.account_bucket_id}</span><strong>{difference.ledger_shares}株 → {difference.imported_shares}株</strong></div>)}
        {positionPreview.cash_differences.map((difference) => <div className="difference-row" key={`cash-${difference.account_bucket_id}`}><span>現金 / {difference.account_bucket_id}</span><strong>{difference.ledger_available_cash}円（予約 {difference.ledger_reserved_cash}円） → {difference.imported_available_cash}円（予約 {difference.imported_reserved_cash}円）</strong></div>)}
        <label className="checkbox"><input type="checkbox" disabled={busy || confirmLocked} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />全差分を確認し、新しい実状態として追加する</label>
        <button className="button button--primary" disabled={busy || !confirmed} onClick={() => void confirmImport()}>差分確認済みで反映</button>
      </section>}
      </section><section className="advanced-section"><h3 className="section-title">反映</h3><KV label="反映先" value={kind==="executions" ? "実際の約定記録" : "確認した保有・現金"} /><button className="button secondary" disabled={busy} onClick={invalidate}>取り消す</button></section>
      {message && <StatePanel title={message} detail="既存recordは上書きしていません。" />}
      {error && <StatePanel tone="error" title="処理を完了できません" detail={error} />}
      </div></div>
    </div>
  );
}

function OperationStatus(): ReactNode {
  const status = useApiData<AppStatus>("/api/v1/status");
  const jobs = useApiData<{run_id:string;started_at:string;business_date:string;stage:string;status:string;reason_code:string|null}[]>("/api/v1/jobs");
  const [jobsFilter,setJobsFilter]=useState("all");
  return (<div>
      <div className="card stack"><section className="advanced-section"><h3 className="section-title">処理状態</h3>{status.loading ? <StatePanel title="運用状態を確認しています" /> : status.error ? <StatePanel tone="error" title="運用状態を取得できません" detail={status.error} /> : status.data && <><KV label="状態" value={status.data.pipelineState} /><KV label="停止理由" value={status.data.blockingReason || "なし"} /><KV label="対象日" value={status.data.businessDate} /></>}</section>
      <section className="advanced-section"><h3 className="section-title">不足データ</h3><p className="small muted">{status.data?.blockingReason || "保存した停止理由はありません。"}</p><Link className="button secondary" to="/settings?edit=repair">不足データを修復</Link></section>
      <section className="advanced-section"><h3 className="section-title">実行記録</h3><Field label="表示"><select className="input" value={jobsFilter} onChange={e=>setJobsFilter(e.target.value)}><option value="all">すべて</option><option value="attention">不足・保留</option></select></Field>{jobs.error ? <p role="alert">実行記録を取得できません。</p> : <table className="subtable"><thead><tr><th>時刻</th><th>状態・処理</th><th>対象</th></tr></thead><tbody>{jobs.data?.filter(item=>jobsFilter==="all" || ["BLOCKED","FAILED"].includes(item.status)).map(item=><tr key={item.run_id}><td>{dateTime(item.started_at)}</td><td>{item.status}<small className="block">{item.stage}</small>{item.reason_code && <small className="block">{item.reason_code}</small>}</td><td>{item.business_date}</td></tr>)}</tbody></table>}{!jobs.loading && !jobs.data?.length && <p className="small muted">保存した実行記録はまだありません。</p>}<DailyPanel compact /></section>
      <section className="advanced-section"><h3 className="section-title">再確認</h3><button className="button secondary" onClick={()=>{status.reload();jobs.reload();}}>記録を再確認</button><div className="subactions"><Link className="button secondary" to="/settings?edit=repair">データ修復</Link><Link className="button secondary" to="/settings?edit=model">モデル管理</Link></div></section></div>

      </div>);
}

import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { PageHeader, StatePanel, dateTime, currency as yen } from "../components";
import { Field, FormGroup, KV } from "../Adopted";
import { ManualExecutionPage } from "./ManualExecutionPage";
import type { ProposalLine } from "../types";

interface DecisionLine {
  proposal_line_id: string;
  selected_target_shares: number;
}

interface SavedDecision {
  decision_id: string;
  version: number;
  lines: DecisionLine[];
}

type ExecutionLine=Pick<ProposalLine,"lineId"|"symbol"|"companyName"|"accountBucketId"|"currentShares"|"referencePrice">;
interface ExecutionContext {
  businessDate:string;
  proposal:{proposalId:string;asOf:string;lines:ExecutionLine[]}|null;
  decision:SavedDecision|null;
  accountLabels:Record<string,string>;
}

interface EntryState {
  status: string;
  side: "BUY" | "SELL";
  orderedShares: number;
  filledShares: number;
  executedAt: string;
  price: string;
  commission: string;
  otherCost: string;
  taxWithheld: string;
  confirmDifference: boolean;
}

function localDateTimeValue(value: Date): string {
  const pad = (part: number): string => part.toString().padStart(2, "0");
  const milliseconds = value.getMilliseconds().toString().padStart(3, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}:${pad(value.getSeconds())}.${milliseconds}`;
}

const initialEntry: EntryState = {
  status: "open",
  side: "BUY",
  orderedShares: 0,
  filledShares: 0,
  executedAt: "",
  price: "",
  commission: "0",
  otherCost: "0",
  taxWithheld: "0",
  confirmDifference: false,
};

export function ExecutionPage(): ReactNode {
  const [params] = useSearchParams();
  const applyOnly=params.has("apply");
  const location = useLocation();
  const [context,setContext]=useState<ExecutionContext|null>(null);
  const [loadingDecision, setLoadingDecision] = useState(true);
  const [selectedLine,setSelectedLine]=useState("");
  const [entries, setEntries] = useState<Record<string, EntryState>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [recorded, setRecorded] = useState<Record<string, boolean>>({});
  const [applied, setApplied] = useState(false);
  const pending = useRef(false);
  const attempts = useRef(new Map<string, { key: string; id: string; confirmed: boolean }>());
  const [nextAsOf, setNextAsOf] = useState(localDateTimeValue(new Date()));
  const proposal = context?.proposal;
  const decision=context?.decision;

  useEffect(() => {
    if(applyOnly || params.has("manual")){setLoadingDecision(false);return;}
    let active=true;
    apiGet<ExecutionContext>("/api/v1/execution-context")
      .then(value=>{if(active)setContext(value);})
      .catch((reason: unknown) => {if(active)setLoadError(reason instanceof Error ? reason.message : "判断を取得できません");})
      .finally(() => {if(active)setLoadingDecision(false);});
    return ()=>{active=false;};
  }, [applyOnly, params]);

  if (!applyOnly && (params.has("manual") || (!loadingDecision && !loadError && (!proposal || !decision)))) return <ManualExecutionPage />;

  if (!applyOnly && (loadingDecision || loadError || !proposal || !decision)) {
    const manualParams = new URLSearchParams({ manual: "1" });
    const symbol = params.get("symbol");
    if (symbol) manualParams.set("symbol", symbol);
    return <div className="page"><Link className="back-link" to="/today">← 今日へ戻る</Link><PageHeader title="実行結果を記録" /><StatePanel tone={loadError ? "error" : "neutral"} title={loadingDecision ? "実行結果入力を準備しています" : loadError ? "入力を準備できません" : "実行待ちの保存済み判断がありません"} detail={loadError} /><Link className="button button--secondary" to={`/today/executions?${manualParams}`} state={location.state}>判断を使わず取引を入力</Link></div>;
  }

  const savedDecision = decision;
  const decisionTargets = new Map((savedDecision?.lines ?? []).map((line) => [line.proposal_line_id, line.selected_target_shares]));
  const changed = (proposal?.lines ?? []).filter((line) => decisionTargets.get(line.lineId) !== line.currentShares && (!params.get("symbol") || params.get("symbol") === line.symbol));

  function entryFor(line: ExecutionLine): EntryState {
    const target = decisionTargets.get(line.lineId) ?? line.currentShares;
    return entries[line.lineId] || {
      ...initialEntry,
      side: target > line.currentShares ? "BUY" : "SELL",
      orderedShares: Math.abs(target - line.currentShares),
      filledShares: 0,
      executedAt: localDateTimeValue(new Date()),
      price: "",
    };
  }

  function patchEntry(line: ExecutionLine, patch: Partial<EntryState>): void {
    setEntries((current) => ({ ...current, [line.lineId]: { ...entryFor(line), ...patch } }));
    setRecorded(current => ({ ...current, [line.lineId]: false }));
  }

  async function record(line: ExecutionLine): Promise<void> {
    if (pending.current || !savedDecision) return;
    pending.current = true; setBusy(true);
    const entry = entryFor(line);
    setEntries(current => ({ ...current, [line.lineId]: entry }));
    const zeroFill = ["not_ordered", "open"].includes(entry.status)
      || (["cancelled", "expired"].includes(entry.status) && entry.filledShares === 0);
    setError(null);
    setMessage(null);
    try {
      const body = {
        executedAt: new Date(entry.executedAt).toISOString(),
        symbol: line.symbol,
        accountBucketId: line.accountBucketId,
        status: entry.status,
        side: entry.side,
        orderedShares: entry.orderedShares,
        filledShares: zeroFill ? 0 : entry.filledShares,
        averageFillPrice: zeroFill ? null : entry.price,
        actualCommission: zeroFill ? "0" : entry.commission,
        actualOtherCost: zeroFill ? "0" : entry.otherCost,
        taxWithheld: zeroFill ? "0" : entry.taxWithheld,
      };
      const key = JSON.stringify([savedDecision.decision_id, body]);
      let attempt = attempts.current.get(line.lineId);
      if (!attempt || attempt.key !== key) {
        attempt = { key, id: `execution-${crypto.randomUUID()}`, confirmed: false };
        attempts.current.set(line.lineId, attempt);
      }
      if (!attempt.confirmed) {
        await apiPost(`/api/v1/decisions/${savedDecision.decision_id}/executions`, {
          ...body, executionId: attempt.id, confirmDifference: entry.confirmDifference,
        });
        attempt.confirmed = true;
      }
      const reflectedAt = new Date();
      await apiPost("/api/v1/portfolio/apply-executions", {
        nextAsOf: reflectedAt.toISOString(), nextPortfolioId: `actual-${crypto.randomUUID()}`,
      });
      setNextAsOf(localDateTimeValue(reflectedAt));
      setRecorded(current => ({ ...current, [line.lineId]: true }));
      setApplied(true);
      setMessage(`${line.companyName}の実行結果を記録し、未反映の約定だけを残高へ反映しました。`);
    } catch (reason) {
      setError(`${attempts.current.get(line.lineId)?.confirmed ? "約定は記録済みです。残高反映を再試行してください。" : ""}${reason instanceof Error ? reason.message : "実行結果を記録できませんでした"}`);
    } finally { pending.current = false; setBusy(false); }
  }

  async function applyRecorded(): Promise<void> {
    if (pending.current || applied) return;
    pending.current = true; setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await apiPost("/api/v1/portfolio/apply-executions", {
        nextAsOf: new Date(nextAsOf).toISOString(),
        nextPortfolioId: `actual-${crypto.randomUUID()}`,
      });
      setMessage("記録済み約定から次の実保有状態を追加しました。");
      setApplied(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "次の実保有状態へ反映できませんでした");
    } finally { pending.current = false; setBusy(false); }
  }

  return (
    <div className="page">
      <PageHeader title={params.has("apply") ? "記録済み約定の反映" : "取引記録"} backTo={params.has("apply") ? "/transactions" : params.get("symbol") ? `/stocks/${params.get("symbol")}` : "/today"} backState={location.state} />
      <div className="subscreen stack">
      {!applyOnly && <Link className="quiet-link" to={`/today/executions?manual=1${params.get("symbol") ? `&symbol=${params.get("symbol")}` : ""}`}>提案以外の取引を記録</Link>}
      {proposal && savedDecision && <p className="small muted">{dateTime(proposal.asOf,true)} の保存済み判断 · 第{savedDecision.version}版</p>}
      {!params.has("apply") && (changed.length === 0 ? <StatePanel title="取引しない判断です" /> : changed.map((line) => {
        const target = decisionTargets.get(line.lineId) ?? line.currentShares;
        const entry = entryFor(line);
        return (
          <div className="stack execution-entry" role="group" aria-label={`${line.companyName}の取引`} key={line.lineId} hidden={line.lineId !== (changed.some(item=>item.lineId===selectedLine) ? selectedLine : changed[0]?.lineId)}>
            <section className="card"><fieldset className="account-form" disabled={busy}>
            <FormGroup title="注文">
              <Field label="銘柄"><select className="input" value={selectedLine || changed[0].lineId} onChange={e=>setSelectedLine(e.target.value)}>{changed.map(item=><option key={item.lineId} value={item.lineId}>{item.symbol} {item.companyName}</option>)}</select></Field>
              <Field label="口座"><input className="input" readOnly value={context?.accountLabels?.[line.accountBucketId] ?? line.accountBucketId} /></Field>
              <Field label="売買方向"><select className="input" value={entry.side} onChange={e=>patchEntry(line,{side:e.target.value as "BUY"|"SELL"})}><option value="BUY">買い</option><option value="SELL">売り</option></select></Field>
              <Field label="注文株数"><input className="input" type="number" min="0" step="100" value={entry.orderedShares} onChange={e=>patchEntry(line,{orderedShares:Number(e.target.value)})} /></Field>
              <Field label="実行日時"><input className="input" type="datetime-local" step="0.001" value={entry.executedAt} onChange={e=>patchEntry(line,{executedAt:e.target.value})} /></Field>
            </FormGroup><FormGroup title="約定">
            <Field label="実行状態"><select className="input" value={entry.status} onChange={e=>patchEntry(line,{status:e.target.value})}><option value="not_ordered">未注文</option><option value="open">注文済み・未約定</option><option value="partially_filled">一部約定</option><option value="filled">全約定</option><option value="cancelled">取消</option><option value="expired">失効</option></select></Field>
            {!(["not_ordered","open"].includes(entry.status)) && <>
              <Field label="約定株数"><input className="input" type="number" min="0" step="1" value={entry.filledShares} onChange={e=>patchEntry(line,{filledShares:Number(e.target.value)})} /></Field>
              <Field label="平均約定単価"><input className="input" inputMode="decimal" value={entry.price} onChange={e=>patchEntry(line,{price:e.target.value})} /></Field>
              <Field label="実手数料"><input className="input" inputMode="decimal" value={entry.commission} onChange={e=>patchEntry(line,{commission:e.target.value})} /></Field>
              <Field label="その他費用"><input className="input" inputMode="decimal" value={entry.otherCost} onChange={e=>patchEntry(line,{otherCost:e.target.value})} /></Field>
              <Field label="源泉徴収税額"><input className="input" inputMode="decimal" value={entry.taxWithheld} onChange={e=>patchEntry(line,{taxWithheld:e.target.value})} /></Field>
            </>}</FormGroup>
            <label className="checkbox"><input type="checkbox" checked={entry.confirmDifference} onChange={(event) => patchEntry(line, { confirmDifference: event.target.checked })} />保存済み判断と異なる実行を明示確認する</label>
            </fieldset></section>
            <section className="card stack"><h3 className="section-title">変更プレビュー</h3><KV label="注文" value={`${line.companyName} · ${entry.side==="BUY" ? "買い" : "売り"} ${entry.orderedShares}株`} /><KV label="今回の約定" value={`${["not_ordered","open"].includes(entry.status) ? 0 : entry.filledShares}株`} /><KV label="判断" value={`${line.currentShares} → ${target}株`} /><KV label="参考価格" value={yen(line.referencePrice)} /><p className="small muted">記録済みの約定は重ねて入力せず、今回新しく約定した分を入力してください。</p></section>
            <div className="subactions"><button className="button" disabled={busy || recorded[line.lineId]} onClick={() => void record(line)}>{recorded[line.lineId] ? "記録済み" : "この結果を記録"}</button><Link className="button secondary" to="/transactions">取引履歴</Link></div>
          </div>
        );
      }))}
      {params.has("apply") && <section className="card stack">
        <h2>残高への反映状況</h2>
        <p className="explain">記録時に未反映の約定だけを反映します。CSV取込後や反映に失敗した場合は、ここから再試行できます。</p>
        <label>次の保有状態の時点<input type="datetime-local" value={nextAsOf} disabled={busy} onChange={(event) => { setNextAsOf(event.target.value); setApplied(false); }} /></label>
        <button className="button button--primary" disabled={busy || applied} onClick={() => void applyRecorded()}>{applied ? "実保有へ反映済み" : "記録済み約定を実保有へ反映"}</button>
      </section>}
      {message && <StatePanel title={message} detail="保有と現金は確定した実約定だけから更新されます。" />}
      {error && <StatePanel tone="error" title="記録できませんでした" detail={error} />}
      {error && <Link className="quiet-link" to="/today/executions?apply=1">記録済み約定の反映を確認</Link>}
      </div>
    </div>
  );
}

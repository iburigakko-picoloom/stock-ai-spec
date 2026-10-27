import { useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiPost } from "../api";
import { useApiData } from "../hooks";
import { PageHeader, StatePanel, dateTime } from "../components";
import { Field, FormGroup } from "../Adopted";

interface Context { portfolioId: string | null; asOf: string | null; accountLabels: Record<string,string>; holdings: {symbol:string;accountBucketId:string;shares:number}[] }
function localNow() { const date=new Date(); return new Date(date.getTime()-date.getTimezoneOffset()*60_000).toISOString().slice(0,23); }
export function ManualExecutionPage() {
  const [params]=useSearchParams();
  const {data,error:loadError,loading,reload}=useApiData<Context>("/api/v1/execution-entry-context",{pollMs:0,refreshOnFocus:false});
  const [symbol,setSymbol]=useState(params.get("symbol") ?? "");
  const [account,setAccount]=useState(""); const [side,setSide]=useState("BUY");
  const [shares,setShares]=useState(""); const [price,setPrice]=useState("");
  const [commission,setCommission]=useState("0"); const [cost,setCost]=useState("0"); const [tax,setTax]=useState("0");
  const [at,setAt]=useState(localNow); const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState(""); const [error,setError]=useState(""); const [saved,setSaved]=useState(false);
  const flight=useRef(false); const attempt=useRef<{key:string;id:string}|null>(null);
  const bucket=account || Object.keys(data?.accountLabels ?? {})[0] || "";
  async function save() {
    if(flight.current || saved || loading || loadError || !data?.portfolioId || !bucket)return;
    flight.current=true;setBusy(true);setError("");setMessage("");
    try {
      const body={executedAt:new Date(at).toISOString(),symbol:symbol.trim().toUpperCase(),accountBucketId:bucket,
        side,status:"filled",orderedShares:Number(shares),filledShares:Number(shares),averageFillPrice:price,
        actualCommission:commission,actualOtherCost:cost,taxWithheld:tax};
      if(!/^[A-Z0-9]{1,10}$/.test(body.symbol) || !Number.isSafeInteger(body.filledShares) || body.filledShares<=0 || !price.trim())throw Error("銘柄コード・約定株数・単価を入力してください。");
      const key=JSON.stringify(body);
      if(attempt.current?.key!==key)attempt.current={key,id:`execution-${crypto.randomUUID()}`};
      const result=await apiPost<{applied:boolean}>("/api/v1/executions/manual",{...body,executionId:attempt.current.id});
      if(!result.applied)throw Error("取引は保存されました。残高への反映状況を確認してください。");
      setSaved(true);setMessage("取引を記録し、約定した株数と金額だけを残高へ反映しました。");
    } catch(reason){setError(reason instanceof Error ? reason.message : "取引を保存できませんでした。入力を保持しています。");}
    finally{flight.current=false;setBusy(false);}
  }
  return <div className="page"><PageHeader title="取引記録" backTo={params.get("symbol") ? `/stocks/${params.get("symbol")}` : "/today"} />
    <div className="subscreen stack execution-entry">
      {loading && <StatePanel title="口座を確認しています" detail="入力は先にできます。確認が終わるまで保存できません。" />}
      {loadError && <><StatePanel tone="error" title="口座を取得できません" detail={loadError}/><button className="button" onClick={reload}>再読み込み</button></>}
      {!loading && !loadError && !data?.portfolioId && <section className="card stack"><p>取引前の現金・保有を先に登録してください。</p><Link className="button" to="/holdings">初回資産登録</Link></section>}
      {(loading || !!loadError || !!data?.portfolioId) && <>
      <p className="small muted">実際に約定した取引を入力してください。AIの提案や判断保存は不要です。</p>
      <section className="card"><fieldset className="account-form" disabled={busy || saved}>
        <FormGroup title="取引">
          <Field label="銘柄コード"><input className="input" value={symbol} maxLength={10} placeholder="例：7203" list="held-symbols" onChange={e=>setSymbol(e.target.value)} /><datalist id="held-symbols">{[...new Set((data?.holdings ?? []).map(x=>x.symbol))].map(x=><option key={x} value={x}/>)}</datalist></Field>
          <Field label="口座"><select className="input" disabled={loading || !!loadError || !data?.portfolioId} value={bucket} onChange={e=>setAccount(e.target.value)}>{Object.entries(data?.accountLabels ?? {}).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></Field>
          <Field label="売買方向"><select className="input" value={side} onChange={e=>setSide(e.target.value)}><option value="BUY">買い</option><option value="SELL">売り</option></select></Field>
          <Field label="約定日時"><input className="input" type="datetime-local" step="0.001" value={at} onChange={e=>setAt(e.target.value)} /></Field>
          <Field label="約定株数"><input className="input" type="number" min="1" step="1" value={shares} onChange={e=>setShares(e.target.value)} /></Field>
          <Field label="平均約定単価"><input className="input" inputMode="decimal" value={price} onChange={e=>setPrice(e.target.value)} /></Field>
        </FormGroup><FormGroup title="費用・税">
          <Field label="実手数料"><input className="input" inputMode="decimal" value={commission} onChange={e=>setCommission(e.target.value)}/></Field>
          <Field label="その他費用"><input className="input" inputMode="decimal" value={cost} onChange={e=>setCost(e.target.value)}/></Field>
          <Field label="源泉徴収税額"><input className="input" inputMode="decimal" value={tax} onChange={e=>setTax(e.target.value)}/></Field>
        </FormGroup>
      </fieldset></section>
      <p className="small muted">残高の基準：{data?.asOf ? dateTime(data.asOf,true) : "—"}。既に残高に含まれる取引は重ねて登録しないでください。</p>
      <div className="subactions"><button className="button" disabled={busy || saved || loading || !!loadError || !data?.portfolioId || !bucket} onClick={()=>void save()}>{busy ? "取引と残高を保存中…" : saved ? "記録済み" : "取引を記録"}</button><Link className="button secondary" to="/transactions">取引履歴</Link></div>
      {saved && <button className="button secondary" onClick={()=>{setSaved(false);setShares("");setPrice("");setAt(localNow());setMessage("");attempt.current=null;reload();}}>別の取引を入力</button>}
      </>}
      {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}
    </div></div>;
}

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "./api";
import { dateTime } from "./components";

interface Memo {symbol:string;text:string;revision:string|null;updatedAt:string|null}
function checked(value:Memo,symbol:string):Memo {
  if(!value || value.symbol!==symbol || typeof value.text!=="string"
    || (value.revision!==null && (typeof value.revision!=="string" || !/^[a-f0-9]{64}$/.test(value.revision)))
    || (value.updatedAt!==null && typeof value.updatedAt!=="string"))throw new Error("メモの保存内容を確認できませんでした。");
  return value;
}

export function StockMemo({symbol}:{symbol:string}) {
  const [base,setBase]=useState<Memo|null>(null);
  const [draft,setDraft]=useState("");
  const [readSequence,setReadSequence]=useState(0);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const [latest,setLatest]=useState<Memo|null>(null);
  useEffect(()=>{
    let active=true;setBase(null);setDraft("");setError("");setMessage("");setLatest(null);
    void apiGet<Memo>("/api/v1/stocks/"+encodeURIComponent(symbol)+"/note")
      .then(reply=>{const value=checked(reply,symbol);if(active){setBase(value);setDraft(value.text);}})
      .catch(reason=>{if(active)setError(reason instanceof Error ? reason.message : "メモを読み込めませんでした。");});
    return ()=>{active=false;};
  },[symbol,readSequence]);
  async function save(){
    if(!base || busy)return;
    setBusy(true);setError("");setMessage("");setLatest(null);
    try{
      const saved=checked(await apiPost<Memo>("/api/v1/stocks/"+encodeURIComponent(symbol)+"/note",{text:draft,expectedRevision:base.revision}),symbol);
      setBase(saved);setDraft(saved.text);setMessage("メモを保存しました。");
    }catch(reason){
      setError(reason instanceof Error ? reason.message : "メモを保存できませんでした。入力は残っています。");
      try{const current=checked(await apiGet<Memo>("/api/v1/stocks/"+encodeURIComponent(symbol)+"/note"),symbol);if(current.revision!==base.revision)setLatest(current);}catch{/* Preserve the draft when the latest record cannot be read. */}
    }finally{setBusy(false);}
  }
  return <section className="card subscreen stack" aria-label="銘柄メモ">
    <h3 className="section-title">{symbol} のメモ</h3>
    <label>メモ<textarea className="input" rows={5} maxLength={5000} value={draft} disabled={!base || busy} onChange={event=>{setDraft(event.target.value);setMessage("");}} placeholder="気になった点や、判断の理由など" /></label>
    {!base && !error && <p role="status" className="small muted">メモを読み込んでいます…</p>}
    <div className="stack"><small className="muted">{draft.length} / 5000文字</small><button className="button" disabled={!base || busy || draft===base.text} onClick={()=>void save()}>{busy ? "保存中…" : "メモを保存"}</button></div>
    {base?.updatedAt && <small className="muted">保存 {dateTime(base.updatedAt,true)}</small>}
    {message && <p role="status" className="save-result">{message}</p>}
    {error && <p role="alert">{error}</p>}
    {error && !base && <button className="button secondary" onClick={()=>setReadSequence(value=>value+1)}>メモを再読込</button>}
    {latest && <div className="stack"><p className="small">別の画面で保存された内容</p><pre className="research-text">{latest.text || "（空のメモ）"}</pre><button className="button secondary" disabled={busy} onClick={()=>{setBase(latest);setLatest(null);setError("");setMessage("入力は残しています。内容を確認して保存してください。");}}>自分の入力を残して編集を続ける</button><button className="quiet-link" onClick={()=>{setBase(latest);setDraft(latest.text);setLatest(null);setError("");}}>保存済みの内容を読み込む</button></div>}
  </section>;
}

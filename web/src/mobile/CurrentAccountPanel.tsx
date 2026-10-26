import { useEffect, useRef, useState, type ReactNode } from "react";
import { apiGet, apiPost } from "../api";
import { dateTime, currency as yen } from "../components";
import { Link } from "react-router-dom";
import { Field, FormGroup, KV } from "../Adopted";
import type { SavedPortfolio, SavedSettings } from "./personal";

type Bucket = { bucket_id: string; account_type: string; withholding_mode: string };
type Position = { symbol: string; account_bucket_id: string; shares: number; average_acquisition_price: string; market_price: string };
type Ledger = { portfolio_id: string; as_of: string; account_buckets: Bucket[]; positions: Position[];
  cash: { account_bucket_id: string; available_cash: string; reserved_cash: string }[];
  tax_states: { account_bucket_id: string; nisa_annual_capacity_user_input: string | null; nisa_lifetime_capacity_user_input: string | null }[] };
type Current = { ledger: Ledger | null; profile: SavedPortfolio | null; settings: SavedSettings | null };
type Edit = { base_ledger_id: string; base_revision_id: string; base_settings_id: string; as_of: string; group: string; changes: unknown; record?:{date:string;reason:string;kind:string} };
export function bucketName(bucket: Bucket): string {
  return bucket.account_type === "nisa" ? "NISA（成長投資枠）" : bucket.account_type === "taxable_general" ? "一般口座"
    : bucket.account_type === "taxable_specified" ? `特定口座（源泉徴収${bucket.withholding_mode === "withholding" ? "あり" : bucket.withholding_mode === "no_withholding" ? "なし" : "未確認"}）` : "口座区分未確認";
}

export function CurrentAccountPanel({ mode, fallback, onSaved, registration = false }: { mode: "cash" | "holdings" | "nisa"; fallback?: ReactNode; onSaved?: () => void; registration?: boolean }): ReactNode {
  const [current, setCurrent] = useState<Current | null>(null);
  const [cash, setCash] = useState<{ account_bucket_id: string; total: string; buying_power: string }[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [selectedPosition,setSelectedPosition]=useState(0);
  const [cashKind,setCashKind]=useState("correction"), [cashIndex,setCashIndex]=useState(0), [cashAmount,setCashAmount]=useState("");
  const [cashInvalid,setCashInvalid]=useState(false);
  const [recordDate,setRecordDate]=useState(()=>new Intl.DateTimeFormat("sv-SE").format(new Date()));
  const [reason,setReason]=useState("");
  const [nisa, setNisa] = useState<{ account_bucket_id: string; annual: string; lifetime: string }[]>([]);
  const [preview, setPreview] = useState<{ before: Ledger; after: Ledger; request: Edit } | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const flight = useRef(false);
  const loadedInput = useRef("");
  useEffect(() => {
    let active = true;
    void apiGet<Current>("/api/v1/mobile/personal/current").then(value => {
      if (!active) return;
      setCurrent(value); setError("");
      const identity=JSON.stringify([value.ledger?.portfolio_id,value.profile?.revision_id,value.settings?.revision_id]);
      if (loadedInput.current === identity) return;
      loadedInput.current=identity; setPreview(null);
      setPositions(value.ledger?.positions ?? []);
      setCash(value.ledger?.cash.map(x => ({ account_bucket_id: x.account_bucket_id, total: x.available_cash, buying_power: subtract(x.available_cash, x.reserved_cash) })) ?? []);
      setNisa(value.ledger?.tax_states.filter(x => value.ledger?.account_buckets.find(b => b.bucket_id === x.account_bucket_id)?.account_type === "nisa")
        .map(x => ({ account_bucket_id: x.account_bucket_id, annual: x.nisa_annual_capacity_user_input ?? "", lifetime: x.nisa_lifetime_capacity_user_input ?? "" })) ?? []);
    }).catch(() => { if (active) setError("現在残高を読み込めませんでした。"); });
    return () => { active = false; };
  }, [reload]);
  async function act(confirm: boolean): Promise<void> {
    if (flight.current || !current?.ledger || !current.profile || !current.settings) return;
    flight.current = true; setBusy(true); setError(""); setMessage("");
    try {
      if (confirm && preview) {
        await apiPost("/api/v1/mobile/personal/current/confirm", preview.request);
        setPreview(null); setReload(x => x + 1); setMessage("現在残高を更新しました。履歴は保持しています。"); onSaved?.();
      } else {
        const request: Edit = { base_ledger_id: current.ledger.portfolio_id, base_revision_id: current.profile.revision_id,
          base_settings_id: current.settings.revision_id, as_of: new Date().toISOString(), group: mode,
          changes: mode === "cash" ? cash : mode === "holdings" ? positions : nisa,
          ...(mode!=="nisa" ? {record:{date:recordDate,reason,kind:mode==="cash" ? cashKind : "correction"}} : {}) };
        setPreview(await apiPost("/api/v1/mobile/personal/current/preview", request));
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "保存できませんでした。読み直して確認してください。"); }
    finally { flight.current = false; setBusy(false); }
  }
  if (!current) return <>{error ? <p role="alert">{error}<button className="button" onClick={() => setReload(x => x + 1)}>読み直す</button></p> : <p role="status">現在残高を確認しています…</p>}</>;
  if (!current.ledger) return <>{fallback ?? <p>初回残高を登録すると、ここで実保有を編集できます。</p>}</>;
  if (registration) return <div className="subscreen stack"><section className="card"><h3 className="section-title">初回残高は登録済みです</h3><KV label="台帳日時" value={dateTime(current.ledger.as_of,true)} /><KV label="保有明細" value={`${current.ledger.positions.length}件`} /><p className="subhint">残高の変更は「現金残高の変更」「保有の訂正」で確認して保存できます。</p></section><Link className="button secondary" to="/assets">資産管理</Link></div>;
  const ledger = current.ledger;
  const label = (id: string) => bucketName(ledger.account_buckets.find(x => x.bucket_id === id) ?? preview!.after.account_buckets.find(x => x.bucket_id === id)!);
  const changed = () => { setPreview(null); setMessage(""); };
  return <div className="subscreen stack">
    <fieldset className="account-form" disabled={busy}>
      {mode === "cash" && <>
        <section className="card"><FormGroup title="変更内容"><Field label="種別"><select className="input" value={cashKind} onChange={e=>{changed();setCashKind(e.target.value);setCashAmount("");setCashInvalid(e.target.value!=="correction");setCash(ledger.cash.map(x=>({account_bucket_id:x.account_bucket_id,total:x.available_cash,buying_power:subtract(x.available_cash,x.reserved_cash)})));}}><option value="deposit">入金</option><option value="withdrawal">出金</option><option value="correction">残高訂正</option></select></Field>
        {cash.length>1 && <Field label="口座"><select className="input" value={cashIndex} onChange={e=>{changed();setCashIndex(Number(e.target.value));setCashAmount("");setCashInvalid(cashKind!=="correction");}}>{cash.map((item,i)=><option key={item.account_bucket_id} value={i}>{label(item.account_bucket_id)}</option>)}</select></Field>}
        {cash.slice(cashIndex,cashIndex+1).map((item,index)=><Field key={item.account_bucket_id} label={cashKind==="correction" ? "現金残高（円）" : "金額（円）"}><input className="input" inputMode="decimal" value={cashKind==="correction" ? item.total : cashAmount} onChange={e=>{changed();const value=e.target.value;setCashAmount(value);try{const original=ledger.cash.find(x=>x.account_bucket_id===item.account_bucket_id)!;const amount=units(value);const total=cashKind==="correction" ? value : amountText(units(original.available_cash)+(cashKind==="withdrawal" ? -amount : amount));const buying=cashKind==="correction" ? item.buying_power : subtract(total,original.reserved_cash);setCash(cash.map((x,i)=>i===cashIndex+index ? {...x,total,buying_power:buying} : x));setCashInvalid(false);}catch{if(cashKind==="correction")setCash(cash.map((x,i)=>i===cashIndex ? {...x,total:value} : x));setCashInvalid(true);}}} /></Field>)}</FormGroup>
        <FormGroup title="記録"><Field label="日付"><input className="input" type="date" value={recordDate} onChange={e=>{changed();setRecordDate(e.target.value);}} /></Field><Field label="理由"><input className="input" maxLength={500} value={reason} onChange={e=>{changed();setReason(e.target.value);}} /></Field>{cashKind==="correction" && cash.slice(cashIndex,cashIndex+1).map(item=><Field key={item.account_bucket_id} label="買付余力（円）"><input className="input" inputMode="decimal" value={item.buying_power} onChange={e=>{changed();setCash(cash.map((x,i)=>i===cashIndex ? {...x,buying_power:e.target.value} : x));}} /></Field>)}</FormGroup></section>
        {current.profile && <PreviousInput current={current} />}
      </>}
      {mode === "holdings" && <>
        <section className="card">
        {positions.length>1 && <Field label="訂正する保有"><select className="input" value={Math.min(selectedPosition,positions.length-1)} onChange={e=>{changed();setSelectedPosition(Number(e.target.value));}}>{positions.map((item,index)=><option key={index} value={index}>{item.symbol || "新しい保有"} · {label(item.account_bucket_id)} · {item.shares}株</option>)}</select></Field>}
        {positions.map((item, index) => <div key={index} hidden={index !== Math.min(selectedPosition,positions.length-1)}>
          <FormGroup title="保有"><Field label="銘柄コード"><input className="input" value={item.symbol} onChange={e => { changed(); setPositions(positions.map((x, i) => i === index ? { ...x, symbol: e.target.value.toUpperCase() } : x)); }} /></Field>
          <Field label="口座区分"><select className="input" value={item.account_bucket_id} onChange={e => { changed(); setPositions(positions.map((x, i) => i === index ? { ...x, account_bucket_id: e.target.value } : x)); }}>{ledger.account_buckets.map(b => <option key={b.bucket_id} value={b.bucket_id}>{bucketName(b)}</option>)}
            <option value="new:specified">特定口座（源泉徴収あり）</option><option value="new:specified_no">特定口座（源泉徴収なし）</option><option value="new:general">一般口座</option><option value="new:nisa">NISA（成長投資枠）</option>
          </select></Field><KV label="現在の株数" value={`${ledger.positions.find(x=>x.symbol===item.symbol && x.account_bucket_id===item.account_bucket_id)?.shares ?? 0}株`} /><KV label="現在の取得単価" value={yen(ledger.positions.find(x=>x.symbol===item.symbol && x.account_bucket_id===item.account_bucket_id)?.average_acquisition_price)} /></FormGroup>
          <FormGroup title="訂正内容"><Field label="株数"><input className="input" type="number" min="1" step="1" value={item.shares} onChange={e => { changed(); setPositions(positions.map((x, i) => i === index ? { ...x, shares: Number(e.target.value) } : x)); }} /></Field>
          {([["average_acquisition_price", "平均取得単価（円）"], ["market_price", "現在の株価（円）"]] as const).map(([key, title]) => <Field key={key} label={title}><input className="input" inputMode="decimal" value={item[key]} onChange={e => { changed(); setPositions(positions.map((x, i) => i === index ? { ...x, [key]: e.target.value } : x)); }} /></Field>)}
          <Field label="訂正日"><input className="input" type="date" value={recordDate} onChange={e=>{changed();setRecordDate(e.target.value);}} /></Field><Field label="理由"><input className="input" value={reason} maxLength={500} onChange={e=>{changed();setReason(e.target.value);}} /></Field></FormGroup>
          <button type="button" className="button button--secondary" onClick={() => { changed(); setPositions(positions.filter((_, i) => i !== index)); }}>この保有を削除</button>
        </div>)}
        <button type="button" className="button secondary" onClick={() => { changed(); setSelectedPosition(positions.length); setPositions([...positions, { symbol: "", account_bucket_id: ledger.account_buckets[0].bucket_id, shares: 100, average_acquisition_price: "", market_price: "" }]); }}>保有株を追加</button></section>
      </>}
      {mode === "nisa" && <>
        <p className="setting-footnote">個別株に使う成長投資枠：年間240万円、保有限度1200万円。残枠はSBIの表示で確認してください。</p>
        {nisa.length === 0 && <p>NISAの登録はありません。</p>}
        {nisa.map((item, index) => <div className="account-form-card" key={item.account_bucket_id}>
          {nisa.length > 1 && <h3>{label(item.account_bucket_id)}</h3>}
          <label>今年の残枠（円）<input inputMode="decimal" value={item.annual} onChange={e => { changed(); setNisa(nisa.map((x, i) => i === index ? { ...x, annual: e.target.value } : x)); }} /></label>
          <label>成長投資枠の残り保有限度（円）<input inputMode="decimal" value={item.lifetime} onChange={e => { changed(); setNisa(nisa.map((x, i) => i === index ? { ...x, lifetime: e.target.value } : x)); }} /></label>
          {(Number(item.annual) > 2400000 || Number(item.lifetime) > 12000000) && <p role="alert">保存値が制度の上限を超えています。SBIの残枠を確認して修正してください。</p>}
        </div>)}
      </>}
      <section className="card stack" style={{marginTop:12}}><h3 className="section-title">変更プレビュー</h3>
      {!preview && mode==="cash" && cash.slice(cashIndex,cashIndex+1).map(item=><div key={item.account_bucket_id}><KV label="現在の現金" value={yen(ledger.cash.find(x=>x.account_bucket_id===item.account_bucket_id)?.available_cash)} /><KV label="変更後（確認中）" value={cashInvalid ? "金額を確認してください" : yen(item.total)} /><KV label="確保中" value={moneyDifference(item.total,item.buying_power)} /></div>)}
      {!preview && mode==="holdings" && positions.slice(Math.min(selectedPosition,positions.length-1),Math.min(selectedPosition,positions.length-1)+1).map(item=><div key={item.symbol}><KV label="株数" value={`${ledger.positions.find(x=>x.symbol===item.symbol && x.account_bucket_id===item.account_bucket_id)?.shares ?? 0} → ${item.shares}株`} /><KV label="平均取得単価" value={yen(item.average_acquisition_price)} /></div>)}
      {preview && <div>
        {mode === "cash" && preview.after.cash.map(x => <p key={x.account_bucket_id}>{label(x.account_bucket_id)}：現金 {yen(preview.before.cash.find(b => b.account_bucket_id === x.account_bucket_id)!.available_cash)} → {yen(x.available_cash)} ／ 確保中 {yen(x.reserved_cash)}</p>)}
        {mode === "holdings" && <><p>{preview.before.positions.length}件 → {preview.after.positions.length}件</p>{preview.after.positions.map(x => <p key={`${x.symbol}:${x.account_bucket_id}`}>{x.symbol} · {label(x.account_bucket_id)} · {x.shares}株</p>)}</>}
        {mode === "nisa" && nisa.map(x => <p key={x.account_bucket_id}>今年の残枠 {yen(x.annual)} ／ 保有限度残り {yen(x.lifetime)}</p>)}
      </div>}</section>
      {(mode !== "nisa" || nisa.length > 0) && <div className="subactions"><button className="button" disabled={mode==="cash" && cashInvalid} type="button" onClick={() => void act(!!preview)}>{preview ? "この内容で現在残高を更新" : "変更内容を確認"}</button><Link className="button secondary" to="/assets">資産管理</Link></div>}
    </fieldset>
    {error && <><p role="alert">{error}</p><button type="button" className="button button--secondary" disabled={busy} onClick={() => setReload(x => x + 1)}>現在残高を読み直す</button></>}{message && <p role="status">{message}</p>}
  </div>;
}

// Keep four decimal places exact; no binary floating-point balance calculations.
function units(value: string): bigint { if (!/^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/.test(value)) throw Error("Invalid amount"); const [whole, decimal = ""] = value.split("."); return BigInt(whole) * 10000n + BigInt(decimal.padEnd(4, "0")); }
function amountText(value:bigint):string {if(value<0n)throw Error("Negative balance");return `${value/10000n}.${(value%10000n).toString().padStart(4,"0")}`.replace(/\.?0+$/,"");}
function subtract(a: string, b: string): string { const value = units(a) - units(b); if (value < 0n) throw Error("Negative balance"); return `${value / 10000n}.${(value % 10000n).toString().padStart(4, "0")}`.replace(/\.?0+$/, ""); }
function moneyDifference(a: string, b: string): string { try { return yen(subtract(a, b)); } catch { return "金額を確認してください"; } }
function PreviousInput({ current }: { current: Current }): ReactNode {
  const settings = current.settings?.settings;
  if (!settings || !current.profile || !current.ledger) return null;
  const differences = current.profile.portfolio.accounts.filter(x => {
    const cash = current.ledger!.cash.find(c => c.account_bucket_id === x.id);
    if (!cash || x.available_cash_yen === null) return true;
    try { return units(x.available_cash_yen) !== units(settings.cash_basis === "deployable_after_reserved" ? subtract(cash.available_cash, cash.reserved_cash) : cash.available_cash); } catch { return true; }
  });
  if (!differences.length) return null;
  return <div className="account-form-card"><p>以前の入力値は現在残高に未反映です。SBIの残高を確認して上の金額を更新してください。</p>{differences.map(x => <p key={x.id}>以前の{settings.cash_basis === "deployable_after_reserved" ? "買付余力" : "現金入力"}：{x.available_cash_yen === null ? "未入力" : yen(x.available_cash_yen)}（{dateTime(current.profile!.saved_at)} JST）</p>)}</div>;
}

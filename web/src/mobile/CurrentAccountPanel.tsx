import { useEffect, useRef, useState, type ReactNode } from "react";
import { apiGet, apiPost } from "../api";
import { dateTime, yen } from "../components";
import type { SavedPortfolio, SavedSettings } from "./personal";

type Bucket = { bucket_id: string; account_type: string; withholding_mode: string };
type Position = { symbol: string; account_bucket_id: string; shares: number; average_acquisition_price: string; market_price: string };
type Ledger = { portfolio_id: string; as_of: string; account_buckets: Bucket[]; positions: Position[];
  cash: { account_bucket_id: string; available_cash: string; reserved_cash: string }[];
  tax_states: { account_bucket_id: string; nisa_annual_capacity_user_input: string | null; nisa_lifetime_capacity_user_input: string | null }[] };
type Current = { ledger: Ledger | null; profile: SavedPortfolio | null; settings: SavedSettings | null };
type Edit = { base_ledger_id: string; base_revision_id: string; base_settings_id: string; as_of: string; group: string; changes: unknown };
export function bucketName(bucket: Bucket): string {
  return bucket.account_type === "nisa" ? "NISA（成長投資枠）" : bucket.account_type === "taxable_general" ? "一般口座"
    : bucket.account_type === "taxable_specified" ? `特定口座（源泉徴収${bucket.withholding_mode === "withholding" ? "あり" : bucket.withholding_mode === "no_withholding" ? "なし" : "未確認"}）` : "口座区分未確認";
}

export function CurrentAccountPanel({ mode, fallback, onSaved }: { mode: "cash" | "holdings" | "nisa"; fallback?: ReactNode; onSaved?: () => void }): ReactNode {
  const [current, setCurrent] = useState<Current | null>(null);
  const [cash, setCash] = useState<{ account_bucket_id: string; total: string; buying_power: string }[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [nisa, setNisa] = useState<{ account_bucket_id: string; annual: string; lifetime: string }[]>([]);
  const [preview, setPreview] = useState<{ before: Ledger; after: Ledger; request: Edit } | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const flight = useRef(false);
  useEffect(() => {
    let active = true;
    void apiGet<Current>("/api/v1/mobile/personal/current").then(value => {
      if (!active) return;
      setCurrent(value); setError(""); setPreview(null);
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
          changes: mode === "cash" ? cash : mode === "holdings" ? positions : nisa };
        setPreview(await apiPost("/api/v1/mobile/personal/current/preview", request));
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "保存できませんでした。読み直して確認してください。"); }
    finally { flight.current = false; setBusy(false); }
  }
  if (!current) return <>{error ? <p role="alert">{error}<button className="button" onClick={() => setReload(x => x + 1)}>読み直す</button></p> : <p role="status">現在残高を確認しています…</p>}</>;
  if (!current.ledger) return <>{fallback ?? <p>初回残高を登録すると、ここで実保有を編集できます。</p>}</>;
  const ledger = current.ledger;
  const label = (id: string) => bucketName(ledger.account_buckets.find(x => x.bucket_id === id) ?? preview!.after.account_buckets.find(x => x.bucket_id === id)!);
  const changed = () => { setPreview(null); setMessage(""); };
  return <div className="account-editor">
    <p className="setting-footnote">SBI証券 · 現在残高 {dateTime(ledger.as_of)} JST</p>
    <fieldset className="account-form" disabled={busy}>
      {mode === "cash" && <>
        <p className="setting-footnote">現金残高 − 買付余力 ＝ 確保中。初回残高と取引履歴は残ります。</p>
        {cash.map((item, index) => <div className="account-form-card" key={item.account_bucket_id}>
          {cash.length > 1 && <h3>{label(item.account_bucket_id)}</h3>}
          <label>現金残高（円）<input inputMode="decimal" value={item.total} onChange={e => { changed(); setCash(cash.map((x, i) => i === index ? { ...x, total: e.target.value } : x)); }} /></label>
          <label>買付余力（円）<input inputMode="decimal" value={item.buying_power} onChange={e => { changed(); setCash(cash.map((x, i) => i === index ? { ...x, buying_power: e.target.value } : x)); }} /></label>
          <p>確保中：{moneyDifference(item.total, item.buying_power)}</p>
        </div>)}
        {current.profile && <PreviousInput current={current} />}
      </>}
      {mode === "holdings" && <>
        <p className="setting-footnote">SBIの現在の保有に合わせて修正します。売買の記録は「約定を記録」から行ってください。</p>
        {positions.map((item, index) => <div className="account-form-card" key={index}>
          <label>銘柄コード<input value={item.symbol} onChange={e => { changed(); setPositions(positions.map((x, i) => i === index ? { ...x, symbol: e.target.value.toUpperCase() } : x)); }} /></label>
          <label>口座区分<select value={item.account_bucket_id} onChange={e => { changed(); setPositions(positions.map((x, i) => i === index ? { ...x, account_bucket_id: e.target.value } : x)); }}>{ledger.account_buckets.map(b => <option key={b.bucket_id} value={b.bucket_id}>{bucketName(b)}</option>)}
            <option value="new:specified">特定口座（源泉徴収あり）</option><option value="new:specified_no">特定口座（源泉徴収なし）</option><option value="new:general">一般口座</option><option value="new:nisa">NISA（成長投資枠）</option>
          </select></label>
          <label>株数<input type="number" min="1" step="1" value={item.shares} onChange={e => { changed(); setPositions(positions.map((x, i) => i === index ? { ...x, shares: Number(e.target.value) } : x)); }} /></label>
          {([["average_acquisition_price", "平均取得単価（円）"], ["market_price", "現在の株価（円）"]] as const).map(([key, title]) => <label key={key}>{title}<input inputMode="decimal" value={item[key]} onChange={e => { changed(); setPositions(positions.map((x, i) => i === index ? { ...x, [key]: e.target.value } : x)); }} /></label>)}
          <button type="button" className="button button--secondary" onClick={() => { changed(); setPositions(positions.filter((_, i) => i !== index)); }}>この保有を削除</button>
        </div>)}
        <button type="button" className="button button--secondary" onClick={() => { changed(); setPositions([...positions, { symbol: "", account_bucket_id: ledger.account_buckets[0].bucket_id, shares: 100, average_acquisition_price: "", market_price: "" }]); }}>保有株を追加</button>
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
      {(mode !== "nisa" || nisa.length > 0) && <button className="button button--primary" type="button" onClick={() => void act(false)}>変更内容を確認</button>}
      {preview && <div className="account-form-card"><h3>変更の確認</h3>
        {mode === "cash" && preview.after.cash.map(x => <p key={x.account_bucket_id}>{label(x.account_bucket_id)}：現金 {yen(preview.before.cash.find(b => b.account_bucket_id === x.account_bucket_id)!.available_cash)} → {yen(x.available_cash)} ／ 確保中 {yen(x.reserved_cash)}</p>)}
        {mode === "holdings" && <><p>{preview.before.positions.length}件 → {preview.after.positions.length}件</p>{preview.after.positions.map(x => <p key={`${x.symbol}:${x.account_bucket_id}`}>{x.symbol} · {label(x.account_bucket_id)} · {x.shares}株</p>)}</>}
        {mode === "nisa" && nisa.map(x => <p key={x.account_bucket_id}>今年の残枠 {yen(x.annual)} ／ 保有限度残り {yen(x.lifetime)}</p>)}
        <button className="button button--primary" type="button" onClick={() => void act(true)}>この内容で現在残高を更新</button>
      </div>}
    </fieldset>
    {error && <><p role="alert">{error}</p><button type="button" className="button button--secondary" disabled={busy} onClick={() => setReload(x => x + 1)}>現在残高を読み直す</button></>}{message && <p role="status">{message}</p>}
  </div>;
}

// Keep four decimal places exact; no binary floating-point balance calculations.
function units(value: string): bigint { if (!/^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$/.test(value)) throw Error("Invalid amount"); const [whole, decimal = ""] = value.split("."); return BigInt(whole) * 10000n + BigInt(decimal.padEnd(4, "0")); }
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

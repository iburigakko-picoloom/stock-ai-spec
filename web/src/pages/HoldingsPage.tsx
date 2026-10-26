import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { PageHeader } from "../components";
import { CurrentAccountPanel } from "../mobile/CurrentAccountPanel";
import type { LocalPortfolio, SavedPortfolio } from "../mobile/personal";

export function HoldingsPage(): ReactNode {
  const [params]=useSearchParams();
  const initial=params.has("initial");
  return <div className="page account-settings-screen"><PageHeader title={initial ? "初回資産登録" : "実保有"} backTo="/assets" />
    <section className="section"><CurrentAccountPanel mode="holdings" registration={initial} fallback={<InitialHoldings />} /></section>
    <Link className="button button--secondary" to="/today/executions">約定を記録</Link>
  </div>;
}

const empty: LocalPortfolio = { schema_version: "manual-portfolio-v1", accounts: [], holdings: [], holdings_status: "unrecorded", investment_budget_yen: null, maximum_drawdown_percent: null };
const classifications = {
  specified: ["taxable_specified", "withholding", "特定口座（源泉徴収あり）"],
  specified_no: ["taxable_specified", "no_withholding", "特定口座（源泉徴収なし）"],
  general: ["taxable_general", "no_withholding", "一般口座"],
  nisa: ["nisa", "not_applicable", "NISA（成長投資枠）"],
} as const;
function InitialHoldings(): ReactNode {
  const [saved, setSaved] = useState<SavedPortfolio | null>(null);
  const [draft, setDraft] = useState<LocalPortfolio>(empty);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [tradeType, setTradeType] = useState<keyof typeof classifications>("specified");
  useEffect(() => { let active = true; void apiGet<SavedPortfolio | null>("/api/v1/mobile/portfolio").then(x => { if (active) { setSaved(x); setDraft(x?.portfolio ?? empty); setLoaded(true); } }).catch(() => { if (active) setMessage("保有入力を読み込めませんでした。"); }); return () => { active = false; }; }, []);
  function account(type: keyof typeof classifications, value: LocalPortfolio) {
    const [kind, withholding] = classifications[type];
    const existing = value.accounts.find(x => x.account_type === kind && x.withholding_mode === withholding);
    if (existing) return { accounts: value.accounts, id: existing.id };
    const added = { id: crypto.randomUUID(), name: "SBI証券", account_type: kind, withholding_mode: withholding, available_cash_yen: null };
    return { accounts: [...value.accounts, added], id: added.id };
  }
  return <fieldset className="account-form" disabled={!loaded || busy}>
    <p className="setting-footnote">初回の保有を入力し、設定で初回残高を確定します。</p>
    <h2>現金</h2>
    {draft.accounts.length ? draft.accounts.map(item=><label key={item.id}>現金残高（円）{draft.accounts.length>1 && ` · ${item.account_type === "nisa" ? "NISA" : item.account_type === "taxable_general" ? "一般口座" : "特定口座"}`}<input inputMode="decimal" value={item.available_cash_yen ?? ""} onChange={e=>setDraft({...draft,accounts:draft.accounts.map(row=>row.id===item.id ? {...row,available_cash_yen:e.target.value || null} : row)})} /></label>) : <label>現金残高（円）<input inputMode="decimal" value="" onChange={e=>{const next=account("specified",draft);setDraft({...draft,accounts:next.accounts.map(row=>row.id===next.id ? {...row,available_cash_yen:e.target.value || null} : row)});}} /></label>}
    <p className="setting-footnote">同じ現金を複数の口座区分へ重複入力しないでください。</p>
    <h2>保有</h2>
    {draft.holdings.map((holding, index) => <div className="account-form-card" key={index}>
      <label>銘柄コード<input value={holding.symbol} onChange={e => setDraft({ ...draft, holdings: draft.holdings.map((x, i) => i === index ? { ...x, symbol: e.target.value.toUpperCase() } : x) })} /></label>
      <label>口座区分<select value={Object.entries(classifications).find(([, [kind, withholding]]) => draft.accounts.some(a => a.id === holding.account_id && a.account_type === kind && a.withholding_mode === withholding))?.[0] ?? ""} onChange={e => { const next = account(e.target.value as keyof typeof classifications, draft); setDraft({ ...draft, accounts: next.accounts, holdings: draft.holdings.map((x, i) => i === index ? { ...x, account_id: next.id } : x) }); }}><option value="" disabled>選んでください</option>{Object.entries(classifications).map(([key, value]) => <option key={key} value={key}>{value[2]}</option>)}</select></label>
      <label>株数<input type="number" min="1" value={holding.shares} onChange={e => setDraft({ ...draft, holdings: draft.holdings.map((x, i) => i === index ? { ...x, shares: Number(e.target.value) } : x) })} /></label>
      <label>平均取得単価（円）<input inputMode="decimal" value={holding.average_acquisition_price_yen ?? ""} onChange={e => setDraft({ ...draft, holdings: draft.holdings.map((x, i) => i === index ? { ...x, average_acquisition_price_yen: e.target.value || null } : x) })} /></label>
      <button className="button button--secondary" onClick={() => { const holdings = draft.holdings.filter((_, i) => i !== index); setDraft({ ...draft, holdings, holdings_status: holdings.length ? "recorded" : "none" }); }}>この保有を削除</button>
    </div>)}
    <button className="button button--secondary" onClick={() => { const next = account(tradeType, draft); setDraft({ ...draft, accounts: next.accounts, holdings_status: "recorded", holdings: [...draft.holdings, { account_id: next.id, symbol: "", shares: 100, average_acquisition_price_yen: null }] }); }}>保有株を追加</button>
    {!draft.holdings.length && <><label>次の取引で使う口座区分<select value={tradeType} onChange={e => setTradeType(e.target.value as keyof typeof classifications)}>{Object.entries(classifications).map(([key, value]) => <option key={key} value={key}>{value[2]}</option>)}</select></label><label><input type="checkbox" checked={draft.holdings_status === "none"} onChange={e => { const next = account(tradeType, draft); setDraft({ ...draft, accounts: next.accounts, holdings_status: e.target.checked ? "none" : "unrecorded" }); }} />現在は保有なし</label></>}
    <button className="button button--primary" onClick={() => { if (busy) return; setBusy(true); void apiPost<SavedPortfolio>("/api/v1/mobile/portfolio", { expected_revision_id: saved?.revision_id ?? null, portfolio: draft }).then(x => { setSaved(x); setDraft(x.portfolio); setMessage("保有入力を保存しました。設定で初回残高を確認してください。"); }).catch(e => setMessage(e instanceof Error ? e.message : "保存できませんでした。")).finally(() => setBusy(false)); }}>保有入力を保存</button>
    {message && <p role="status">{message}</p>}
    <Link to="/settings?edit=accounts" className="button button--secondary">初回残高の設定へ</Link>
  </fieldset>;
}

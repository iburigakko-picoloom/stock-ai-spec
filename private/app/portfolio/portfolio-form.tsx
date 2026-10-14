"use client";

import { useState } from "react";
import { accountTypeLabels, emptyPortfolio, portfolioInput, portfolioResponse, withholdingLabels, type ManualPortfolio, type SavedPortfolio } from "@/lib/portfolio";

const yen = (value: string | null) => value === null ? "未入力" : `${Number(value).toLocaleString("ja-JP", { maximumFractionDigits: 4 })}円`;
type Account = ManualPortfolio["accounts"][number];
type Holding = ManualPortfolio["holdings"][number];

export default function PortfolioForm({ initial }: { initial: SavedPortfolio | null }) {
  const [saved, setSaved] = useState(initial);
  const [draft, setDraft] = useState<ManualPortfolio>(initial?.portfolio ?? emptyPortfolio);
  const [preview, setPreview] = useState<ManualPortfolio | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  function change(next: ManualPortfolio) { setDraft(next); setPreview(null); setMessage(""); setError(""); }
  function accountChange(index: number, values: Partial<Account>) {
    change({ ...draft, accounts: draft.accounts.map((item, i) => i === index ? { ...item, ...values } : item) });
  }
  function holdingChange(index: number, values: Partial<Holding>) {
    change({ ...draft, holdings: draft.holdings.map((item, i) => i === index ? { ...item, ...values } : item) });
  }
  function review() {
    const parsed = portfolioInput.safeParse(draft);
    if (!parsed.success) { setError(parsed.error.issues[0].message); setPreview(null); return; }
    setError(""); setPreview(parsed.data); setMessage("");
  }
  async function reload() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/portfolio", { cache: "no-store" });
      if (!response.ok) throw new Error("read failed");
      const result = portfolioResponse.parse(await response.json());
      setSaved(result.saved); setDraft(result.saved?.portfolio ?? emptyPortfolio); setPreview(null);
      setMessage("保存済みの内容を読み込みました。");
    } catch { setError("保存内容を読み込めませんでした。入力はそのまま残しています。"); }
    finally { setBusy(false); }
  }
  async function save() {
    if (!preview || busy) return;
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/portfolio", { method: "POST", headers: {
        "Content-Type": "application/json", "X-Stock-AI-Intent": "manual-record",
      }, body: JSON.stringify({ expected_revision_id: saved?.revision_id ?? null, portfolio: preview }) });
      if (!response.ok) {
        setError(response.status === 409 ? "別の画面で更新されています。保存内容を読み直してください。" : "保存できませんでした。入力内容を確認して再度保存してください。");
        return;
      }
      const result = portfolioResponse.parse(await response.json());
      if (!result.saved) throw new Error("missing saved portfolio");
      setSaved(result.saved); setDraft(result.saved.portfolio); setPreview(null); setMessage("保存しました。あとからいつでも修正できます。");
    } catch { setError("通信を確認して再度保存してください。入力内容は画面に残っています。"); }
    finally { setBusy(false); }
  }
  return <div>
    <div className="saved-line"><span>{saved ? `最終保存: ${new Date(saved.saved_at).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })} JST` : "まだ保存されていません"}</span><button className="text-button" type="button" onClick={reload} disabled={busy}>保存内容を読み直す</button></div>
    <fieldset disabled={busy} className="form-fields">
      <section className="panel"><div className="section-heading"><div className="section-number">01</div><div><h2>現在の保有</h2><p>株をまだ持っていなくても、その状態を記録できます。</p></div></div>
        <label className="field">保有状況<select value={draft.holdings_status} onChange={event => change({ ...draft, holdings_status: event.target.value as ManualPortfolio["holdings_status"] })}><option value="none">現在は保有なし</option><option value="recorded">保有あり</option><option value="unrecorded">まだ入力していない</option></select></label>
        {draft.holdings_status !== "recorded" && draft.holdings.length > 0 && <p className="form-error">銘柄の行が残っています。「保有なし」で保存する場合は、下の保有行を削除してください。</p>}
      </section>
      <section className="panel"><div className="section-heading"><div className="section-number">02</div><div><h2>口座区分</h2><p>口座ごとに呼び名と区分を登録します。口座番号は必要ありません。</p></div></div>
        {draft.accounts.map((item, index) => <fieldset className="entry-card" key={item.id}><legend>口座 {index + 1}</legend><div className="form-grid">
          <label className="field">口座の呼び名<input maxLength={60} autoComplete="off" placeholder="例：メイン証券・NISA" value={item.name} onChange={event => accountChange(index, { name: event.target.value })}/></label>
          <label className="field">口座区分<select value={item.account_type} onChange={event => { const type = event.target.value as Account["account_type"]; accountChange(index, { account_type: type, withholding_mode: type === "nisa" ? "not_applicable" : "unknown" }); }}>{Object.entries(accountTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="field">源泉徴収<select value={item.withholding_mode} disabled={item.account_type === "nisa"} onChange={event => accountChange(index, { withholding_mode: event.target.value as Account["withholding_mode"] })}>{Object.entries(withholdingLabels).filter(([value]) => item.account_type === "nisa" ? value === "not_applicable" : value !== "not_applicable" && (item.account_type === "taxable_specified" || value !== "withholding")).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="field">利用可能な現金（円・任意）<input inputMode="decimal" placeholder="未入力" value={item.available_cash_yen ?? ""} onChange={event => accountChange(index, { available_cash_yen: event.target.value || null })}/></label>
        </div><button className="text-button danger" type="button" disabled={draft.holdings.some(holding => holding.account_id === item.id)} onClick={() => change({ ...draft, accounts: draft.accounts.filter((_, i) => i !== index) })}>この口座を削除</button>{draft.holdings.some(holding => holding.account_id === item.id) && <small className="muted"> 保有銘柄の行を先に削除すると口座を削除できます。</small>}</fieldset>)}
        {!draft.accounts.length && <p className="muted">口座は未登録です。「保有なし」だけでも保存できます。</p>}
        <button className="secondary-button" type="button" disabled={draft.accounts.length >= 30} onClick={() => change({ ...draft, accounts: [...draft.accounts, { id: crypto.randomUUID(), name: "", account_type: "unknown_manual", withholding_mode: "unknown", available_cash_yen: null }] })}>＋ 口座を追加</button>
      </section>
      {(draft.holdings_status === "recorded" || draft.holdings.length > 0) && <section className="panel"><div className="section-heading"><div className="section-number">03</div><div><h2>保有している株</h2><p>銘柄と口座の組み合わせごとに入力します。単元未満株も記録できます。</p></div></div>
        {draft.holdings.map((item, index) => <fieldset className="entry-card" key={index}><legend>保有銘柄 {index + 1}</legend><div className="form-grid">
          <label className="field">口座<select value={item.account_id} onChange={event => holdingChange(index, { account_id: event.target.value })}><option value="">選択してください</option>{draft.accounts.map(account => <option key={account.id} value={account.id}>{account.name || "名称未入力"}（{accountTypeLabels[account.account_type]}）</option>)}</select></label>
          <label className="field">銘柄コード<input autoComplete="off" maxLength={5} placeholder="例：7203" value={item.symbol} onChange={event => holdingChange(index, { symbol: event.target.value.toUpperCase() })}/></label>
          <label className="field">保有株数<input type="number" min="1" step="1" inputMode="numeric" placeholder="例：100" value={item.shares || ""} onChange={event => holdingChange(index, { shares: Number(event.target.value) })}/></label>
          <label className="field">平均取得単価（円・任意）<input inputMode="decimal" placeholder="不明なら空欄" value={item.average_acquisition_price_yen ?? ""} onChange={event => holdingChange(index, { average_acquisition_price_yen: event.target.value || null })}/></label>
        </div><button className="text-button danger" type="button" onClick={() => change({ ...draft, holdings: draft.holdings.filter((_, i) => i !== index) })}>この保有行を削除</button></fieldset>)}
        {!draft.accounts.length && <p className="muted">先に口座を1つ登録してください。</p>}
        <button className="secondary-button" type="button" disabled={!draft.accounts.length || draft.holdings.length >= 200} onClick={() => change({ ...draft, holdings: [...draft.holdings, { account_id: draft.accounts[0].id, symbol: "", shares: 0, average_acquisition_price_yen: null }] })}>＋ 保有銘柄を追加</button>
      </section>}
      <section className="panel"><div className="section-heading"><div className="section-number">04</div><div><h2>資金とリスクの希望</h2><p>未定の項目は空欄で保存できます。空欄を0円やリスク許容なしとは扱いません。</p></div></div><div className="form-grid">
        <label className="field">投資に使う上限（円・任意）<input inputMode="decimal" placeholder="未定なら空欄" value={draft.investment_budget_yen ?? ""} onChange={event => change({ ...draft, investment_budget_yen: event.target.value || null })}/></label>
        <label className="field">許容したい最大下落率（%・任意）<input type="number" inputMode="decimal" min="0.01" max="100" step="0.01" placeholder="未定なら空欄" value={draft.maximum_drawdown_percent ?? ""} onChange={event => change({ ...draft, maximum_drawdown_percent: event.target.value === "" ? null : Number(event.target.value) })}/></label>
      </div><p className="footnote">最大下落率は希望の記録です。損失をその値以内に抑える保証ではありません。費用・税・データ・モデルの確認が済むまでは、推奨株数には使いません。</p></section>
      <button type="button" className="primary-button" onClick={review}>入力内容を確認</button>
    </fieldset>
    {error && <p role="alert" className="form-error">{error}</p>}
    {message && <p role="status" className="form-success">{message}</p>}
    {preview && <section className="panel confirmation" aria-label="保存内容の確認"><h2>この内容で保存します</h2><p>保有状況：{preview.holdings_status === "none" ? "保有なし" : preview.holdings_status === "recorded" ? "保有あり" : "未入力"}</p>
      {preview.accounts.map(account => <p key={account.id}>{account.name}：{accountTypeLabels[account.account_type]} / {withholdingLabels[account.withholding_mode]} / 現金 {yen(account.available_cash_yen)}</p>)}
      {preview.holdings.map(item => <p key={`${item.account_id}:${item.symbol}`}>{item.symbol} · {preview.accounts.find(account => account.id === item.account_id)?.name} · {item.shares.toLocaleString()}株 · 取得単価 {yen(item.average_acquisition_price_yen)}</p>)}
      <p>投資上限：{yen(preview.investment_budget_yen)} ／ 最大下落率：{preview.maximum_drawdown_percent === null ? "未入力" : `${preview.maximum_drawdown_percent}%`}</p>
      <div className="button-row"><button className="primary-button" type="button" disabled={busy} onClick={save}>{busy ? "保存中…" : "この内容を保存"}</button><button className="secondary-button" type="button" disabled={busy} onClick={() => setPreview(null)}>入力へ戻る</button></div>
    </section>}
  </div>;
}

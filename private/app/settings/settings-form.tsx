"use client";

import Link from "next/link";
import { useState } from "react";
import { accountTypeLabels, portfolioResponse, type SavedPortfolio } from "@/lib/portfolio";
import { blankAccount, costLabels, emptySettings, inputGaps, personalSettingsInput, settingsResponse,
  taxLabels, validateSettingsPortfolio, type PersonalSettings, type SavedSettings } from "@/lib/personal-settings";

const time = (value: string) => new Date(value).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" }) + " JST";
const number = (value: string | number | null) => {
  if (value === null) return "未入力";
  const [whole, fraction] = String(value).split(".");
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (fraction === undefined ? "" : `.${fraction}`);
};
const cashLabels = { total_including_reserved: "確保中の金額を含む総現金", deployable_after_reserved: "確保中の金額を除いた買付余力" };
const pendingLabels = { unknown: "まだ確認していない", none: "未反映の取引・未決済・未反映の入出金はない", pending: "未反映または未決済のものがある" };
type Account = PersonalSettings["accounts"][number];
function serverError(value: unknown, fallback: string) {
  return value !== null && typeof value === "object" && "error" in value && typeof value.error === "string"
    ? value.error : fallback;
}
function AmountField({ label, value, onChange }: { label: string; value: string | null; onChange: (value: string | null) => void }) {
  return <label className="field">{label}<input inputMode="decimal" value={value ?? ""} placeholder="未確認なら空欄" onChange={event => onChange(event.target.value || null)}/></label>;
}
function ResearchConditions() {
  return <details className="settings-details"><summary>この研究用比較で使う条件</summary>
    <ul><li>20日予測を使い、5日予測は参考表示。売買は100株単位。</li><li>最大10銘柄。1銘柄は資産の10%、同一業種は30%まで。現金は10%以上。</li><li>1回の売買総額は資産の100%まで。1銘柄の注文は平均日次売買代金の5%まで。</li><li>費用・推定税・下側リスク・不確実性を考慮し、現状維持からの改善が1,000円以上の案を比較。</li><li>下側リスクと不確実性はそれぞれ1倍で控除。大幅下落確率・集中・売買回転に対する追加ペナルティと追加の金額バッファーは0。</li></ul>
    <p className="muted">これらは研究用の固定条件です。入力した最大下落率から自動的に決めた条件ではなく、損失額を保証するものでもありません。実用採用には別の検証と確認が必要です。</p>
  </details>;
}
export default function SettingsForm({ initialPortfolio, initialSettings }: { initialPortfolio: SavedPortfolio; initialSettings: SavedSettings | null }) {
  const [portfolio, setPortfolio] = useState(initialPortfolio);
  const [saved, setSaved] = useState(initialSettings);
  const [draft, setDraft] = useState<PersonalSettings>(initialSettings?.settings ?? emptySettings(initialPortfolio.revision_id, initialPortfolio.portfolio));
  const [preview, setPreview] = useState<PersonalSettings | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [message, setMessage] = useState("");
  const stale = draft.portfolio_revision_id !== portfolio.revision_id;
  function change(next: PersonalSettings) { setDraft(next); setPreview(null); setError(""); setMessage(""); }
  function accountChange(id: string, values: Partial<Account>) { change({ ...draft, accounts: draft.accounts.map(item => item.account_id === id ? { ...item, ...values } : item) }); }
  function useCurrentPortfolio() {
    const ids = new Set(portfolio.portfolio.accounts.map(item => item.id));
    const removed = draft.accounts.filter(item => !ids.has(item.account_id)).length;
    change({ ...draft, portfolio_revision_id: portfolio.revision_id, research_conditions_reviewed: false,
      accounts: portfolio.portfolio.accounts.map(item => draft.accounts.find(old => old.account_id === item.id) ?? blankAccount(item.id)) });
    setMessage(`最新の口座・保有に合わせました。金額と口座区分を見直して保存してください。${removed ? `削除された${removed}口座の設定は過去の履歴に残ります。` : ""}`);
  }
  async function reload() {
    setBusy(true); setError("");
    try {
      const [a, b] = await Promise.all([fetch("/api/portfolio", { cache: "no-store" }), fetch("/api/personal-settings", { cache: "no-store" })]);
      if (!a.ok || !b.ok) throw new Error("unavailable");
      const p = portfolioResponse.parse(await a.json()).saved, s = settingsResponse.parse(await b.json());
      if (!p || p.revision_id !== s.current_portfolio_revision_id) throw new Error("changed during read");
      setPortfolio(p); setSaved(s.saved); setDraft(s.saved?.settings ?? emptySettings(p.revision_id, p.portfolio)); setPreview(null);
      setMessage("保存済みの口座・保有と補足設定を読み込みました。");
    } catch { setError("保存内容を読み込めませんでした。入力は画面に残しています。"); }
    finally { setBusy(false); }
  }
  function review() {
    const parsed = personalSettingsInput.safeParse(draft);
    if (!parsed.success) { setError(parsed.error.issues[0].message); setPreview(null); return; }
    const mismatch = validateSettingsPortfolio(parsed.data, portfolio.revision_id, portfolio.portfolio);
    if (mismatch) { setError(mismatch); setPreview(null); return; }
    setPreview(parsed.data); setError(""); setMessage("");
  }
  async function save() {
    if (!preview || busy) return;
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/personal-settings", { method: "POST", headers: { "Content-Type": "application/json", "X-Stock-AI-Intent": "manual-record" },
        body: JSON.stringify({ expected_revision_id: saved?.revision_id ?? null, settings: preview }) });
      const result = await response.json();
      if (!response.ok) { setError(serverError(result, "保存できませんでした。")); return; }
      const parsed = settingsResponse.parse(result);
      if (!parsed.saved) throw new Error("missing settings");
      setSaved(parsed.saved); setDraft(parsed.saved.settings); setPreview(null);
      setMessage(parsed.current_portfolio_revision_id === portfolio.revision_id ? "補足設定を保存しました。あとから修正できます。" : "保存しましたが、口座・保有が更新されています。保存内容を読み直して再確認してください。");
    } catch { setError("通信を確認して再度保存してください。入力は画面に残っています。"); }
    finally { setBusy(false); }
  }
  async function download() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/personal-settings/export", { cache: "no-store" });
      if (!response.ok) { const data = await response.json(); setError(serverError(data, "書き出せませんでした。")); return; }
      const blob = await response.blob(), url = URL.createObjectURL(blob), anchor = document.createElement("a");
      anchor.href = url; anchor.download = "stock-ai-personal-settings.json"; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage("保存済みの設定を書き出しました。この操作ではPCの保有台帳は変わりません。");
    } catch { setError("書き出せませんでした。通信を確認してください。"); }
    finally { setBusy(false); }
  }
  return <div>
    <div className="saved-line"><span>{saved ? `補足設定の最終保存：${time(saved.saved_at)}` : "補足設定は未保存です"}</span><button type="button" className="text-button" disabled={busy} onClick={reload}>保存内容を読み直す</button></div>
    <p className="muted">口座・保有の保存時刻：{time(portfolio.saved_at)} ／ <Link href="/portfolio">口座・保有を編集</Link></p>
    <p className="notice">ここでは入力を保存できます。PCの保有台帳への反映と比較結果の表示は準備中です。空欄を0として計算しません。</p>
    {stale && <section className="panel"><h2>口座・保有が更新されています</h2><p>保存済みの補足設定は以前の口座・保有に対するものです。</p><button className="secondary-button" type="button" onClick={useCurrentPortfolio} disabled={busy}>最新の口座・保有に合わせて見直す</button></section>}
    <fieldset disabled={busy || stale} className="form-fields">
      <section className="panel"><div className="section-heading"><div className="section-number">01</div><div><h2>現金と投資上限</h2><p>口座・保有画面で入力した金額が何を表すかを確認します。</p></div></div>
        <label className="field">各口座に入力した現金の意味（全口座共通）<select value={draft.cash_basis ?? ""} onChange={event => change({ ...draft, cash_basis: event.target.value as PersonalSettings["cash_basis"] || null })}><option value="">未確認</option>{Object.entries(cashLabels).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <p className="muted">投資上限：{number(portfolio.portfolio.investment_budget_yen)}{portfolio.portfolio.investment_budget_yen !== null && "円"} ／ 希望する最大下落率：{number(portfolio.portfolio.maximum_drawdown_percent)}{portfolio.portfolio.maximum_drawdown_percent !== null && "%"}</p>
        <label className="check-field"><input type="checkbox" checked={draft.budget_basis !== null} onChange={event => change({ ...draft, budget_basis: event.target.checked ? "maximum_total_equity_market_value" : null })}/>投資上限を「全口座で保有する株式の時価合計の上限」として比較する</label>
        <p className="footnote">追加購入に使う現金額だけを意味するものではありません。既存保有が上限を超えていても、現状維持を比較対象に残します。</p>
      </section>
      <section className="panel"><div className="section-heading"><div className="section-number">02</div><div><h2>口座の残高・損益</h2><p>証券会社の画面などで確認した内容を入力します。0円と未確認は区別します。</p></div></div>
        <label className="field">損益の対象年<input type="number" inputMode="numeric" min="2000" max="2200" step="1" placeholder="例：2026" value={draft.tax_year ?? ""} onChange={event => change({ ...draft, tax_year: event.target.value === "" ? null : Number(event.target.value) })}/></label>
        {!portfolio.portfolio.accounts.length && <p className="muted">口座は未登録です。<Link href="/portfolio">口座・保有画面で追加</Link>できます。</p>}
        {draft.accounts.map(item => { const source = portfolio.portfolio.accounts.find(source => source.id === item.account_id); if (!source) return null;
          return <fieldset className="entry-card" key={item.account_id}><legend>{source.name}（{accountTypeLabels[source.account_type]}）</legend><p className="muted">口座画面の現金：{number(source.available_cash_yen)}{source.available_cash_yen !== null && "円"}</p><div className="form-grid">
            <AmountField label="注文中などで確保されている現金（円）" value={item.reserved_cash_yen} onChange={value => accountChange(item.account_id, { reserved_cash_yen: value })}/>
            <label className="field">未反映の取引・決済<select value={item.pending_activity} onChange={event => accountChange(item.account_id, { pending_activity: event.target.value as Account["pending_activity"] })}>{Object.entries(pendingLabels).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            {Object.entries(taxLabels).filter(([key]) => !key.startsWith("nisa_") || source.account_type === "nisa" || item[key as keyof typeof taxLabels] !== null).map(([key,label]) => <AmountField key={key} label={label} value={item[key as keyof typeof taxLabels]} onChange={value => accountChange(item.account_id, { [key]: value })}/>)}
          </div>{source.account_type === "nisa" && <p className="footnote">残り枠は購入可能な金額です。この研究比較では売却によって同日中の購入枠を増やしません。</p>}</fieldset>;
        })}
      </section>
      <section className="panel"><div className="section-heading"><div className="section-number">03</div><div><h2>費用と税の計算条件</h2><p>全口座共通の研究用条件です。分からないものは空欄で保存できます。</p></div></div>
        <details className="settings-details"><summary>手数料・価格差を入力</summary><p className="muted">1 bps = 0.01%。価格差の全幅は、1回の取引では半分を費用として扱います。</p><div className="form-grid">
          {Object.entries(costLabels).map(([key,label]) => <AmountField key={key} label={label} value={draft.cost_assumptions[key as keyof typeof costLabels]} onChange={value => change({ ...draft, cost_assumptions: { ...draft.cost_assumptions, [key]: value } })}/>)}
        </div><label className="check-field"><input type="checkbox" checked={draft.cost_assumptions.zero_commission_confirmed} onChange={event => change({ ...draft, cost_assumptions: { ...draft.cost_assumptions, zero_commission_confirmed: event.target.checked } })}/>この口座条件では手数料が無料であることを確認した</label><p className="footnote">無料の確認だけで金額を自動入力しません。手数料0円でも、価格差・ずれ・市場への影響は別の項目です。</p></details>
        <details className="settings-details"><summary>推定税の条件を入力</summary><div className="form-grid">
          <label className="field">この税計算条件を使い始める日<input type="date" value={draft.tax_assumptions.effective_from ?? ""} onChange={event => change({ ...draft, tax_assumptions: { ...draft.tax_assumptions, effective_from: event.target.value || null } })}/></label>
          <AmountField label="課税口座の推定税率（%）" value={draft.tax_assumptions.taxable_rate_percent} onChange={value => change({ ...draft, tax_assumptions: { ...draft.tax_assumptions, taxable_rate_percent: value } })}/>
          <AmountField label="NISA枠を手放す機会費用の率（研究用・%）" value={draft.tax_assumptions.nisa_opportunity_cost_percent} onChange={value => change({ ...draft, tax_assumptions: { ...draft.tax_assumptions, nisa_opportunity_cost_percent: value } })}/>
        </div><p className="footnote">NISAの機会費用は税金ではなく、売却に対する研究用の調整です。ここで税申告額は確定しません。</p></details>
        <ResearchConditions/><label className="check-field"><input type="checkbox" checked={draft.research_conditions_reviewed} onChange={event => change({ ...draft, research_conditions_reviewed: event.target.checked })}/>上記の固定条件を研究用比較の条件として確認した</label>
      </section>
      <button className="primary-button" type="button" onClick={review}>入力内容を確認</button>
    </fieldset>
    {error && <p className="form-error" role="alert">{error}</p>}{message && <p className="form-success" role="status">{message}</p>}
    {preview && <section className="panel confirmation" aria-label="補足設定の保存確認"><h2>この補足設定を保存します</h2>
      <p>現金：{preview.cash_basis ? cashLabels[preview.cash_basis] : "未確認"} ／ 投資上限の意味：{preview.budget_basis ? "確認済み" : "未確認"} ／ 対象年：{preview.tax_year ?? "未入力"}</p>
      {preview.accounts.map(item => <div className="entry-card" key={item.account_id}><h3>{portfolio.portfolio.accounts.find(a => a.id === item.account_id)?.name}</h3><p>確保中の現金：{number(item.reserved_cash_yen)} ／ 取引・決済：{pendingLabels[item.pending_activity]}</p>{Object.entries(taxLabels).map(([key,label]) => <p key={key}>{label}：{number(item[key as keyof typeof taxLabels])}</p>)}</div>)}
      {Object.entries(costLabels).map(([key,label]) => <p key={key}>{label}：{number(preview.cost_assumptions[key as keyof typeof costLabels])}</p>)}
      <p>手数料無料：{preview.cost_assumptions.zero_commission_confirmed ? "確認済み" : "未確認"} ／ 税条件開始日：{preview.tax_assumptions.effective_from ?? "未入力"}</p><p>推定税率：{number(preview.tax_assumptions.taxable_rate_percent)}% ／ NISA機会費用：{number(preview.tax_assumptions.nisa_opportunity_cost_percent)}%</p><p>研究用比較条件：{preview.research_conditions_reviewed ? "確認済み" : "未確認"}</p>
      {inputGaps(preview, portfolio.portfolio).length > 0 && <details className="settings-details"><summary>まだ確認が必要な入力（{inputGaps(preview, portfolio.portfolio).length}項目）</summary><ul>{inputGaps(preview, portfolio.portfolio).map(value => <li key={value}>{value}</li>)}</ul><p className="muted">未入力のまま保存できます。これらがそろっても、台帳・市場データ・モデルの検証は別に必要です。</p></details>}
      <div className="button-row"><button className="primary-button" type="button" disabled={busy} onClick={save}>この内容を保存</button><button className="secondary-button" type="button" disabled={busy} onClick={() => setPreview(null)}>入力へ戻る</button></div>
    </section>}
    {saved && <section className="panel settings-export"><h2>保存済みの設定</h2><p className="muted">保存内容をJSONとして書き出せます。PC取込と台帳への確定は別の操作です。</p><button className="secondary-button" type="button" disabled={busy} onClick={download}>保存済みの設定を書き出す</button></section>}
  </div>;
}

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api";
import { SaveProgress } from "./SaveProgress";
import { blankAccount, costLabels, emptySettings, gapLabel, taxLabels, type AccountSettings,
  type InitialLedgerPreview, type PersonalSettings, type Readiness, type SavedPortfolio,
  type SavedSettings, type SettingsResponse } from "./personal";

function Amount({ label, value, change }: { label: string; value: string | null; change: (next: string | null) => void }) {
  return <label>{label}<input inputMode="decimal" placeholder="未確認なら空欄" value={value ?? ""} onChange={event => change(event.target.value || null)} /></label>;
}

export function MobilePersonalPanel({ profile, disabled }: { profile: SavedPortfolio | null; disabled: boolean }) {
  const [saved, setSaved] = useState<SavedSettings | null>(null);
  const [draft, setDraft] = useState<PersonalSettings | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [preview, setPreview] = useState<InitialLedgerPreview | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      apiGet<SettingsResponse>("/api/v1/mobile/personal/settings"),
      apiGet<Readiness>("/api/v1/mobile/personal/readiness"),
    ]).then(([result, ready]) => {
      if (cancelled) return;
      setSaved(result.saved); setReadiness(ready);
      setDraft(result.saved?.settings ?? (result.current_portfolio ? emptySettings(result.current_portfolio) : null));
      setLoaded(true); setPreview(null); setConfirm(false);
    }).catch(() => { if (!cancelled) setMessage("補足設定を読み込めません。保存済みの口座・保有を読み直してください。"); });
    return () => { cancelled = true; };
  }, [profile?.revision_id, reload]);

  const stale = draft !== null && draft.portfolio_revision_id !== profile?.revision_id;
  const blocked = disabled || busy || !loaded || stale;
  function change(value: PersonalSettings) { setDraft(value); setPreview(null); setConfirm(false); setMessage(""); }
  function accountChange(id: string, value: Partial<AccountSettings>) {
    if (draft) change({ ...draft, accounts: draft.accounts.map(x => x.account_id === id ? { ...x, ...value } : x) });
  }
  async function act(task: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setMessage("");
    try { await task(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "入力と保存状態を確認してください。"); }
    finally { setBusy(false); }
  }
  async function refresh() { setReadiness(await apiGet<Readiness>("/api/v1/mobile/personal/readiness")); }
  if (!profile || !draft) return <section className="section"><h2>補足設定と初回台帳</h2><p>先に口座・保有を保存してください。未定の金額は空欄のまま保存できます。</p>{message && <p role="status">{message}</p>}</section>;
  const gaps = [...new Set((readiness?.input_gaps ?? []).map(gapLabel))];
  const reasons = [...new Set((readiness?.comparison.blocking_reasons ?? []).map(x => gapLabel(x.code)))];
  return <section className="section" aria-label="補足設定と初回台帳">
    <h2>補足設定と初回台帳</h2>
    {busy && <SaveProgress label="端末で確認・保存中…" />}
    <p>未確認の項目は空欄で保存できます。空欄を0として計算しません。入力の保存と、初回残高を台帳へ確定する操作は別です。</p>
    <button className="button button--secondary" disabled={busy || disabled} onClick={() => {
      setLoaded(false); setPreview(null); setConfirm(false); setReload(value => value + 1);
    }}>補足設定を読み直す</button>
    {disabled && <p>口座・保有に未保存の変更があります。先に保存してください。</p>}
    {stale && <div><p>口座・保有が更新されています。補足設定を見直してください。</p>
      <button className="button button--secondary" disabled={disabled || busy} onClick={() => change({ ...draft,
        portfolio_revision_id: profile.revision_id, research_conditions_reviewed: false,
        accounts: profile.portfolio.accounts.map(x => draft.accounts.find(old => old.account_id === x.id) ?? blankAccount(x.id)),
      })}>最新の口座・保有に合わせて見直す</button></div>}
    <fieldset disabled={blocked}>
      <legend>現金・口座・税の補足</legend>
      <label>口座に入力した現金の意味<select value={draft.cash_basis ?? ""} onChange={event => change({ ...draft, cash_basis: event.target.value as PersonalSettings["cash_basis"] || null })}>
        <option value="">未確認</option><option value="total_including_reserved">確保中の金額を含む総現金</option><option value="deployable_after_reserved">確保中の金額を除いた買付余力</option>
      </select></label>
      <label><input type="checkbox" checked={draft.budget_basis !== null} onChange={event => change({ ...draft, budget_basis: event.target.checked ? "maximum_total_equity_market_value" : null })} />投資上限は全口座で保有する株式の時価合計に対する上限です</label>
      <label>損益の対象年<input type="number" min="2000" max="2200" value={draft.tax_year ?? ""} onChange={event => change({ ...draft, tax_year: event.target.value ? Number(event.target.value) : null })} /></label>
      {profile.portfolio.accounts.map(source => {
        const item = draft.accounts.find(x => x.account_id === source.id);
        if (!item) return null;
        return <fieldset key={source.id}><legend>{source.name}</legend>
          <Amount label="確保中の現金（円）" value={item.reserved_cash_yen} change={next => accountChange(source.id, { reserved_cash_yen: next })} />
          <label>未反映の取引・決済・入出金<select value={item.pending_activity} onChange={event => accountChange(source.id, { pending_activity: event.target.value as AccountSettings["pending_activity"] })}>
            <option value="unknown">まだ確認していない</option><option value="none">未反映のものはない</option><option value="pending">未反映・未決済のものがある</option>
          </select></label>
          {(Object.entries(taxLabels) as [keyof typeof taxLabels, string][]).filter(([key]) => source.account_type === "nisa" || !key.startsWith("nisa_") || item[key] !== null).map(([key, label]) =>
            <Amount key={key} label={label} value={item[key]} change={next => accountChange(source.id, { [key]: next })} />)}
        </fieldset>;
      })}
      <details><summary>費用と税の計算条件</summary><p>bpsは1万分の1です。税率や手数料は自動補完しません。</p>
        {(Object.entries(costLabels) as [keyof typeof costLabels, string][]).map(([key, label]) => <Amount key={key} label={label} value={draft.cost_assumptions[key]} change={next => change({ ...draft, cost_assumptions: { ...draft.cost_assumptions, [key]: next } })} />)}
        <label><input type="checkbox" checked={draft.cost_assumptions.zero_commission_confirmed} onChange={event => change({ ...draft, cost_assumptions: { ...draft.cost_assumptions, zero_commission_confirmed: event.target.checked } })} />手数料を0とする場合、無料の適用条件を確認しました</label>
        <label>税の条件の適用開始日<input type="date" value={draft.tax_assumptions.effective_from ?? ""} onChange={event => change({ ...draft, tax_assumptions: { ...draft.tax_assumptions, effective_from: event.target.value || null } })} /></label>
        <Amount label="課税口座の想定税率（%）" value={draft.tax_assumptions.taxable_rate_percent} change={next => change({ ...draft, tax_assumptions: { ...draft.tax_assumptions, taxable_rate_percent: next } })} />
        <Amount label="NISA枠の機会費用の仮定（%）" value={draft.tax_assumptions.nisa_opportunity_cost_percent} change={next => change({ ...draft, tax_assumptions: { ...draft.tax_assumptions, nisa_opportunity_cost_percent: next } })} />
      </details>
      <details><summary>研究用比較で使う条件</summary><p>20日予測で比較し、5日予測は参考とします。売買は100株単位、最大10銘柄、1銘柄10%・同一業種30%まで、現金10%以上。売買総額は資産の100%まで、1銘柄の注文は平均日次売買代金の5%までとします。</p><p>費用・推定税・下側リスク・不確実性を考慮し、現状維持から1,000円以上改善する案を比較します。下側リスク・不確実性は各1倍、追加の集中・下落確率・回転ペナルティと金額バッファーは0です。最大下落率の希望から条件を自動設定せず、損失額を保証しません。NISAの残り購入枠は売却で同日回復させません。</p></details>
      <label>株数の探索方法<select value={draft.research_decision_policy} onChange={event => change({ ...draft,
        research_decision_policy: event.target.value as PersonalSettings["research_decision_policy"], research_conditions_reviewed: false,
      })}><option value="daily-decision-engine-v3-bounded">300社向け</option>
        <option value="daily-decision-engine-v2">全組合せ</option></select></label>
      <p>{draft.research_decision_policy === "daily-decision-engine-v3-bounded"
        ? "HOLD・現金化・保有調整・乗り換えを有限回で比較します。すべての銘柄・口座を検討しますが、最良の組合せは保証しません。"
        : "全組合せを比較し、上限を超える場合は計算を止めます。別の探索方法へ自動変更しません。"}</p>
      <label><input type="checkbox" checked={draft.research_conditions_reviewed} onChange={event => change({ ...draft, research_conditions_reviewed: event.target.checked })} />探索方法を含む研究用の比較条件を確認しました</label>
      <button className="button" onClick={() => void act(async () => {
        const result = await apiPost<SettingsResponse>("/api/v1/mobile/personal/settings", { expected_revision_id: saved?.revision_id ?? null, settings: draft });
        setSaved(result.saved); setDraft(result.saved!.settings); setPreview(null); setConfirm(false);
        await refresh(); setMessage("補足設定を端末に保存しました。未入力は未入力のまま保持します。");
      })}>補足設定を保存</button>
    </fieldset>
    {gaps.length > 0 && <div><h3>まだ確認が必要な入力</h3><ul>{gaps.map(x => <li key={x}>{x}</li>)}</ul></div>}
    <h3>初回残高の確認</h3><p>保存済み入力から一度だけ初回台帳を作成します。保有株がある場合は、保存済みの未調整終値を確認します。確定後の台帳は入力欄の編集では変更しません。</p>
    <button className="button button--secondary" disabled={blocked || draft !== saved?.settings} onClick={() => void act(async () => {
      setPreview(await apiPost<InitialLedgerPreview>("/api/v1/mobile/personal/initial/preview", {})); setConfirm(false);
    })}>初回残高の確認内容を作る</button>
    {preview && <div>{preview.blocking_reasons.length > 0 ? <ul>{preview.blocking_reasons.map(code => <li key={code}>{gapLabel(code)}</li>)}</ul> : <>
      <p>価格の参照日：{preview.prices.date ?? "保有株なしのため価格参照なし"}</p>
      {preview.portfolio?.accounts.map(account => { const cash = preview.portfolio!.cash.find(x => x.account_bucket_id === account.account_id)!; return <p key={account.account_id}>{account.display_name}：総現金 {cash.available_cash}円／確保中 {cash.reserved_cash}円</p>; })}
      {preview.portfolio?.positions.map(x => <p key={`${x.account_bucket_id}:${x.symbol}`}>{profile.portfolio.accounts.find(a => a.id === x.account_bucket_id)?.name}・{x.symbol} {x.shares}株／取得単価 {x.average_acquisition_price}円／参考価格 {x.market_price}円</p>)}
      <label><input type="checkbox" checked={confirm} onChange={event => setConfirm(event.target.checked)} />この口座・保有・現金・税の保存内容を初回台帳に確定します</label>
      <button className="button" disabled={blocked || !confirm} onClick={() => void act(async () => {
        await apiPost("/api/v1/mobile/personal/initial/confirm", { preview_id: preview.preview_id, confirmed: true });
        setPreview(null); setConfirm(false); await refresh(); setMessage("初回台帳を確定しました。ホームで確認できます。実注文は行いません。");
      })}>この内容を初回台帳に確定</button>
    </>}</div>}
    <h3>個人比較の準備状況</h3><p>{readiness?.comparison.ledger_portfolio_id ? "初回台帳は登録済みです。" : "初回台帳は未確定です。"} 採用モデルと最新予測が揃うまで、研究用表示を続けます。</p>
    {reasons.length > 0 && <ul>{reasons.map(x => <li key={x}>{x}</li>)}</ul>}
    <p role="status">{busy ? "端末内で処理しています…" : message}</p>
  </section>;
}

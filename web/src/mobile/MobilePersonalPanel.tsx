import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../api";
import { SaveProgress } from "./SaveProgress";
import { SbiConditions } from "./SbiConditions";
import { Link } from "react-router-dom";
import { Field, KV, SettingGroup } from "../Adopted";
import { blankAccount, costLabels, emptySettings, gapLabel, taxLabels, type AccountSettings,
  type InitialLedgerPreview, type PersonalSettings, type Readiness, type SavedPortfolio,
  type SavedSettings, type SettingsResponse } from "./personal";

function Amount({ label, value, change }: { label: string; value: string | null; change: (next: string | null) => void }) {
  return <label>{label}<input inputMode="decimal" placeholder="未確認なら空欄" value={value ?? ""} onChange={event => change(event.target.value || null)} /></label>;
}

export const accountStepTitles = { portfolio: "現金・買付余力", nisa: "NISA残枠", conditions: "取引の確認", balances: "初回残高" };
export type AccountStep = keyof typeof accountStepTitles;

export function MobilePersonalPanel({ profile, disabled, step = "all", onStep, portfolioStatus = "確認中" }: {
  profile: SavedPortfolio | null; disabled: boolean; step?: AccountStep | "overview" | "all" | "method" | "taxes";
  onStep?: (step: AccountStep) => void; portfolioStatus?: string;
}) {
  const [saved, setSaved] = useState<SavedSettings | null>(null);
  const [draft, setDraft] = useState<PersonalSettings | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [readinessBusy, setReadinessBusy] = useState(false);
  const [preview, setPreview] = useState<InitialLedgerPreview | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const acting = useRef(false);
  const draftTouched = useRef(false);
  const [message, setMessage] = useState("");
  const [reload, setReload] = useState(0);
  const [manualConditions, setManualConditions] = useState(false);
  const refreshEpoch = useRef(0);
  const [refreshError, setRefreshError] = useState("");
  const invalidateRefresh = useCallback(() => { refreshEpoch.current++; }, []);
  useEffect(() => {
    refreshEpoch.current++;
    setLoaded(false);
    let cancelled = false;
    // Comparison and price-backed preview run only on explicit request.
    void apiGet<SettingsResponse>("/api/v1/mobile/personal/settings").then(result => {
      if (cancelled) return;
      setSaved(result.saved); setRefreshError("");
      setDraft(previous => draftTouched.current && previous ? previous : result.saved?.settings ?? (result.current_portfolio ? emptySettings(result.current_portfolio) : null));
      setLoaded(true); setPreview(null); setConfirm(false);
    }).catch(() => { if (!cancelled) { setRefreshError("入力状況を確認できません。もう一度読み込んでください。"); setMessage("補足設定を読み込めません。保存済みの口座・保有を読み直してください。"); } });
    return () => { cancelled = true; invalidateRefresh(); };
  }, [reload, profile?.revision_id, invalidateRefresh]);
  useEffect(() => {
    invalidateRefresh(); setReadiness(null); setReadinessBusy(false); setRefreshError(""); setPreview(null); setConfirm(false);
  }, [profile?.revision_id, invalidateRefresh]);
  useEffect(() => {
    if (loaded && profile) setDraft(previous => previous ?? emptySettings(profile));
  }, [loaded, profile]);

  const stale = draft !== null && draft.portfolio_revision_id !== profile?.revision_id;
  const blocked = disabled || busy || !loaded || stale;
  function change(value: PersonalSettings) { draftTouched.current = true; setDraft(value); setPreview(null); setConfirm(false); setMessage(""); }
  function accountChange(id: string, value: Partial<AccountSettings>) {
    if (draft) change({ ...draft, accounts: draft.accounts.map(x => x.account_id === id ? { ...x, ...value } : x) });
  }
  async function act(task: () => Promise<void>) {
    if (acting.current) return;
    acting.current = true;
    refreshEpoch.current++;
    setReadiness(null); setReadinessBusy(false); setRefreshError("");
    setBusy(true); setMessage("");
    try { await task(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "入力と保存状態を確認してください。"); }
    finally { acting.current = false; setBusy(false); }
  }
  function refresh() {
    if (readinessBusy) return;
    const epoch = ++refreshEpoch.current;
    setReadiness(null); setReadinessBusy(true); setRefreshError("");
    void apiGet<Readiness>("/api/v1/mobile/personal/readiness").then(value => {
      if (epoch === refreshEpoch.current) setReadiness(value);
    }).catch(() => {
      if (epoch === refreshEpoch.current) setRefreshError("準備状況を取得できませんでした。もう一度確認してください。");
    }).finally(() => { if (epoch === refreshEpoch.current) setReadinessBusy(false); });
  }
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(saved?.settings ?? (profile ? emptySettings(profile) : null));
  const ownGaps = readiness?.input_gaps.filter(code => ![
    "manual_input", "accounts", "holdings_status", "available_cash_yen", "account_classification",
    "average_acquisition_price_yen", "investment_budget_yen", "maximum_drawdown_percent",
  ].includes(code)) ?? [];
  const settingsStatus = refreshError ? "確認できません" : dirty ? "未保存" : !loaded ? "確認中"
    : !saved ? "未入力" : stale || ownGaps.length > 0 ? "要確認" : "入力済み";
  const ledgerStatus = refreshError ? "確認できません" : !readiness ? "未確認"
    : readiness.comparison.ledger_portfolio_id ? "登録済み" : "未登録";
  if (step === "overview") return <section className="account-setup-menu" aria-label="証券口座の登録項目">
    {([
      ["portfolio", "現金・買付余力", "SBI証券の現在残高", portfolioStatus],
      ["nisa", "NISA残枠", "成長投資枠", ledgerStatus],
      ["conditions", "取引の確認", "SBIの手数料・残高の確認", settingsStatus],
      ["balances", "初回残高", "開始時の資産・履歴", ledgerStatus],
    ] as const).map(([id, title, hint, status]) => <button key={id} type="button" className="account-setup-row" onClick={() => onStep?.(id)}>
      <span className="account-setup-copy"><strong>{title}</strong><small>{hint}</small></span>
      <span className={`account-setup-status${status === "入力済み" || status === "登録済み" ? " account-setup-status--done" : ""}`}>{status}</span>
      <span className="account-setup-arrow" aria-hidden="true">›</span>
    </button>)}
    <button className="button button--secondary" disabled={blocked || readinessBusy} onClick={refresh}>{readinessBusy ? "準備状況を確認中…" : "準備状況を確認"}</button>
    {refreshError && <p role="alert">{refreshError}</p>}
    {refreshError && <button className="button button--secondary" onClick={() => setReload(value => value + 1)}>入力状況を再確認</button>}
  </section>;
  if (step === "portfolio" || step === "nisa") return null;
  if (!profile || !draft) return <section className="section"><p>{!loaded && !refreshError ? "登録内容を読み込んでいます…" : "先に口座・保有を保存してください。"}</p>{message && <><p role="status">{message}</p><button className="button" disabled={busy} onClick={() => setReload(value => value + 1)}>補足設定を読み直す</button></>}</section>;
  const focused = step === "method" || step === "taxes";
  const gaps = [...new Set((readiness?.input_gaps ?? []).map(gapLabel))];
  const reasons = [...new Set((readiness?.comparison.blocking_reasons ?? []).map(x => gapLabel(x.code)))];
  async function saveSettings() {
    const result = await apiPost<SettingsResponse>("/api/v1/mobile/personal/settings", { expected_revision_id: saved?.revision_id ?? null, settings: draft });
    draftTouched.current=false; setSaved(result.saved); setDraft(result.saved!.settings); setPreview(null); setConfirm(false); setMessage("保存しました。");
  }
  if (focused) return <div className={`subscreen ${step==="taxes" ? "sub-settings" : "advanced-domain"}`}>
    {busy && <SaveProgress label="端末で確認・保存中…" />}
    {disabled && <p role="status">口座・保有に未保存の変更があります。先に保存してください。</p>}
    {stale && <div className="card"><p>口座・保有が更新されています。補足設定を見直してください。</p><button className="button secondary" disabled={disabled || busy} onClick={()=>change({...draft,portfolio_revision_id:profile.revision_id,research_conditions_reviewed:false,accounts:profile.portfolio.accounts.map(x=>draft.accounts.find(old=>old.account_id===x.id) ?? blankAccount(x.id))})}>最新の口座・保有に合わせて見直す</button></div>}
    <fieldset className="account-form" disabled={blocked}>
    {step==="taxes" ? <div className="ss-compact">
      <SettingGroup number="01" title="口座・税区分"><KV label="証券口座" value={`登録済み・${profile.portfolio.accounts.length}口座`} /><KV label="管理対象" value={profile.portfolio.accounts.map(x=>x.name).join("・")} /><Field label="対象年"><input className="input" type="number" min="2000" max="2200" value={draft.tax_year ?? ""} onChange={e=>change({...draft,tax_year:e.target.value ? Number(e.target.value) : null})} /></Field>
      {profile.portfolio.accounts.map(x=><KV key={x.id} label={x.name} value={x.account_type==="nisa" ? "NISA" : x.account_type==="taxable_general" ? "一般口座" : `特定口座・源泉徴収${x.withholding_mode==="withholding" ? "あり" : x.withholding_mode==="no_withholding" ? "なし" : "未確認"}`} />)}</SettingGroup>
      <SettingGroup number="02" title="年間損益・NISA">{profile.portfolio.accounts.map(source=>{const item=draft.accounts.find(x=>x.account_id===source.id);return item && <div className="stack" key={source.id}><h4 className="small muted">{source.name}</h4><Field label="未反映の取引・決済・入出金"><select className="input" value={item.pending_activity} onChange={e=>accountChange(source.id,{pending_activity:e.target.value as AccountSettings["pending_activity"]})}><option value="unknown">まだ確認していない</option><option value="none">未反映のものはない</option><option value="pending">未反映・未決済のものがある</option></select></Field>
      {(Object.entries(taxLabels) as [keyof typeof taxLabels,string][]).filter(([key])=>!(readiness?.comparison.ledger_portfolio_id && key.startsWith("nisa_")) && (source.account_type==="nisa" || !key.startsWith("nisa_") || item[key]!==null)).map(([key,label])=><Field key={key} label={label}><input className="input" inputMode="decimal" value={item[key] ?? ""} onChange={e=>accountChange(source.id,{[key]:e.target.value || null})} /></Field>)}</div>;})}
      <Link className="quiet-link" to="/settings?edit=accounts&step=nisa">現在のNISA残枠を確認・変更 ›</Link></SettingGroup>
      <SettingGroup number="03" title="手数料・計算前提">{(Object.entries(costLabels) as [keyof typeof costLabels,string][]).map(([key,label])=><Field key={key} label={label}><input className="input" inputMode="decimal" value={draft.cost_assumptions[key] ?? ""} onChange={e=>change({...draft,cost_assumptions:{...draft.cost_assumptions,[key]:e.target.value || null}})} /></Field>)}
      <label className="row"><input type="checkbox" checked={draft.cost_assumptions.zero_commission_confirmed} onChange={e=>change({...draft,cost_assumptions:{...draft.cost_assumptions,zero_commission_confirmed:e.target.checked}})} />無料の適用条件を確認しました</label>
      <Field label="税の条件の適用開始日"><input className="input" type="date" value={draft.tax_assumptions.effective_from ?? ""} onChange={e=>change({...draft,tax_assumptions:{...draft.tax_assumptions,effective_from:e.target.value || null}})} /></Field>
      <Field label="課税口座の想定税率（%）"><input className="input" inputMode="decimal" value={draft.tax_assumptions.taxable_rate_percent ?? ""} onChange={e=>change({...draft,tax_assumptions:{...draft.tax_assumptions,taxable_rate_percent:e.target.value || null}})} /></Field>
      <Field label="NISA枠の機会費用の仮定（%）"><input className="input" inputMode="decimal" value={draft.tax_assumptions.nisa_opportunity_cost_percent ?? ""} onChange={e=>change({...draft,tax_assumptions:{...draft.tax_assumptions,nisa_opportunity_cost_percent:e.target.value || null}})} /></Field></SettingGroup>
    </div> : <div className="card stack">
      <section className="advanced-section"><h3 className="section-title">予測対象</h3><Field label="対象銘柄の選び方"><input className="input" readOnly value="保存モデルの対象集合・全保有" /></Field><Field label="予測期間"><input className="input" readOnly value="5日・20日" /></Field></section>
      <section className="advanced-section"><h3 className="section-title">株数探索</h3><Field label="探索方法"><select className="input" value={draft.research_decision_policy} onChange={e=>change({...draft,research_decision_policy:e.target.value as PersonalSettings["research_decision_policy"],research_conditions_reviewed:false})}><option value="daily-decision-engine-v3-bounded">300社向け</option><option value="daily-decision-engine-v2">全組合せ</option></select></Field><KV label="売買単位" value="100株" /><p className="small muted">{draft.research_decision_policy==="daily-decision-engine-v3-bounded" ? "最良の組合せは保証しません。" : "計算上限を超える場合は停止します。"}</p></section>
      <section className="advanced-section"><h3 className="section-title">研究用条件</h3><KV label="最大保有銘柄数" value="10銘柄" /><KV label="銘柄 / 業種上限" value="10% / 30%" /><KV label="最低現金 / 売買総額上限" value="資産の10% / 100%" /><KV label="注文の流動性上限" value="平均日次売買代金の5%" /><KV label="現状維持からの改善" value="1,000円以上" /><KV label="下側リスク / 不確実性" value="各1倍" /><KV label="追加ペナルティ・金額バッファー" value="0" /></section>
      <section className="advanced-section"><h3 className="section-title">保存</h3><label className="row"><input type="checkbox" checked={draft.research_conditions_reviewed} onChange={e=>change({...draft,research_conditions_reviewed:e.target.checked})} />探索方法を含む研究用の比較条件を確認しました</label></section>
    </div>}
    <div className="subactions"><button className="button" onClick={()=>void act(saveSettings)}>{step==="taxes" ? "設定を保存" : "計算方式を保存"}</button>{step==="method" && <Link className="button secondary" to="/settings?edit=conditions">日常の運用条件</Link>}</div>
    </fieldset>{!busy && message && <p className="ss-status" role="status">{message}</p>}{refreshError && <p role="status">{refreshError}</p>}
  </div>;
  return <section className="section account-editor" aria-label="補足設定と初回台帳">
    {step === "all" && <h2>残高の登録</h2>}
    {busy && <SaveProgress label="端末で確認・保存中…" />}
    {(step === "all" || manualConditions) && step !== "balances" && <p className="setting-footnote">分からない項目は空欄で保存できます。</p>}
    {!loaded && <button className="button button--secondary" disabled={busy || disabled} onClick={() => {
      setLoaded(false); setPreview(null); setConfirm(false); setReload(value => value + 1);
    }}>補足設定を読み直す</button>}
    {disabled && <p>口座・保有に未保存の変更があります。先に保存してください。</p>}
    {stale && <div><p>口座・保有が更新されています。補足設定を見直してください。</p>
      <button className="button button--secondary" disabled={disabled || busy} onClick={() => change({ ...draft,
        portfolio_revision_id: profile.revision_id, research_conditions_reviewed: false,
        accounts: profile.portfolio.accounts.map(x => draft.accounts.find(old => old.account_id === x.id) ?? blankAccount(x.id)),
      })}>最新の口座・保有に合わせて見直す</button></div>}
    <fieldset className="account-form" hidden={step === "balances"} disabled={blocked}>
      <legend className={step !== "all" && !manualConditions ? "sr-only" : undefined}>現金・税金・費用の入力</legend>
      {step !== "all" && !focused && !manualConditions ? <SbiConditions profile={profile} draft={draft} change={change} onManual={() => setManualConditions(true)} currentLedger={!!readiness?.comparison.ledger_portfolio_id} /> : <>
      {step !== "all" && !focused && <button type="button" className="settings-back" onClick={() => setManualConditions(false)}>← かんたん設定へ</button>}
      <div hidden={focused} className="account-form-card"><h3>現金の扱い</h3>
      {!readiness?.comparison.ledger_portfolio_id && <label>口座に入力した現金の意味<select value={draft.cash_basis ?? ""} onChange={event => change({ ...draft, cash_basis: event.target.value as PersonalSettings["cash_basis"] || null })}>
        <option value="">未確認</option><option value="total_including_reserved">確保中の金額を含む総現金</option><option value="deployable_after_reserved">確保中の金額を除いた買付余力</option>
      </select></label>}
      <label><input type="checkbox" checked={draft.budget_basis !== null} onChange={event => change({ ...draft, budget_basis: event.target.checked ? "maximum_total_equity_market_value" : null })} />投資上限は全口座で保有する株式の時価合計に対する上限です</label>
      </div>
      <div className="account-form-card"><h3>口座ごとの内訳</h3>
      <label>損益の対象年<input type="number" min="2000" max="2200" value={draft.tax_year ?? ""} onChange={event => change({ ...draft, tax_year: event.target.value ? Number(event.target.value) : null })} /></label>
      {profile.portfolio.accounts.map(source => {
        const item = draft.accounts.find(x => x.account_id === source.id);
        if (!item) return null;
        return <fieldset key={source.id}><legend>{source.name}</legend>
          {!readiness?.comparison.ledger_portfolio_id && <Amount label="確保中の現金（円）" value={item.reserved_cash_yen} change={next => accountChange(source.id, { reserved_cash_yen: next })} />}
          <label>未反映の取引・決済・入出金<select value={item.pending_activity} onChange={event => accountChange(source.id, { pending_activity: event.target.value as AccountSettings["pending_activity"] })}>
            <option value="unknown">まだ確認していない</option><option value="none">未反映のものはない</option><option value="pending">未反映・未決済のものがある</option>
          </select></label>
          <section className="settings-disclosure"><h3 className="plain-section-title">この口座の税・NISA</h3>
          {(Object.entries(taxLabels) as [keyof typeof taxLabels, string][]).filter(([key]) => !(readiness?.comparison.ledger_portfolio_id && key.startsWith("nisa_")) && (source.account_type === "nisa" || !key.startsWith("nisa_") || item[key] !== null)).map(([key, label]) =>
            <Amount key={key} label={label} value={item[key]} change={next => accountChange(source.id, { [key]: next })} />)}
          </section>
        </fieldset>;
      })}
      </div>
      <div className="account-form-card"><h3>取引コスト・税の計算条件</h3><p>bpsは1万分の1です。価格差10・ずれ5・価格影響25bpsはアプリの計算仮定で、SBIの手数料ではありません。</p>
        {(Object.entries(costLabels) as [keyof typeof costLabels, string][]).map(([key, label]) => <Amount key={key} label={label} value={draft.cost_assumptions[key]} change={next => change({ ...draft, cost_assumptions: { ...draft.cost_assumptions, [key]: next } })} />)}
        <label><input type="checkbox" checked={draft.cost_assumptions.zero_commission_confirmed} onChange={event => change({ ...draft, cost_assumptions: { ...draft.cost_assumptions, zero_commission_confirmed: event.target.checked } })} />手数料を0とする場合、無料の適用条件を確認しました</label>
        <label>税の条件の適用開始日<input type="date" value={draft.tax_assumptions.effective_from ?? ""} onChange={event => change({ ...draft, tax_assumptions: { ...draft.tax_assumptions, effective_from: event.target.value || null } })} /></label>
        <Amount label="課税口座の想定税率（%）" value={draft.tax_assumptions.taxable_rate_percent} change={next => change({ ...draft, tax_assumptions: { ...draft.tax_assumptions, taxable_rate_percent: next } })} />
        <Amount label="NISA枠の機会費用の仮定（%）" value={draft.tax_assumptions.nisa_opportunity_cost_percent} change={next => change({ ...draft, tax_assumptions: { ...draft.tax_assumptions, nisa_opportunity_cost_percent: next } })} />
      </div>
      <div className="account-form-card"><h3>株数探索</h3>

      <label>探索方法<select value={draft.research_decision_policy} onChange={event => change({ ...draft,
        research_decision_policy: event.target.value as PersonalSettings["research_decision_policy"], research_conditions_reviewed: false,
      })}><option value="daily-decision-engine-v3-bounded">300社向け</option>
        <option value="daily-decision-engine-v2">全組合せ</option></select></label>
      <p>{draft.research_decision_policy === "daily-decision-engine-v3-bounded"
        ? "最良の組合せは保証しません。"
        : "計算上限を超える場合は停止します。"}</p>
      <section className="comparison-conditions"><h3 className="plain-section-title">研究用比較で使う条件</h3>
        <dl className="summary-list"><div><dt>予測期間</dt><dd>20日で比較・5日は参考</dd></div><div><dt>売買単位 / 最大保有</dt><dd>100株 / 10銘柄</dd></div><div><dt>銘柄 / 業種上限</dt><dd>10% / 30%</dd></div><div><dt>最低現金 / 売買総額上限</dt><dd>資産の10% / 100%</dd></div><div><dt>注文の流動性上限</dt><dd>平均日次売買代金の5%</dd></div><div><dt>現状維持からの改善</dt><dd>1,000円以上</dd></div><div><dt>下側リスク / 不確実性</dt><dd>各1倍</dd></div><div><dt>追加ペナルティ・金額バッファー</dt><dd>0</dd></div></dl>
        <p className="setting-footnote">費用・推定税を含めて比較します。許容下落率から条件を自動設定せず、損失額を保証しません。NISA枠は売却で同日回復させません。</p>
      </section>
      <label><input type="checkbox" checked={draft.research_conditions_reviewed} onChange={event => change({ ...draft, research_conditions_reviewed: event.target.checked })} />探索方法を含む研究用の比較条件を確認しました</label>
      </div>
      </>}
      <button className="button button--primary" onClick={() => void act(async () => {
        const result = await apiPost<SettingsResponse>("/api/v1/mobile/personal/settings", { expected_revision_id: saved?.revision_id ?? null, settings: draft });
        draftTouched.current = false;
        setSaved(result.saved); setDraft(result.saved!.settings); setPreview(null); setConfirm(false);
        setMessage("保存しました。");
      })}>補足設定を保存</button>
    </fieldset>
    {step !== "balances" && gaps.length > 0 && <div><h3>まだ確認が必要な入力</h3><ul>{gaps.map(x => <li key={x}>{x}</li>)}</ul></div>}
    <div hidden={step === "conditions" || focused} className="account-form-card">
    <h3>残高を確認して登録</h3>
    <p className="setting-footnote">最初の残高を登録します。登録後は入力欄の編集では変更されません。</p>
    {step === "balances" && loaded && (!saved || dirty || stale) && <p>先に取引の確認を確認・保存してください。{onStep && <button type="button" className="settings-back" onClick={() => onStep("conditions")}>取引の確認を開く →</button>}</p>}
    <button className="button button--secondary" disabled={blocked || !saved || dirty || !!readiness?.comparison.ledger_portfolio_id} onClick={() => void act(async () => {
      setPreview(await apiPost<InitialLedgerPreview>("/api/v1/mobile/personal/initial/preview", {})); setConfirm(false);
    })}>初回残高の確認内容を作る</button>
    {preview && <div>{preview.blocking_reasons.length > 0 ? <ul>{preview.blocking_reasons.map(code => <li key={code}>{gapLabel(code)}</li>)}</ul> : <>
      <p>価格の参照日：{preview.prices.date ?? "保有株なしのため価格参照なし"}</p>
      {preview.portfolio?.accounts.map(account => { const cash = preview.portfolio!.cash.find(x => x.account_bucket_id === account.account_id)!; return <p key={account.account_id}>{account.display_name}：総現金 {cash.available_cash}円／確保中 {cash.reserved_cash}円</p>; })}
      {preview.portfolio?.positions.map(x => <p key={`${x.account_bucket_id}:${x.symbol}`}>{profile.portfolio.accounts.find(a => a.id === x.account_bucket_id)?.name}・{x.symbol} {x.shares}株／取得単価 {x.average_acquisition_price}円／参考価格 {x.market_price}円</p>)}
      <label><input type="checkbox" checked={confirm} onChange={event => setConfirm(event.target.checked)} />この口座・保有・現金・税の保存内容を初回台帳に確定します</label>
      <button className="button" disabled={blocked || !confirm} onClick={() => void act(async () => {
        await apiPost("/api/v1/mobile/personal/initial/confirm", { preview_id: preview.preview_id, confirmed: true });
        setPreview(null); setConfirm(false); setMessage("残高を登録しました。ホームで確認できます。");
      })}>この内容を初回台帳に確定</button>
    </>}</div>}
    </div>
    <div hidden={step === "conditions" || focused}>
    <h3>登録状況</h3><button className="button button--secondary" disabled={blocked || readinessBusy} onClick={refresh}>{readinessBusy ? "準備状況を確認中…" : "準備状況を確認"}</button><p>{!readiness ? "準備状況は未確認です。" : readiness.comparison.ledger_portfolio_id ? "初回台帳は登録済みです。" : "初回台帳は未確定です。"} 採用モデルと最新予測が揃うまで、研究用表示を続けます。</p>
    {reasons.length > 0 && <ul>{reasons.map(x => <li key={x}>{x}</li>)}</ul>}
    </div>
    {!busy && message && <p role="status">{message}</p>}
    {refreshError && <p role="status">{refreshError}</p>}
  </section>;
}

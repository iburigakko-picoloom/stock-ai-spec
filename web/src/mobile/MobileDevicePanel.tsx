import { Activity, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { isAndroid, StockAI, type ReleaseInfo } from "./native";
import { MobileBackupPanel } from "./MobileBackupPanel";
import { MobilePersonalPanel, accountStepTitles, type AccountStep } from "./MobilePersonalPanel";
import { AllocationReadout, MinimumCashField, PolicyDataProvider, PolicySummary, RiskPolicyFields } from "./PolicySummary";
import { AppInfoPanel } from "./AppInfoPanel";
import { CurrentAccountPanel } from "./CurrentAccountPanel";
import { SaveProgress } from "./SaveProgress";
import { ChatGPTPanel } from "./ChatGPTPanel";
import { MobileMarketPanel } from "./MobileMarketPanel";
import { MobileModelPanel } from "./MobileModelPanel";
import { DailyControls, useDailyAutomation } from "./DailyPanel";
import type { LocalPortfolio, SavedPortfolio } from "./personal";
import { Field, SettingGroup } from "../Adopted";

export function MobileUpdateNotice(): ReactNode {
  const [release, setRelease] = useState<ReleaseInfo | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const installing = useRef(false);
  useEffect(() => {
    let active = true;
    if (isAndroid()) void StockAI.checkUpdate().then(value => { if (active) setRelease(value); }).catch(() => {
      // Startup/network failures never stop local use or discard existing state.
    });
    return () => { active = false; };
  }, []);
  if (!release?.available) return null;
  const versionCode = release.versionCode;
  async function install(): Promise<void> {
    if (installing.current) return;
    installing.current = true;
    setBusy(true);
    setMessage("APKを確認しています…");
    try {
      const result = await StockAI.installUpdate({ versionCode });
      setMessage(result.needsPermission ? "Androidの設定で更新を許可してから、もう一度更新ボタンを押してください。" : "Androidの確認画面でインストールしてください。");
    } catch {
      setMessage("更新を取得できませんでした。現在のアプリを引き続き使用できます。");
    } finally {
      installing.current = false;
      setBusy(false);
    }
  }
  return <section className="app-update" aria-label="アプリの更新">
    <div className="app-update-bar">
      <div className="app-update-copy"><strong>新しいバージョンがあります</strong><span>{release.versionName}</span></div>
      <button className="button button--primary app-update-button" disabled={busy} aria-busy={busy} onClick={() => { void install(); }}>{busy ? "確認中…" : "更新"}</button>
    </div>
    {release.notes && <section className="app-update-details"><h3 className="plain-section-title">変更内容を見る</h3><p tabIndex={0}>{release.notes}</p></section>}
    {message && <p className="app-update-message" role="status">{message}</p>}
  </section>;
}

const blank: LocalPortfolio = { schema_version: "manual-portfolio-v1", holdings_status: "unrecorded", investment_budget_yen: null, maximum_drawdown_percent: null, accounts: [], holdings: [] };

const panelTitles = { accounts: "証券口座", capital: "運用資金", risk: "許容下落率", market: "J-Quants・市場データ", model: "モデル管理", daily: "データ更新", chatgpt: "ChatGPT", backup: "バックアップ・復元", about: "アプリ情報・詳細", repair: "市場データの修復", method: "計算方式", conditions: "運用条件", taxes: "口座・税・手数料" };
type SettingsPanelId = keyof typeof panelTitles;
const iconPaths = {
  database: "M4 6c0-4 16-4 16 0S4 10 4 6Zm0 0v12c0 4 16 4 16 0V6M4 12c0 4 16 4 16 0",
  bank: "m3 8 9-5 9 5H3Zm2 3v7m7-7v7m7-7v7M3 21h18M3 18h18",
  calendar: "M7 3v4m10-4v4M4 10h16M5 5h14a1 1 0 0 1 1 1v14H4V6a1 1 0 0 1 1-1Zm3 9h1m6 0h1m-8 3h1",
  shield: "m12 3 8 4v6c0 4-5 7-8 9-3-2-8-5-8-9V7l8-4Zm-4 9 3 3 5-6",
  refresh: "M20 9a8 8 0 0 0-14-4L3 8m0-5v5h5M4 15a8 8 0 0 0 14 4l3-3m0 5v-5h-5",
  bell: "M5 17c2-3 1-5 2-9a5 5 0 0 1 10 0c1 4 0 6 2 9H5Zm5 3h4",
  cloud: "M7 18H6a4 4 0 0 1-1-8 7 7 0 0 1 14-1 4 4 0 0 1-1 9h-1m-5 3V11m-4 4 4-4 4 4",
  chat: "M4 4h16v12H9l-5 5V4Zm4 5h8m-8 3h5",
  info: "M12 8v1m0 3v5m9-5a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
};

function SettingsRow({ title, value, icon, onClick, checked, disabled = false, badge = false }: {
  title: string; value?: string; icon: keyof typeof iconPaths;
  onClick: () => void; checked?: boolean; disabled?: boolean; badge?: boolean;
}): ReactNode {
  return <button type="button" className={`settings-menu-row${checked === undefined ? "" : " settings-menu-row--switch"}`} onClick={onClick} disabled={disabled}
    role={checked === undefined ? undefined : "switch"} aria-checked={checked} aria-label={checked === undefined ? undefined : title}>
    <svg className="settings-menu-icon" viewBox="0 0 24 24" aria-hidden="true"><path d={iconPaths[icon]} /></svg>
    <span className="settings-menu-copy"><strong>{title}</strong></span>
    {checked === undefined ? <>
      {value && <span className={badge ? "settings-menu-value settings-menu-badge" : "settings-menu-value"}>{value}</span>}
      <svg className="settings-menu-chevron" viewBox="0 0 16 24" aria-hidden="true"><path d="m5 5 7 7-7 7" /></svg>
    </> : <span className={`settings-switch${checked ? " settings-switch--on" : ""}`} aria-hidden="true"><span /></span>}
  </button>;
}

export function SettingsPanel({ visible, children }: { visible: boolean; children: ReactNode }): ReactNode {
  const [visited, setVisited] = useState(visible);
  useEffect(() => { if (visible) setVisited(true); }, [visible]);
  // Defer unused panels, but retain drafts and in-flight work after first opening.
  if (!visible && !visited) return null;
  return <Activity mode={visible ? "visible" : "hidden"}><div className="settings-edit-content">{children}</div></Activity>;
}

export function MobileDevicePanel(): ReactNode {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const requested = params.get("edit");
  const selected = requested && Object.hasOwn(panelTitles, requested) ? requested as SettingsPanelId : null;
  const requestedStep = params.get("step");
  const accountStep = selected === "accounts" && requestedStep && Object.hasOwn(accountStepTitles, requestedStep) ? requestedStep as AccountStep : null;
  const heading = useRef<HTMLHeadingElement>(null);
  const daily = useDailyAutomation();
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [key, setKey] = useState("");
  const [portfolio, setPortfolio] = useState<LocalPortfolio>(blank);
  const [savedPortfolio, setSavedPortfolio] = useState<SavedPortfolio | null>(null);
  const [portfolioLoaded, setPortfolioLoaded] = useState(false);
  const [previewPortfolio, setPreviewPortfolio] = useState<SavedPortfolio | null>(null);
  const [portfolioError, setPortfolioError] = useState("");
  const [readAttempt, setReadAttempt] = useState(0);
  const loadedPortfolio = useRef<{ revision:string|null; attempt:number }|null>(null);
  const [loadError, setLoadError] = useState("");
  const [message, setMessage] = useState("");
  const [messageGroup, setMessageGroup] = useState("account");
  const [busy, setBusy] = useState(false);
  const acting = useRef(false);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [selected, accountStep]);
  useEffect(() => {
    if (!isAndroid()) return;
    void StockAI.keyStatus().then(value => setConfigured(value.configured)).catch(() => setLoadError(value => `${value}APIキーの保存状態を確認できません。再起動してください。`));
  }, []);
  useEffect(() => {
    if (!isAndroid()) return;
    let active = true;
    let finished = false;
    const timer = window.setTimeout(() => {
      if (!active || finished) return;
      finished = true;
      setPortfolioError("口座情報の確認に時間がかかっています。再確認してください。");
    }, 45_000);
    if (typeof StockAI.readSavedView === "function") {
      void StockAI.readSavedView({ path: "/api/v1/mobile/portfolio" }).then(saved => {
        if (active && !finished && saved.available && saved.readOnly && saved.savedAt
            && Number.isFinite(Date.parse(saved.savedAt)) && Date.parse(saved.savedAt) <= Date.now()) {
          setPreviewPortfolio(saved.body as SavedPortfolio | null);
        }
      }).catch(() => { /* Invalid display copies cannot enable editing. */ });
    }
    void apiGet<SavedPortfolio | null>("/api/v1/mobile/portfolio").then(value => {
      if (!active || finished) return;
      finished = true; window.clearTimeout(timer);
      const revision=value?.revision_id ?? null;
      if (!loadedPortfolio.current || loadedPortfolio.current.revision !== revision || loadedPortfolio.current.attempt !== readAttempt) setPortfolio(value?.portfolio ?? blank);
      loadedPortfolio.current={revision,attempt:readAttempt};
      setSavedPortfolio(value);
      setPortfolioLoaded(true);
      setPreviewPortfolio(null); setPortfolioError("");
    }).catch(() => {
      if (!active || finished) return;
      finished = true; window.clearTimeout(timer); setPreviewPortfolio(null);
      setPortfolioError("口座情報を確認できませんでした。再確認してください。");
    });
    return () => { active = false; window.clearTimeout(timer); };
  }, [readAttempt]);
  if (!isAndroid()) return null;
  function open(panel: SettingsPanelId): void { setParams({ edit: panel }, { state: { settingsList: true } }); }
  function openAccount(step: AccountStep): void { setParams({ edit: "accounts", step }, { state: { accountList: true } }); }
  function back(): void {
    if (accountStep) {
      if (location.state?.accountList) void navigate(-1);
      else setParams({ edit: "accounts" }, { replace: true });
      return;
    }
    if (location.state?.settingsList) void navigate(-1);
    else setParams({}, { replace: true });
  }
  async function action(task: () => Promise<unknown>, success: string, group = "account"): Promise<void> {
    if (acting.current) return;
    acting.current = true;
    setBusy(true); setMessage(""); setMessageGroup(group);
    try { await task(); setMessage(success); }
    catch (error) { setMessage(error instanceof Error ? error.message : "処理を完了できませんでした。入力・通信・保存状態を確認してください。"); }
    finally { acting.current = false; setBusy(false); }
  }
  async function savePortfolio(): Promise<void> {
    const base = savedPortfolio?.portfolio ?? blank;
    const changes = selected === "capital" ? { investment_budget_yen: portfolio.investment_budget_yen }
      : selected === "risk" ? { maximum_drawdown_percent: portfolio.maximum_drawdown_percent }
        : selected === "conditions" ? { investment_budget_yen: portfolio.investment_budget_yen, maximum_drawdown_percent: portfolio.maximum_drawdown_percent }
        : { accounts: portfolio.accounts, holdings: portfolio.holdings, holdings_status: portfolio.holdings_status };
    const value = await apiPost<SavedPortfolio>("/api/v1/mobile/portfolio", {
      expected_revision_id: savedPortfolio?.revision_id ?? null, portfolio: { ...base, ...changes },
    });
    setSavedPortfolio(value);
    // Keep other editors' drafts, without silently submitting them in this save.
    setPortfolio(draft => selected === "conditions" ? { ...draft, investment_budget_yen: value.portfolio.investment_budget_yen, maximum_drawdown_percent: value.portfolio.maximum_drawdown_percent }
      : selected === "capital" ? { ...draft, investment_budget_yen: value.portfolio.investment_budget_yen }
      : selected === "risk" ? { ...draft, maximum_drawdown_percent: value.portfolio.maximum_drawdown_percent }
        : { ...draft, accounts: value.portfolio.accounts, holdings: value.portfolio.holdings, holdings_status: value.portfolio.holdings_status });
  }
  function currentSaved(): void {
    void apiGet<SavedPortfolio | null>("/api/v1/mobile/portfolio").then(value => {
      if (!value) return;
      setSavedPortfolio(value);
      setPortfolio(draft => ({ ...draft, accounts: value.portfolio.accounts,
        holdings: value.portfolio.holdings, holdings_status: value.portfolio.holdings_status }));
    }).catch(() => setPortfolioError("保存済みです。設定一覧を読み直してください。"));
  }
  const accountDirty = JSON.stringify([portfolio.accounts, portfolio.holdings, portfolio.holdings_status]) !== JSON.stringify([
    savedPortfolio?.portfolio.accounts ?? blank.accounts, savedPortfolio?.portfolio.holdings ?? blank.holdings,
    savedPortfolio?.portfolio.holdings_status ?? blank.holdings_status,
  ]);
  const recorded = savedPortfolio?.portfolio;
  const accountComplete = recorded && recorded.accounts.length > 0 && recorded.holdings_status !== "unrecorded"
    && recorded.accounts.every(account => account.name.trim() && account.account_type !== "unknown_manual" && account.withholding_mode !== "unknown" && account.available_cash_yen !== null)
    && recorded.holdings.every(holding => holding.average_acquisition_price_yen !== null);
  const waitingLabel = portfolioError ? "再確認が必要" : "確認中";
  const overview = (portfolioLoaded ? savedPortfolio : previewPortfolio)?.portfolio;
  const accountStatus = !portfolioLoaded ? waitingLabel : accountDirty ? "未保存" : !recorded ? "未入力" : accountComplete ? "入力済み" : "要確認";
  const budget = overview?.investment_budget_yen;
  const budgetValue = budget && Number.isFinite(Number(budget)) ? `¥${Math.round(Number(budget)).toLocaleString("ja-JP")}` : "未設定";
  const drawdown = overview?.maximum_drawdown_percent;
  return <div className={`device-settings settings-screen${selected ? " settings-screen--editing" : " settings-screen--overview"}${selected === "accounts" ? " account-settings-screen" : ""}`}>
    <header className="settings-page-header app-brand">
      <div className="page-header__line">{selected && <button type="button" className="settings-back" aria-label={`← ${accountStep ? "証券口座へ" : "設定一覧へ"}`} onClick={back}>‹</button>}<span className="brand-mark" aria-hidden="true">株AI</span><h1 ref={heading} tabIndex={-1}>{accountStep ? accountStepTitles[accountStep] : selected ? panelTitles[selected] : "設定"}</h1></div>
    </header>
    {loadError && <p role="alert">{loadError}</p>}
    {!portfolioLoaded && previewPortfolio && <p className="explain">前回保存した設定を表示しています。編集は最新確認後にできます。</p>}
    {portfolioError && <><p role="alert">{portfolioError}</p><button className="button" onClick={() => { setPortfolioError(""); setReadAttempt(value => value + 1); }}>口座・保有を読み直す</button></>}
    {busy && <SaveProgress />}
    <div className="settings-overview" hidden={selected !== null}>
      <section className="settings-menu-section" aria-labelledby="settings-connection"><h2 id="settings-connection">接続</h2><div className="settings-menu-list">
        <SettingsRow icon="database" title="J-Quants API" value={configured === null ? "確認中" : configured ? "設定済み" : "未設定"} badge={configured === true} onClick={() => open("market")} />
      </div></section>
      <section className="settings-menu-section" aria-labelledby="settings-accounts"><h2 id="settings-accounts">口座・資金</h2><div className="settings-menu-list">
        <SettingsRow icon="bank" title="証券口座" value={!portfolioLoaded && !overview ? waitingLabel : overview?.accounts.length ? "登録済み" : "未登録"} badge={!!overview?.accounts.length} onClick={() => open("accounts")} />
        <SettingsRow icon="database" title="運用資金" value={portfolioLoaded || overview ? budgetValue : waitingLabel} onClick={() => open("capital")} />
      </div></section>
      <section className="settings-menu-section" aria-labelledby="settings-conditions"><h2 id="settings-conditions">運用条件</h2><div className="settings-menu-list">
        <SettingsRow icon="calendar" title="予測期間" value="5日・20日" onClick={() => open("model")} />
        <SettingsRow icon="shield" title="許容下落率" value={!portfolioLoaded && !overview ? waitingLabel : drawdown === null || drawdown === undefined ? "未設定" : `${drawdown}%`} onClick={() => open("risk")} />
      </div></section>
      <section className="settings-menu-section" aria-labelledby="settings-automation"><h2 id="settings-automation">自動更新</h2><div className="settings-menu-list">
        <SettingsRow icon="refresh" title="営業日に自動更新" checked={daily.status?.enabled ?? false} disabled={daily.busy || !daily.status || (!daily.status.enabled && !configured)} onClick={() => void daily.change(!daily.status?.enabled)} />
        <SettingsRow icon="bell" title="完了通知" value={daily.status ? daily.status.notificationsEnabled ? "許可済み" : "オフ" : "確認中"} onClick={() => open("daily")} />
      </div>{daily.busy && <p role="status">変更中…</p>}{!configured && daily.status && !daily.status.enabled && <p>先にAPIキーを設定してください。</p>}{daily.message && <p className="settings-menu-message" role="alert">{daily.message}</p>}</section>
      <section className="settings-menu-section" aria-labelledby="settings-storage"><h2 id="settings-storage">データ</h2><div className="settings-menu-list">
        <SettingsRow icon="cloud" title="バックアップ・復元" onClick={() => open("backup")} />
        <SettingsRow icon="chat" title="ChatGPT" onClick={() => open("chatgpt")} />
        <SettingsRow icon="info" title="アプリ情報・詳細" onClick={() => open("about")} />
      </div></section>
    </div>
    <SettingsPanel visible={selected === "capital" || selected === "risk"}>
    <section className="section account-editor">
      <fieldset className="account-form" disabled={busy || !portfolioLoaded}>

      <div hidden={selected !== "capital"}>
      <label>投資上限（円・未定は空欄）<input inputMode="decimal" value={portfolio.investment_budget_yen ?? ""} onChange={event => setPortfolio({ ...portfolio, investment_budget_yen: event.target.value || null })} /></label>
      </div>
      <div hidden={selected !== "risk"}>
      <label>許容する最大下落率（%・未定は空欄）<input type="number" min="0.01" max="100" step="any" value={portfolio.maximum_drawdown_percent ?? ""} onChange={event => setPortfolio({ ...portfolio, maximum_drawdown_percent: event.target.value ? Number(event.target.value) : null })} /></label>
      <p className="setting-footnote">本人の希望条件です。この下落率以内に収まることを保証するものではありません。</p>
      </div>
      <div className="button-stack">
      <button className="button button--primary" disabled={busy || !portfolioLoaded} onClick={() => void action(savePortfolio, `${selected ? panelTitles[selected] : "口座・保有"}を端末に保存しました。`)}>{selected === "capital" ? "運用資金を保存" : selected === "risk" ? "許容下落率を保存" : "口座・保有を保存"}</button>
      </div>
      <section className="settings-disclosure"><h3 className="plain-section-title">入力を保存済みの値へ戻す</h3>
      <p className="setting-footnote">ほかの設定で編集中の内容も、すべて最後に保存した値へ戻します。</p>
      <button className="button button--secondary" disabled={busy} onClick={() => void action(async () => {
        const value = await apiGet<SavedPortfolio | null>("/api/v1/mobile/portfolio");
        setSavedPortfolio(value); setPortfolio(value?.portfolio ?? blank); setPortfolioLoaded(true);
      }, "保存済みの口座・保有を読み直しました。")}>すべての保存済み入力を読み直す</button>
      </section>
      </fieldset>
    </section>
    {messageGroup === "account" && message && <p role="status">{message}</p>}
    </SettingsPanel>
    <SettingsPanel visible={selected === "accounts" && accountStep === "portfolio"}>
      <section className="section"><CurrentAccountPanel mode="cash" onSaved={currentSaved} fallback={<fieldset className="account-form" disabled={busy || !portfolioLoaded}>
        <p>SBI証券 · 初回残高の入力</p>
        {portfolio.accounts.map(account => <label key={account.id}>現金入力（円）<input inputMode="decimal" value={account.available_cash_yen ?? ""} onChange={event => setPortfolio({ ...portfolio, accounts: portfolio.accounts.map(item => item.id === account.id ? { ...item, available_cash_yen: event.target.value || null } : item) })} /></label>)}
        {!portfolio.accounts.length && <p>ホームの「実保有」から保有状況を登録してください。</p>}
        <button className="button button--primary" onClick={() => void action(savePortfolio, "初回残高の入力を保存しました。")}>初回残高の入力を保存</button>
      </fieldset>} /></section>
    </SettingsPanel>
    <SettingsPanel visible={selected === "accounts" && accountStep === "nisa"}>
      <section className="section"><CurrentAccountPanel mode="nisa" onSaved={currentSaved} /></section>
    </SettingsPanel>
    <SettingsPanel visible={selected === "accounts"}>
      <MobilePersonalPanel profile={savedPortfolio} disabled={busy || !portfolioLoaded || accountDirty}
        step={accountStep ?? "overview"} onStep={openAccount} portfolioStatus={accountStatus} />
    </SettingsPanel>
    <SettingsPanel visible={selected === "market" || selected === "repair"}>
    <div hidden={selected === "repair"}>
    <section className="section">
      <h2>J-Quants APIキー</h2>
      <p>{configured === null ? "確認中" : configured ? "設定済み" : "未設定"}</p>
      <label>J-Quants APIキー<input type="password" value={key} autoComplete="off" onChange={event => setKey(event.target.value)} /></label>
      <div className="button-stack">
        <button className="button" disabled={busy || !key} onClick={() => void action(async () => {
          await StockAI.saveApiKey({ apiKey: key }); setKey(""); setConfigured(true);
        }, "APIキーを保存しました。", "data")}>APIキーを保存</button>
        <button className="button button--secondary" disabled={busy || !configured} onClick={() => void action(async () => { await StockAI.clearApiKey(); setConfigured(false); }, "APIキーを削除しました。", "data")}>APIキーを削除</button>
      </div>
      {messageGroup === "data" && message && <p role="status">{message}</p>}
    </section>
    </div><MobileMarketPanel configured={configured === true} disabled={busy} onBusy={setBusy} onBackground={() => open("daily")} />
    </SettingsPanel>
    <SettingsPanel visible={selected === "model"}>
    <MobileModelPanel disabled={busy} inputsSaved={portfolioLoaded && savedPortfolio !== null && JSON.stringify(portfolio) === JSON.stringify(savedPortfolio.portfolio)} inputStatus={!portfolioLoaded ? "口座情報を読み込み中です。読込に失敗した場合は、この画面の「口座・保有を読み直す」を押してください。" : savedPortfolio === null ? "口座・保有が未登録です。証券口座と実保有を登録してください。" : "口座・保有の編集が未保存です。保存してから計算してください。"} onBusy={setBusy} />
    </SettingsPanel>
    <SettingsPanel visible={selected === "daily"}>
    <div className="subscreen sub-settings"><div className="ss-compact"><SettingGroup number="01" title="更新状況"><DailyControls status={daily.status} busy={daily.busy} message={daily.message} onChange={start => void daily.change(start)} explanations={false} /></SettingGroup>
    <SettingGroup number="02" title="自動更新・通知"><p className="small muted">通知のオン・オフはAndroidの設定で変更できます。</p>
      <button className="button button--secondary" disabled={daily.busy || !daily.status} onClick={() => void daily.requestNotifications()}>通知の許可を確認</button>
    </SettingGroup>
    <SettingGroup number="03" title="データ接続"><p className="small muted">APIキー：{configured === null ? "確認中" : configured ? "設定済み" : "未設定"}</p><Field label="J-Quants APIキー"><input className="input" type="password" value={key} autoComplete="off" onChange={event=>setKey(event.target.value)} /></Field><div className="subactions"><button className="button secondary" disabled={busy || !key} onClick={()=>void action(async()=>{await StockAI.saveApiKey({apiKey:key});setKey("");setConfigured(true);},"APIキーを保存しました。","data")}>キーを保存</button><button className="button secondary" disabled={busy || !configured} onClick={()=>void action(async()=>{await StockAI.clearApiKey();setConfigured(false);},"APIキーを削除しました。","data")}>キーを削除</button></div>{messageGroup === "data" && message && <p role="status">{message}</p>}<button className="text-link" onClick={()=>open("repair")}>市場データの修復</button></SettingGroup></div></div>
    </SettingsPanel>
    <SettingsPanel visible={selected === "chatgpt"}>
      <ChatGPTPanel />
    </SettingsPanel>
    <SettingsPanel visible={selected === "backup"}>
    <MobileBackupPanel disabled={busy} onBusy={setBusy} />
    </SettingsPanel>
    <SettingsPanel visible={selected === "about"}>
      <AppInfoPanel />
      <h3 className="plain-section-title">詳細管理</h3>
      <nav className="settings-list" aria-label="保存済み設定の詳細">
        {[["capital", "資金"], ["broker", "証券会社"], ["accounts", "口座・税金"], ["trading", "取引コスト・制約"], ["decision", "AI判断"], ["model", "モデル"], ["data", "データ・運用状態"]].map(([id, title]) =>
          <Link className="settings-row" to={`/settings/${id}`} key={id}><strong>{title}</strong><b aria-hidden="true">→</b></Link>)}
      </nav>
      <nav className="compact-links" aria-label="詳細管理">
        {([["conditions", "運用条件"], ["taxes", "口座・税・手数料"], ["model", "モデル管理"], ["repair", "市場データの修復"], ["method", "計算方式"]] as const).map(([id, title]) => <button className="button button--secondary" key={id} onClick={() => open(id)}>{title}</button>)}
        <Link className="button button--secondary" to="/settings/csv">CSV取り込み</Link>
        <Link className="button button--secondary" to="/settings/logs">処理状況・実行記録</Link>
      </nav>
    </SettingsPanel>
    <SettingsPanel visible={selected === "conditions"}>
      <PolicyDataProvider><div className="subscreen sub-settings"><fieldset className="account-form" disabled={busy || !portfolioLoaded}><div className="ss-compact">
        <SettingGroup number="01" title="資金配分"><AllocationReadout /><Field label="投資上限（株式時価・円）"><input className="input" inputMode="decimal" value={portfolio.investment_budget_yen ?? ""} onChange={e=>setPortfolio({...portfolio,investment_budget_yen:e.target.value || null})} /></Field><MinimumCashField /></SettingGroup>
        <SettingGroup number="02" title="リスク"><Field label="最大許容下落率（%）"><input className="input" type="number" min="0.01" max="100" step="any" value={portfolio.maximum_drawdown_percent ?? ""} onChange={e=>setPortfolio({...portfolio,maximum_drawdown_percent:e.target.value ? Number(e.target.value) : null})} /></Field><RiskPolicyFields /></SettingGroup>
        {selected === "conditions" && <PolicySummary />}</div>
        <div className="subactions"><button className="button" onClick={()=>void action(savePortfolio,"運用条件を保存しました。")}>設定を保存</button></div>
      </fieldset>{messageGroup === "account" && message && <p className="ss-status" role="status">{message}</p>}</div>
      <button className="text-link" onClick={()=>open("method")}>計算方式</button></PolicyDataProvider>
    </SettingsPanel>
    <SettingsPanel visible={selected === "method" || selected === "taxes"}>
      <MobilePersonalPanel profile={savedPortfolio} disabled={busy || !portfolioLoaded || accountDirty} step={selected === "method" ? "method" : "taxes"} />
    </SettingsPanel>
  </div>;
}

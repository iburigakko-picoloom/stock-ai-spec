import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { isAndroid, StockAI, type ReleaseInfo } from "./native";
import { MobileBackupPanel } from "./MobileBackupPanel";
import { MobilePersonalPanel } from "./MobilePersonalPanel";
import { ChatGPTPanel } from "./ChatGPTPanel";
import { MobileMarketPanel } from "./MobileMarketPanel";
import { MobileModelPanel } from "./MobileModelPanel";
import { DailyControls, useDailyAutomation } from "./DailyPanel";
import type { LocalPortfolio, SavedPortfolio } from "./personal";

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
    {release.notes && <details className="app-update-details"><summary>変更内容を見る</summary><p tabIndex={0}>{release.notes}</p></details>}
    {message && <p className="app-update-message" role="status">{message}</p>}
  </section>;
}

const blank: LocalPortfolio = { schema_version: "manual-portfolio-v1", holdings_status: "unrecorded", investment_budget_yen: null, maximum_drawdown_percent: null, accounts: [], holdings: [] };

const panelTitles = { accounts: "証券口座・保有", capital: "運用資金", risk: "許容下落率", market: "J-Quants・市場データ", model: "予測期間・モデル", daily: "自動更新・通知", chatgpt: "ChatGPT", backup: "バックアップ・復元", about: "アプリ情報・詳細" };
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

function SettingsRow({ title, description, value, icon, onClick, checked, disabled = false, badge = false }: {
  title: string; description: string; value?: string; icon: keyof typeof iconPaths;
  onClick: () => void; checked?: boolean; disabled?: boolean; badge?: boolean;
}): ReactNode {
  return <button type="button" className={`settings-menu-row${checked === undefined ? "" : " settings-menu-row--switch"}`} onClick={onClick} disabled={disabled}
    role={checked === undefined ? undefined : "switch"} aria-checked={checked} aria-label={checked === undefined ? undefined : title}>
    <svg className="settings-menu-icon" viewBox="0 0 24 24" aria-hidden="true"><path d={iconPaths[icon]} /></svg>
    <span className="settings-menu-copy"><strong>{title}</strong><small>{description}</small></span>
    {checked === undefined ? <>
      {value && <span className={badge ? "settings-menu-value settings-menu-badge" : "settings-menu-value"}>{value}</span>}
      <svg className="settings-menu-chevron" viewBox="0 0 16 24" aria-hidden="true"><path d="m5 5 7 7-7 7" /></svg>
    </> : <span className={`settings-switch${checked ? " settings-switch--on" : ""}`} aria-hidden="true"><span /></span>}
  </button>;
}

function SettingsPanel({ visible, children }: { visible: boolean; children: ReactNode }): ReactNode {
  return <div className="settings-edit-content" hidden={!visible}>{children}</div>;
}

export function MobileDevicePanel(): ReactNode {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const requested = params.get("edit");
  const selected = requested && Object.hasOwn(panelTitles, requested) ? requested as SettingsPanelId : null;
  const heading = useRef<HTMLHeadingElement>(null);
  const daily = useDailyAutomation();
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [key, setKey] = useState("");
  const [portfolio, setPortfolio] = useState<LocalPortfolio>(blank);
  const [savedPortfolio, setSavedPortfolio] = useState<SavedPortfolio | null>(null);
  const [portfolioLoaded, setPortfolioLoaded] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [message, setMessage] = useState("");
  const [messageGroup, setMessageGroup] = useState("account");
  const [busy, setBusy] = useState(false);
  useEffect(() => { heading.current?.focus(); window.scrollTo(0, 0); }, [selected]);
  useEffect(() => {
    if (!isAndroid()) return;
    void StockAI.keyStatus().then(value => setConfigured(value.configured)).catch(() => setLoadError(value => `${value}APIキーの保存状態を確認できません。再起動してください。`));
    void apiGet<SavedPortfolio | null>("/api/v1/mobile/portfolio").then(value => {
      if (value) setPortfolio(value.portfolio);
      setSavedPortfolio(value);
      setPortfolioLoaded(true);
    }).catch(() => setLoadError(value => `${value}保存済みの口座入力を確認できません。再起動してから編集してください。`));
  }, []);
  if (!isAndroid()) return null;
  function open(panel: SettingsPanelId): void { setParams({ edit: panel }, { state: { settingsList: true } }); }
  function back(): void {
    if (location.state?.settingsList) void navigate(-1);
    else setParams({}, { replace: true });
  }
  async function action(task: () => Promise<unknown>, success: string, group = "account"): Promise<void> {
    setBusy(true); setMessage(""); setMessageGroup(group);
    try { await task(); setMessage(success); }
    catch (error) { setMessage(error instanceof Error ? error.message : "処理を完了できませんでした。入力・通信・保存状態を確認してください。"); }
    finally { setBusy(false); }
  }
  async function savePortfolio(): Promise<void> {
    const base = savedPortfolio?.portfolio ?? blank;
    const changes = selected === "capital" ? { investment_budget_yen: portfolio.investment_budget_yen }
      : selected === "risk" ? { maximum_drawdown_percent: portfolio.maximum_drawdown_percent }
        : { accounts: portfolio.accounts, holdings: portfolio.holdings, holdings_status: portfolio.holdings_status };
    const value = await apiPost<SavedPortfolio>("/api/v1/mobile/portfolio", {
      expected_revision_id: savedPortfolio?.revision_id ?? null, portfolio: { ...base, ...changes },
    });
    setSavedPortfolio(value);
    // Keep other editors' drafts, without silently submitting them in this save.
    setPortfolio(draft => selected === "capital" ? { ...draft, investment_budget_yen: value.portfolio.investment_budget_yen }
      : selected === "risk" ? { ...draft, maximum_drawdown_percent: value.portfolio.maximum_drawdown_percent }
        : { ...draft, accounts: value.portfolio.accounts, holdings: value.portfolio.holdings, holdings_status: value.portfolio.holdings_status });
  }
  const budget = savedPortfolio?.portfolio.investment_budget_yen;
  const budgetValue = budget && Number.isFinite(Number(budget)) ? `¥${Math.round(Number(budget)).toLocaleString("ja-JP")}` : "未設定";
  const drawdown = savedPortfolio?.portfolio.maximum_drawdown_percent;
  return <div className="device-settings settings-screen">
    <header className="settings-page-header">
      {selected && <button type="button" className="settings-back" onClick={back}>← 設定一覧へ</button>}
      <h1 ref={heading} tabIndex={-1}>{selected ? panelTitles[selected] : "設定"}</h1>
      {!selected && <p>運用に必要な設定をまとめて管理。</p>}
    </header>
    {loadError && <p role="alert">{loadError}</p>}
    <div className="settings-overview" hidden={selected !== null}>
      <section className="settings-menu-section" aria-labelledby="settings-connection"><h2 id="settings-connection">接続</h2><div className="settings-menu-list">
        <SettingsRow icon="database" title="J-Quants API" description="日本株のデータを取得します" value={configured === null ? "確認中" : configured ? "設定済み" : "未設定"} badge={configured === true} onClick={() => open("market")} />
      </div></section>
      <section className="settings-menu-section" aria-labelledby="settings-accounts"><h2 id="settings-accounts">口座・資金</h2><div className="settings-menu-list">
        <SettingsRow icon="bank" title="証券口座" description="口座区分・現金・保有株の設定" value={!portfolioLoaded ? "確認中" : savedPortfolio?.portfolio.accounts.length ? "登録済み" : "未登録"} badge={!!savedPortfolio?.portfolio.accounts.length} onClick={() => open("accounts")} />
        <SettingsRow icon="database" title="運用資金" description="運用に使う投資上限" value={portfolioLoaded ? budgetValue : "確認中"} onClick={() => open("capital")} />
      </div></section>
      <section className="settings-menu-section" aria-labelledby="settings-conditions"><h2 id="settings-conditions">運用条件</h2><div className="settings-menu-list">
        <SettingsRow icon="calendar" title="予測期間" description="モデルの取込と予測の計算" value="5日・20日" onClick={() => open("model")} />
        <SettingsRow icon="shield" title="許容下落率" description="本人が設定する下落率の目安" value={!portfolioLoaded ? "確認中" : drawdown === null || drawdown === undefined ? "未設定" : `${drawdown}%`} onClick={() => open("risk")} />
      </div></section>
      <section className="settings-menu-section" aria-labelledby="settings-automation"><h2 id="settings-automation">自動更新</h2><div className="settings-menu-list">
        <SettingsRow icon="refresh" title="営業日に自動更新" description={daily.busy ? "変更を確認しています…" : !configured && daily.status && !daily.status.enabled ? "先にAPIキーを設定してください" : "毎営業日のデータ取得と予測"} checked={daily.status?.enabled ?? false} disabled={daily.busy || !daily.status || (!daily.status.enabled && !configured)} onClick={() => void daily.change(!daily.status?.enabled)} />
        <SettingsRow icon="bell" title="完了通知" description="Androidの通知許可・更新状態" value={daily.status ? daily.status.notificationsEnabled ? "許可済み" : "オフ" : "確認中"} onClick={() => open("daily")} />
      </div>{daily.message && <p className="settings-menu-message" role="alert">{daily.message}</p>}</section>
      <section className="settings-menu-section" aria-labelledby="settings-storage"><h2 id="settings-storage">データ</h2><div className="settings-menu-list">
        <SettingsRow icon="cloud" title="バックアップ・復元" description="保有・設定・履歴を保存します" onClick={() => open("backup")} />
        <SettingsRow icon="chat" title="ChatGPT" description="銘柄の相談・連携設定" onClick={() => open("chatgpt")} />
        <SettingsRow icon="info" title="アプリ情報・詳細" description="保存済みの設定値・ライセンス" onClick={() => open("about")} />
      </div></section>
    </div>
    <SettingsPanel visible={selected === "accounts" || selected === "capital" || selected === "risk"}>
    <section className="section">
      <div hidden={selected !== "capital"}>
      <label>投資上限（円・未定は空欄）<input inputMode="decimal" value={portfolio.investment_budget_yen ?? ""} onChange={event => setPortfolio({ ...portfolio, investment_budget_yen: event.target.value || null })} /></label>
      </div>
      <div hidden={selected !== "risk"}>
      <label>許容する最大下落率（%・未定は空欄）<input type="number" min="0.01" max="100" step="any" value={portfolio.maximum_drawdown_percent ?? ""} onChange={event => setPortfolio({ ...portfolio, maximum_drawdown_percent: event.target.value ? Number(event.target.value) : null })} /></label>
      <p className="setting-footnote">本人の希望条件です。この下落率以内に収まることを保証するものではありません。</p>
      </div>
      <div hidden={selected !== "accounts"}>
      <label><input type="checkbox" checked={portfolio.holdings_status === "none"} onChange={event => setPortfolio({ ...portfolio, holdings_status: event.target.checked ? "none" : "unrecorded", holdings: [] })} />現在は保有なし</label>
      {portfolio.accounts.map((account, index) => <fieldset key={account.id}><legend>口座 {index + 1}</legend>
        <label>口座の呼び名<input value={account.name} onChange={event => setPortfolio({ ...portfolio, accounts: portfolio.accounts.map(item => item.id === account.id ? { ...item, name: event.target.value } : item) })} /></label>
        <label>口座区分<select value={account.account_type} onChange={event => setPortfolio({ ...portfolio, accounts: portfolio.accounts.map(item => item.id === account.id ? { ...item, account_type: event.target.value as typeof item.account_type, withholding_mode: event.target.value === "nisa" ? "not_applicable" : "unknown" } : item) })}>
          <option value="unknown_manual">未確認</option><option value="taxable_specified">特定口座</option><option value="taxable_general">一般口座</option><option value="nisa">NISA</option>
        </select></label>
        {(account.account_type === "taxable_specified" || account.account_type === "taxable_general") && <label>源泉徴収<select value={account.withholding_mode} onChange={event => setPortfolio({ ...portfolio, accounts: portfolio.accounts.map(item => item.id === account.id ? { ...item, withholding_mode: event.target.value as typeof item.withholding_mode } : item) })}><option value="unknown">未確認</option>{account.account_type === "taxable_specified" && <option value="withholding">あり</option>}<option value="no_withholding">なし</option></select></label>}
        <label>利用可能現金（円・未定は空欄）<input inputMode="decimal" value={account.available_cash_yen ?? ""} onChange={event => setPortfolio({ ...portfolio, accounts: portfolio.accounts.map(item => item.id === account.id ? { ...item, available_cash_yen: event.target.value || null } : item) })} /></label>
        <button className="button button--secondary" onClick={() => setPortfolio({ ...portfolio, holdings_status: "recorded", holdings: [...portfolio.holdings, { account_id: account.id, symbol: "", shares: 1, average_acquisition_price_yen: null }] })}>この口座に保有株を追加</button>
        <button className="button button--secondary" onClick={() => {
          const holdings = portfolio.holdings.filter(item => item.account_id !== account.id);
          setPortfolio({ ...portfolio, accounts: portfolio.accounts.filter(item => item.id !== account.id), holdings, holdings_status: holdings.length ? "recorded" : "unrecorded" });
        }}>この口座と入力中の保有を削除</button>
      </fieldset>)}
      <button className="button button--secondary" onClick={() => setPortfolio({ ...portfolio, accounts: [...portfolio.accounts, { id: crypto.randomUUID(), name: "", account_type: "unknown_manual", withholding_mode: "unknown", available_cash_yen: null }] })}>口座を追加</button>
      {portfolio.holdings.map((holding, index) => <fieldset key={index}><legend>保有株 {index + 1} · {portfolio.accounts.find(item => item.id === holding.account_id)?.name}</legend>
        <label>銘柄コード<input value={holding.symbol} onChange={event => setPortfolio({ ...portfolio, holdings: portfolio.holdings.map((item, position) => position === index ? { ...item, symbol: event.target.value.toUpperCase() } : item) })} /></label>
        <label>株数<input type="number" min="1" value={holding.shares} onChange={event => setPortfolio({ ...portfolio, holdings: portfolio.holdings.map((item, position) => position === index ? { ...item, shares: Number(event.target.value) } : item) })} /></label>
        <label>平均取得単価（円・未定は空欄）<input inputMode="decimal" value={holding.average_acquisition_price_yen ?? ""} onChange={event => setPortfolio({ ...portfolio, holdings: portfolio.holdings.map((item, position) => position === index ? { ...item, average_acquisition_price_yen: event.target.value || null } : item) })} /></label>
        <button className="button button--secondary" onClick={() => {
          const holdings = portfolio.holdings.filter((_, position) => position !== index);
          setPortfolio({ ...portfolio, holdings, holdings_status: holdings.length ? "recorded" : "unrecorded" });
        }}>この保有入力を削除</button>
      </fieldset>)}
      </div>
      <div className="button-stack">
      <button className="button" disabled={busy || !portfolioLoaded} onClick={() => void action(savePortfolio, `${selected ? panelTitles[selected] : "口座・保有"}を端末に保存しました。`)}>{selected === "capital" ? "運用資金を保存" : selected === "risk" ? "許容下落率を保存" : "口座・保有を保存"}</button>
      </div>
      <details className="settings-disclosure"><summary>入力を保存済みの値へ戻す</summary>
      <p className="setting-footnote">ほかの設定で編集中の内容も、すべて最後に保存した値へ戻します。</p>
      <button className="button button--secondary" disabled={busy} onClick={() => void action(async () => {
        const value = await apiGet<SavedPortfolio | null>("/api/v1/mobile/portfolio");
        setSavedPortfolio(value); setPortfolio(value?.portfolio ?? blank); setPortfolioLoaded(true);
      }, "保存済みの口座・保有を読み直しました。")}>すべての保存済み入力を読み直す</button>
      </details>
    </section>
    {messageGroup === "account" && message && <p role="status">{message}</p>}
    <details className="settings-disclosure" hidden={selected !== "accounts"}><summary>税金・費用・初回台帳</summary>
      <MobilePersonalPanel profile={savedPortfolio} disabled={busy || !portfolioLoaded || JSON.stringify(portfolio) !== JSON.stringify(savedPortfolio?.portfolio)} />
    </details>
    </SettingsPanel>
    <SettingsPanel visible={selected === "market"}>
    <section className="section">
      <h2>J-Quants APIキー</h2>
      <p>{configured === null ? "確認中" : configured ? "設定済み（値は表示しません）" : "未設定"}</p>
      <label>J-Quants APIキー<input type="password" value={key} autoComplete="off" onChange={event => setKey(event.target.value)} /></label>
      <div className="button-stack">
        <button className="button" disabled={busy || !key} onClick={() => void action(async () => {
          await StockAI.saveApiKey({ apiKey: key }); setKey(""); setConfigured(true);
        }, "APIキーを端末に暗号化保存しました。", "data")}>APIキーを保存</button>
        <button className="button button--secondary" disabled={busy || !configured} onClick={() => void action(async () => { await StockAI.clearApiKey(); setConfigured(false); }, "APIキーを削除しました。", "data")}>APIキーを削除</button>
      </div>
      {messageGroup === "data" && message && <p role="status">{message}</p>}
    </section>
    <MobileMarketPanel configured={configured === true} disabled={busy} onBusy={setBusy} />
    </SettingsPanel>
    <SettingsPanel visible={selected === "model"}>
    <MobileModelPanel disabled={busy} inputsSaved={portfolioLoaded && savedPortfolio !== null && JSON.stringify(portfolio) === JSON.stringify(savedPortfolio.portfolio)} onBusy={setBusy} />
    </SettingsPanel>
    <SettingsPanel visible={selected === "daily"}>
    <DailyControls status={daily.status} busy={daily.busy} message={daily.message} onChange={start => void daily.change(start)} />
    <section className="section"><h2>完了通知</h2><p>通知はAndroidの許可状態を表示します。オフへの変更や許可後の再設定は、Androidの「アプリ情報 → 通知」で行ってください。</p>
      <button className="button button--secondary" disabled={daily.busy || !daily.status} onClick={() => void daily.requestNotifications()}>通知の許可を確認</button>
    </section>
    </SettingsPanel>
    <SettingsPanel visible={selected === "chatgpt"}>
      <div className="button-stack"><Link className="button button--secondary" to="/today/chatgpt">手動でChatGPTに相談</Link></div>
      <details className="settings-disclosure"><summary>アカウント連携の設定</summary><ChatGPTPanel /></details>
    </SettingsPanel>
    <SettingsPanel visible={selected === "backup"}>
    <MobileBackupPanel disabled={busy} onBusy={setBusy} />
    </SettingsPanel>
    <SettingsPanel visible={selected === "about"}>
      <p>保有・設定はこの端末に保存します。モデルの最終採用と推論の一致確認が完了するまで研究用表示を続けます。</p>
      <nav className="settings-list" aria-label="保存済み設定の詳細">
        {[["capital", "資金"], ["broker", "証券会社"], ["accounts", "口座・税金"], ["trading", "取引コスト・制約"], ["decision", "AI判断"], ["model", "モデル"], ["data", "データ・運用状態"]].map(([id, title]) =>
          <Link className="settings-row" to={`/settings/${id}`} key={id}><strong>{title}</strong><b aria-hidden="true">→</b></Link>)}
      </nav>
      <p><a href="/python/licenses.html" target="_blank" rel="noreferrer">オープンソースの表示・ソース取得先</a></p>
    </SettingsPanel>
    {busy && <p role="status">端末内で処理しています…</p>}
  </div>;
}

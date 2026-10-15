import { useEffect, useState, type ReactNode } from "react";
import { apiGet, apiPost } from "../api";
import { isAndroid, StockAI, type ReleaseInfo } from "./native";
import { restoreMobileState } from "./runtime";
import { MobilePersonalPanel } from "./MobilePersonalPanel";
import type { LocalPortfolio, SavedPortfolio } from "./personal";

export function MobileUpdateNotice(): ReactNode {
  const [release, setRelease] = useState<ReleaseInfo | null>(null);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (isAndroid()) void StockAI.checkUpdate().then(setRelease).catch(() => {
      // Startup/network failures never stop local use or discard existing state.
    });
  }, []);
  if (!release?.available) return null;
  return <section className="section" aria-label="アプリの更新">
    <h2>StockAI {release.versionName} に更新できます</h2>
    <p style={{ whiteSpace: "pre-wrap" }}>{release.notes}</p>
    <button className="button" onClick={() => {
      setMessage("APKを確認しています…");
      void StockAI.installUpdate({ versionCode: release.versionCode }).then(result =>
        setMessage(result.needsPermission ? "Androidの設定で更新を許可してから、もう一度更新ボタンを押してください。" : "Androidの確認画面でインストールしてください。"),
      () => setMessage("更新を取得できませんでした。現在のアプリを引き続き使用できます。"));
    }}>確認して更新</button><p role="status">{message}</p>
  </section>;
}

const blank: LocalPortfolio = { schema_version: "manual-portfolio-v1", holdings_status: "unrecorded", investment_budget_yen: null, maximum_drawdown_percent: null, accounts: [], holdings: [] };

export function MobileDevicePanel(): ReactNode {
  const [configured, setConfigured] = useState(false);
  const [key, setKey] = useState("");
  const [password, setPassword] = useState("");
  const [portfolio, setPortfolio] = useState<LocalPortfolio>(blank);
  const [savedPortfolio, setSavedPortfolio] = useState<SavedPortfolio | null>(null);
  const [portfolioLoaded, setPortfolioLoaded] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [restorePayload, setRestorePayload] = useState<string | null>(null);
  const [confirmRestore, setConfirmRestore] = useState(false);
  const [marketDate, setMarketDate] = useState("");
  const [marketStatus, setMarketStatus] = useState<{ latest_data_date: string | null; completed_dates: string[] } | null>(null);
  const [modelStatus, setModelStatus] = useState<{ approved_count: number; imported_count: number } | null>(null);
  useEffect(() => {
    if (!isAndroid()) return;
    void StockAI.keyStatus().then(value => setConfigured(value.configured)).catch(() => setMessage("APIキーの保存状態を確認できません。再起動してください。"));
    void apiGet<SavedPortfolio | null>("/api/v1/mobile/portfolio").then(value => {
      if (value) setPortfolio(value.portfolio);
      setSavedPortfolio(value);
      setPortfolioLoaded(true);
    }).catch(() => setMessage("保存済みの口座入力を確認できません。再起動してから編集してください。"));
    void apiGet<{ latest_data_date: string | null; completed_dates: string[] }>("/api/v1/mobile/market").then(setMarketStatus).catch(() => setMessage("保存済みの市場データを確認できません。再起動してください。"));
    void apiGet<{ approved_count: number; imported_count: number }>("/api/v1/mobile/models").then(setModelStatus).catch(() => setMessage("モデルの保存状態を確認できません。再起動してください。"));
  }, []);
  if (!isAndroid()) return null;
  async function action(task: () => Promise<unknown>, success: string): Promise<void> {
    setBusy(true); setMessage("");
    try { await task(); setMessage(success); }
    catch (error) { setMessage(error instanceof Error ? error.message : "処理を完了できませんでした。入力・通信・保存状態を確認してください。"); }
    finally { setBusy(false); }
  }
  return <>
    <section className="section">
      <h2>端末内の研究環境</h2>
      <p>保有・設定はこの端末に保存します。モデルの最終採用と推論の一致確認が完了するまで研究用表示を続けます。</p>
      <p><a href="/python/licenses.html" target="_blank" rel="noreferrer">オープンソースの表示・ソース取得先</a></p>
      <label>J-Quants APIキー（{configured ? "設定済み" : "未設定"}）<input type="password" value={key} autoComplete="off" onChange={event => setKey(event.target.value)} /></label>
      <button className="button" disabled={busy || !key} onClick={() => void action(async () => {
        await StockAI.saveApiKey({ apiKey: key }); setKey(""); setConfigured(true);
      }, "APIキーを端末に暗号化保存しました。")}>APIキーを保存</button>
      <button className="button button--secondary" disabled={busy || !configured} onClick={() => void action(async () => { await StockAI.clearApiKey(); setConfigured(false); }, "APIキーを削除しました。")}>APIキーを削除</button>
    </section>
    <section className="section">
      <h2>この端末の口座・保有</h2>
      <label><input type="checkbox" checked={portfolio.holdings_status === "none"} onChange={event => setPortfolio({ ...portfolio, holdings_status: event.target.checked ? "none" : "unrecorded", holdings: [] })} />現在は保有なし</label>
      <label>投資上限（円・未定は空欄）<input inputMode="decimal" value={portfolio.investment_budget_yen ?? ""} onChange={event => setPortfolio({ ...portfolio, investment_budget_yen: event.target.value || null })} /></label>
      <label>許容する最大下落率（%・未定は空欄）<input type="number" min="0.01" max="100" step="any" value={portfolio.maximum_drawdown_percent ?? ""} onChange={event => setPortfolio({ ...portfolio, maximum_drawdown_percent: event.target.value ? Number(event.target.value) : null })} /></label>
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
      <button className="button" disabled={busy || !portfolioLoaded} onClick={() => void action(async () => {
        const value = await apiPost<SavedPortfolio>("/api/v1/mobile/portfolio", { expected_revision_id: savedPortfolio?.revision_id ?? null, portfolio });
        setSavedPortfolio(value); setPortfolio(value.portfolio);
      }, "口座・保有を端末に保存しました。補足設定と初回台帳の確認へ進めます。")}>口座・保有を保存</button>
      <button className="button button--secondary" disabled={busy} onClick={() => void action(async () => {
        const value = await apiGet<SavedPortfolio | null>("/api/v1/mobile/portfolio");
        setSavedPortfolio(value); setPortfolio(value?.portfolio ?? blank); setPortfolioLoaded(true);
      }, "保存済みの口座・保有を読み直しました。")}>保存済みの口座・保有を読み直す</button>
    </section>
    <MobilePersonalPanel profile={savedPortfolio} disabled={busy || !portfolioLoaded || JSON.stringify(portfolio) !== JSON.stringify(savedPortfolio?.portfolio)} />
    <section className="section"><h2>市場データの差分取得</h2>
      <p>保存済みの最終日：{marketStatus?.latest_data_date ?? "未取得"}。予測の更新日時とは別に表示しています。</p>
      <p>1日分ずつ取得し、保存済みの日付は再取得しません。初回は特徴量の計算に必要な履歴を用意する必要があります。</p>
      <label>取得する日付<input type="date" value={marketDate} onChange={event => setMarketDate(event.target.value)} /></label>
      <button className="button" disabled={busy || !configured || !marketDate || marketStatus?.completed_dates.includes(marketDate)} onClick={() => void action(async () => {
        const result = await StockAI.fetchMarket({ date: marketDate });
        if (result.status !== 200) {
          throw new Error(result.status === 403 ? "API 403：契約プラン・APIキー・対象期間を確認してください。" : `データ取得に失敗しました（HTTP ${result.status}）。`);
        }
        const saved = await apiPost<{ latest_data_date: string | null; completed_dates: string[] }>("/api/v1/mobile/market/ingest", result);
        setMarketStatus(saved);
      }, "データを検証して端末に保存しました。モデル未採用のため最新の推奨は表示しません。")}>この日付の差分を取得</button>
      <button className="button button--secondary" disabled={busy || !marketStatus?.latest_data_date} onClick={() => void action(() => apiPost("/api/v1/mobile/features/latest", {}), "端末内で41・51特徴量を計算しました。モデル採用・推論一致確認は別途必要です。")}>保存データで特徴量を確認</button>
    </section>
    <section className="section"><h2>端末で使うモデル</h2>
      <p>採用・取込条件を確認済み：{modelStatus?.approved_count ?? 0}件／端末へ取込済み：{modelStatus?.imported_count ?? 0}件</p>
      <p>最終採用、モデルの配布条件、PCと実機の一致確認が完了したモデルだけを取り込みます。</p>
      <button className="button" disabled={busy || !modelStatus?.approved_count} onClick={() => void action(async () => {
        const value = await StockAI.importModel(); await apiPost("/api/v1/mobile/models/import", value);
        setModelStatus(await apiGet("/api/v1/mobile/models"));
      }, "採用情報とハッシュが一致するモデルを端末に保存しました。")}>確認済みモデルを取り込む</button>
      <button className="button button--secondary" disabled={busy || !modelStatus?.imported_count} onClick={() => void action(() => apiPost("/api/v1/mobile/models/infer", {}), "端末内で研究用のモデル出力を計算しました。")}>端末内で推論を確認</button>
    </section>
    <section className="section"><h2>データのバックアップ</h2>
      <p>保有・設定・履歴をパスワード付きで保存します。APIキーは含めません。</p>
      <label>バックアップのパスワード（12文字以上）<input type="password" autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} /></label>
      <button className="button" disabled={busy || password.length < 12} onClick={() => void action(() => StockAI.exportBackup({ password }), "バックアップを保存しました。パスワードを別の安全な場所に保管してください。")}>バックアップを書き出す</button>
      <button className="button button--secondary" disabled={busy || password.length < 12} onClick={() => void action(async () => {
        const value = await StockAI.importBackup({ password }); setRestorePayload(value.payload); setConfirmRestore(false);
      }, "復元ファイルを読み込みました。内容を復元すると現在の保有・設定・履歴を置き換えます。")}>復元ファイルを選ぶ</button>
      {restorePayload && <div><label><input type="checkbox" checked={confirmRestore} onChange={event => setConfirmRestore(event.target.checked)} />現在の保有・設定・履歴を、このバックアップへ置き換えることを確認しました。</label>
        <button className="button" disabled={busy || !confirmRestore} onClick={() => void action(() => restoreMobileState(restorePayload), "復元しました。")}>このバックアップから復元</button></div>}
    </section>
    <p role="status">{busy ? "端末内で処理しています…" : message}</p>
  </>;
}

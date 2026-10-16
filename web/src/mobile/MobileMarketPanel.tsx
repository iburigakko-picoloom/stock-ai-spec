import { useEffect, useRef, useState, type ReactNode } from "react";
import { apiGet, apiPost } from "../api";
import { acquireMembership, acquireRange, defaultPlan, type AcquisitionMode, type MarketPlan, type MarketStatus, type MembershipStatus, type UniversePreview } from "./market";

export function MobileMarketPanel({ configured, disabled, onBusy }: {
  configured: boolean; disabled: boolean; onBusy: (value: boolean) => void;
}): ReactNode {
  const [status, setStatus] = useState<MarketStatus | null>(null);
  const [plan, setPlan] = useState<MarketPlan>(defaultPlan);
  const [loaded, setLoaded] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState("");
  const [refreshDay, setRefreshDay] = useState("");
  const [selection, setSelection] = useState<UniversePreview | null>(null);
  const [membership, setMembership] = useState<MembershipStatus | null>(null);
  const stop = useRef(false);
  useEffect(() => {
    void Promise.all([apiGet<MarketStatus>("/api/v1/mobile/market"), apiGet<MarketPlan | null>("/api/v1/mobile/market/plan"), apiGet<MembershipStatus>("/api/v1/mobile/market/membership")])
      .then(([saved, range, member]) => { setStatus(saved); if (range) setPlan(range); setMembership(member); setLoaded(true); })
      .catch(() => setMessage("取得範囲と保存データを確認できません。アプリを再起動してください。"));
    return () => { stop.current = true; };
  }, []);
  async function run(range: MarketPlan, mode: AcquisitionMode = "pending"): Promise<void> {
    stop.current = false; setRunning(true); onBusy(true); setSelection(null);
    try {
      const result = await acquireRange(range, (day, done, total, saved) => {
        setMessage(`${day}を${saved ? "保存しました" : "取得しています"}（${done} / ${total}日）。`);
        if (saved) setStatus(saved);
      }, () => stop.current, mode);
      setStatus(result.status);
      setMessage(result.stopped ? "取得を停止しました。取得済みの日付・ページから再開できます。" : "指定範囲を保存しました。予測と推奨株数の更新状況は別に確認します。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "取得を完了できません。続きから再開できます。");
    } finally { setRunning(false); onBusy(false); }
  }
  async function inspect(task: () => Promise<void>): Promise<void> {
    onBusy(true);
    try { await task(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "データを確認できません。"); }
    finally { onBusy(false); }
  }
  return <section className="section" aria-label="市場データ">
    <h2>市場データ</h2>
    <p>保存済みの最終日：{status?.latest_data_date ?? "未取得"}</p>
    <p>{plan.first_day}〜{plan.last_day}。保存済みの日付を除いて取得し、通信中断後は取得済みページから再開します。APIの速度制限があるため、初回は数時間かかる場合があります。</p>
    <p>現在は画面を開いて取得します。画面を閉じた後の継続と毎営業日の自動更新は準備中です。</p>
    <div className="button-stack">
      <button className="button button--primary" disabled={disabled || !configured || !loaded || running} onClick={() => void run(plan)}>履歴の取得を開始・再開</button>
      {running && <button className="button button--secondary" onClick={() => { stop.current = true; setMessage("今の日付の保存が終わったら停止します。"); }}>この日付の取得後に停止</button>}
    </div>
    <p role="status" aria-live="polite">{message}</p>
    <details className="market-options"><summary>取得範囲・訂正データ・計算の確認</summary>
      <p>当日の銘柄一覧・直近受領：{membership?.latest_received_at ?? "未取得"}。11:30までに受領した利用対象：{membership?.eligible_received_at ?? "未確認"}</p>
      <label>開始日<input type="date" disabled={disabled || running} value={plan.first_day} onChange={e => setPlan({ ...plan, first_day: e.target.value })} /></label>
      <label>終了日<input type="date" disabled={disabled || running} value={plan.last_day} onChange={e => setPlan({ ...plan, last_day: e.target.value })} /></label>
      <p>最大2年分。初期値は特徴量の履歴用に420日前からです。契約外の期間や不足データを自動的に補いません。</p>
      <label>訂正を確認する日付<input type="date" disabled={disabled || running} value={refreshDay} onChange={e => setRefreshDay(e.target.value)} /></label>
      <div className="button-stack">
        <button className="button button--secondary" disabled={disabled || running || !loaded || !configured} onClick={() => void inspect(async () => {
          const saved = await acquireMembership(); setMembership(saved); setSelection(null);
          setMessage(saved.available_at_cutoff ? saved.is_business_day ? "当日の銘柄一覧を確認しました。" : "カレンダーで当日の休場を確認しました。" : "11:30後の受領です。今日の数値予測へは使えません。");
        })}>当日の銘柄一覧を取得・再開</button>
        <button className="button button--secondary" disabled={disabled || running || !loaded || !configured} onClick={() => void inspect(async () => {
          const saved = await acquireMembership(true); setMembership(saved); setSelection(null);
          setMessage("銘柄一覧を取り直しました。11:30を過ぎて受領した情報は今日の数値予測へ使いません。");
        })}>当日の銘柄一覧を最初から再取得</button>
        <button className="button button--secondary" disabled={disabled || running || !loaded || !configured || !refreshDay} onClick={() => void run({ first_day: refreshDay, last_day: refreshDay }, "corrections")}>この日付の訂正を取得・再開</button>
        <button className="button button--secondary" disabled={disabled || running || !loaded || !configured || !refreshDay} onClick={() => void run({ first_day: refreshDay, last_day: refreshDay }, "restart")}>この日付を最初から再取得</button>
        <button className="button button--secondary" disabled={disabled || running || !status?.latest_data_date} onClick={() => void inspect(async () => {
          setSelection(await apiGet<UniversePreview>("/api/v1/mobile/market/current-universe")); setMessage("対象抽出の受領記録を確認しました。");
        })}>候補と全保有の対象を確認</button>
        <button className="button button--secondary" disabled={disabled || running || !status?.latest_data_date} onClick={() => void inspect(async () => {
          await apiPost("/api/v1/mobile/features/latest", {}); setMessage("保存データで特徴量を計算しました。モデル採用と推論の一致確認は別途必要です。");
        })}>保存データで特徴量を確認</button>
      </div>
      <p>検証に失敗し続ける場合は「最初から再取得」で取り直せます。</p>
      {selection && <div><p>抽出時点：{selection.as_of}／当日の銘柄一覧：{selection.membership_source_date ?? "未確認"}／終値・時価総額：{selection.latest_source_date ?? "不足"}</p>
        {selection.holdings_recorded === false && <p>保有の入力が未確認です。対象の保有銘柄を確定するには、口座・保有の入力が必要です。</p>}
        <p>条件内の上位{selection.new_candidates.length}社＋条件外の保有{selection.held_only.length}社＝評価対象{selection.decision_symbols.length}社</p>
        {selection.blocking_reasons.includes("current_membership_missing") ? <p>11:30までに受領した当日の銘柄一覧がありません。全保有を対象に残しています。</p>
          : selection.blocking_reasons.includes("non_business_day") ? <p>当日は休場日です。新しい数値予測は作成しません。</p>
          : selection.blocking_reasons.length > 0 && <p>必要な20営業日のカレンダー・株価・時価総額がそろっていません。全保有を対象に残しています。</p>}
        <p>全保有のうち条件外：{selection.held_only.join("、") || "なし"}。市場・業種の特徴量は全体の母集団から計算します。</p>
      </div>}
    </details>
  </section>;
}

import { useEffect, useRef, useState, type ReactNode } from "react";
import { isAndroid, StockAI, type DailyStatus } from "./native";

const labels: Record<string, string> = {
  idle: "未開始", queued: "開始待ち", history: "履歴を取得しています", membership: "当日の銘柄一覧を取得しています",
  waiting_cutoff: "11:30の締切待ち", calculating: "予測を計算しています", closed: "今日は休場日です",
  forecast_saved: "原予測を保存済み・株数判定待ち", deciding: "株数を計算しています",
  consultation_ready: "研究用の原予測を保存済み・ChatGPTへの相談準備完了",
  history_wait: "Androidの取得待ち・アプリで保存状態を確認してください",
  compute_wait: "Androidの計算待ち・アプリで保存状態を確認してください",
  numerical_saved: "数値判定を保存済み・ChatGPT調査は別途確認", inputs: "モデル・本人設定の確認が必要です",
  late: "11:30までの当日情報が不足しています", credentials: "APIキー・契約を確認して再開してください",
  retry: "中断・保存済みの続きから再試行待ち", paused: "停止中・取得済みのデータを保持しています",
  research_running: "数値判定を保存済み・ChatGPT調査を進めています",
  research_complete: "数値判定・ChatGPT調査を保存しました",
  research_attention: "数値判定を保存済み・ChatGPT調査の確認が必要です",
};

// Completed stages, not a percentage of time or individual model operations.
const stages: Record<string, number> = {
  history: 0, membership: 0, calculating: 1, forecast_saved: 2, deciding: 2,
  numerical_saved: 3, research_running: 3, research_complete: 3, research_attention: 3,
};

export function useDailyAutomation() {
  const [status, setStatus] = useState<DailyStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const changing = useRef(false);
  const revision = useRef(0);
  useEffect(() => {
    if (!isAndroid()) return;
    let active = true;
    const refresh = (): void => {
      if (changing.current) return;
      const observed = revision.current;
      void StockAI.dailyStatus().then(value => { if (active && !changing.current && observed === revision.current) setStatus(value); })
        .catch(() => { if (active && !changing.current && observed === revision.current) setMessage("自動処理の状態を確認できません。アプリを再起動してください。"); });
    };
    refresh();
    const timer = window.setInterval(refresh, 15000);
    window.addEventListener("focus", refresh);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, []);
  async function change(start: boolean): Promise<void> {
    if (changing.current) return;
    changing.current = true; revision.current++;
    setBusy(true); setMessage("");
    try {
      if (start) {
        await StockAI.requestDailyNotifications();
        setStatus(await StockAI.startDaily());
      } else setStatus(await StockAI.stopDaily());
    } catch (error) { setMessage(error instanceof Error ? error.message : "処理を完了できません。保存状態を確認してください。"); }
    finally { changing.current = false; setBusy(false); }
  }
  async function requestNotifications(): Promise<void> {
    if (changing.current) return;
    changing.current = true; revision.current++; setBusy(true); setMessage("");
    try {
      await StockAI.requestDailyNotifications();
      const current = await StockAI.dailyStatus(); setStatus(current);
      setMessage(current.notificationsEnabled ? "通知が許可されています。" : "通知はオフです。Androidのアプリ設定で通知を許可してください。");
    } catch { setMessage("通知の許可状態を確認できません。Androidのアプリ設定を確認してください。"); }
    finally { changing.current = false; setBusy(false); }
  }
  return { status, busy, message, change, requestNotifications };
}

export function DailyPanel(): ReactNode {
  const daily = useDailyAutomation();
  if (!isAndroid()) return null;
  return <DailyControls status={daily.status} busy={daily.busy} message={daily.message} onChange={start => void daily.change(start)} />;
}

export function DailyControls({ status, busy, message, onChange }: {
  status: DailyStatus | null; busy: boolean; message: string; onChange: (start: boolean) => void;
}): ReactNode {
  const delayed = status?.state === "waiting_cutoff" && status.day && Date.now() >= Date.parse(`${status.day}T11:30:00+09:00`);
  const stage = status && status.enabled ? stages[status.state] : undefined;
  return <section className="section daily-panel" aria-label="毎日の自動処理">
    <h2>毎日の自動処理</h2>
    <p role="status">{status ? delayed ? "締切後の実行待ち・Androidの予約処理を待っています" : labels[status.state] ?? "保存状態を確認してください" : "状態を確認しています…"}</p>
    {stage !== undefined && <div className="daily-stage">
      <progress max={3} value={stage} aria-label="数値計算の完了工程" aria-valuetext={`${stage}/3工程完了。残り時間の割合ではありません。`} />
      <small>進み具合の目安</small>
    </div>}
    {status?.enabled && ["history", "membership", "calculating", "deciding"].includes(status.state) && <p className="daily-background">画面を閉じても続けます。省電力などで中断した場合は、保存済みの続きから再開します。</p>}
    {status?.day && <p>対象日：{status.day}</p>}
    <div className="button-stack">
      <button className="button button--primary" hidden={!!status?.enabled && status.state !== "credentials"} disabled={busy || !status || (status.enabled && status.state !== "credentials")} onClick={() => onChange(true)}>{status?.state === "paused" || status?.state === "credentials" ? "続きから再開" : "開始"}</button>
      <button className="button button--secondary" hidden={!status?.enabled} disabled={busy || !status?.enabled} onClick={() => onChange(false)}>自動処理を停止</button>
    </div>
    {message && <p role="alert">{message}</p>}
    {status && !status.notificationsEnabled && <p>通知はオフです。計算結果はアプリ内に保存します。</p>}
    <details><summary>取得と実行時刻について</summary>
      <p>口座・保有・初回台帳とモデル一式を確認し、APIキーを保存してから開始します。初期履歴を取得し、以後は毎営業日の差分と予測・株数の保存へ進みます。モバイル回線を使用します。</p>
      <p>Androidの省電力や通信状態で実行が遅れることがあります。11:30を過ぎた受領を締切内へ戻しません。停止・再起動後も保存済みの続きから再開します。Androidの「強制停止」後はアプリを開いてください。</p>
      <p>ChatGPT連携とモデル設定がある場合は、数値上位20銘柄と全保有を調査します。中断・上限・認証切れは未完了として保存し、調査画面で確認できます。</p>
      {status?.updatedAt && <p>状態の記録：{new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", dateStyle: "short", timeStyle: "medium" }).format(new Date(status.updatedAt))} JST</p>}
    </details>
  </section>;
}

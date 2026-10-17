import { useEffect, useState, type ReactNode } from "react";
import { isAndroid, StockAI, type DailyStatus } from "./native";

const labels: Record<string, string> = {
  idle: "未開始", queued: "開始待ち", history: "履歴を取得しています", membership: "当日の銘柄一覧を取得しています",
  waiting_cutoff: "11:30の締切待ち", calculating: "予測を計算しています", closed: "今日は休場日です",
  forecast_saved: "原予測を保存済み・株数判定待ち", deciding: "株数を計算しています",
  compute_wait: "Androidの計算待ち・アプリで保存状態を確認してください",
  numerical_saved: "数値判定を保存済み・ChatGPT調査は別途確認", inputs: "モデル・本人設定の確認が必要です",
  late: "11:30までの当日情報が不足しています", credentials: "APIキー・契約を確認して再開してください",
  retry: "中断・保存済みの続きから再試行待ち", paused: "停止中・取得済みのデータを保持しています",
  research_running: "数値判定を保存済み・ChatGPT調査を進めています",
  research_complete: "数値判定・ChatGPT調査を保存しました",
  research_attention: "数値判定を保存済み・ChatGPT調査の確認が必要です",
};

export function DailyPanel(): ReactNode {
  const [status, setStatus] = useState<DailyStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (!isAndroid()) return;
    let active = true;
    const refresh = (): void => {
      void StockAI.dailyStatus().then(value => { if (active) setStatus(value); })
        .catch(() => { if (active) setMessage("自動処理の状態を確認できません。アプリを再起動してください。"); });
    };
    refresh();
    const timer = window.setInterval(refresh, 15000);
    window.addEventListener("focus", refresh);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, []);
  if (!isAndroid()) return null;
  async function change(start: boolean): Promise<void> {
    setBusy(true); setMessage("");
    try {
      if (start) {
        await StockAI.requestDailyNotifications();
        setStatus(await StockAI.startDaily());
      } else setStatus(await StockAI.stopDaily());
    } catch (error) { setMessage(error instanceof Error ? error.message : "処理を完了できません。保存状態を確認してください。"); }
    finally { setBusy(false); }
  }
  return <DailyControls status={status} busy={busy} message={message} onChange={start => void change(start)} />;
}

export function DailyControls({ status, busy, message, onChange }: {
  status: DailyStatus | null; busy: boolean; message: string; onChange: (start: boolean) => void;
}): ReactNode {
  const delayed = status?.state === "waiting_cutoff" && status.day && Date.now() >= Date.parse(`${status.day}T11:30:00+09:00`);
  return <section className="section daily-panel" aria-label="毎日の自動処理">
    <h2>毎日の自動処理</h2>
    <p role="status">{status ? delayed ? "締切後の実行待ち・Androidの予約処理を待っています" : labels[status.state] ?? "保存状態を確認してください" : "状態を確認しています…"}</p>
    {status?.day && <p>対象日：{status.day}</p>}
    <div className="button-stack">
      <button className="button button--primary" disabled={busy || !status || (status.enabled && status.state !== "credentials")} onClick={() => onChange(true)}>{status?.state === "paused" || status?.state === "credentials" ? "続きから再開" : "開始"}</button>
      <button className="button button--secondary" disabled={busy || !status?.enabled} onClick={() => onChange(false)}>自動処理を停止</button>
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

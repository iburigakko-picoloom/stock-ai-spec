import { useEffect, useState } from "react";
import { StockAI, type BackupPreview } from "./native";
import { restoreMobileBackup } from "./runtime";

export function MobileBackupPanel({ disabled, onBusy }: { disabled: boolean; onBusy: (value: boolean) => void }) {
  const [password, setPassword] = useState("");
  const [preview, setPreview] = useState<BackupPreview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => () => {
    if (preview) void StockAI.discardBackup({ token: preview.token }).catch(() => {});
  }, [preview]);

  async function run(operation: () => Promise<void>, success: string) {
    if (busy || disabled) return;
    setBusy(true); onBusy(true); setMessage("");
    try { await operation(); setMessage(success); }
    catch { setMessage("処理の結果を確認できませんでした。保存状態とパスワード・ファイルを確認し、必要ならファイルを選び直してください。"); }
    finally { setBusy(false); onBusy(false); }
  }
  const blocked = busy || disabled;
  return <div aria-label="データのバックアップ"><section className="numbered-section"><small>01</small><h2>書き出し</h2>
    <p>保有・設定・履歴をパスワード付きで保存します。APIキーは含めません。</p>
    <label>バックアップのパスワード（12文字以上）<input type="password" autoComplete="new-password" maxLength={1024} value={password} disabled={blocked} onChange={event => setPassword(event.target.value)} /></label>
    <div className="button-stack">
      <button className="button" disabled={blocked || password.length < 12} onClick={() => void run(() => StockAI.exportBackup({ password }), "バックアップを保存しました。パスワードを別の安全な場所に保管してください。")}>バックアップを書き出す</button></div></section>
    <section className="numbered-section"><small>02</small><h2>復元ファイル</h2><div className="button-stack">
      <button className="button button--secondary" disabled={blocked || password.length < 12} onClick={() => void run(async () => {
        setPreview(null); setConfirmed(false);
        setPreview(await StockAI.importBackup({ password }));
      }, "復元ファイルを確認しました。復元すると現在の保有・設定・履歴を置き換えます。")}>復元ファイルを選ぶ</button>
    </div>
    </section><section className="numbered-section"><small>03</small><h2>復元内容の確認</h2>
    {!preview && <p className="setting-footnote">復元ファイルは未選択です。</p>}
    {preview && <div>
      <label><input type="checkbox" checked={confirmed} disabled={blocked} onChange={event => setConfirmed(event.target.checked)} />現在の保有・設定・履歴を、このバックアップへ置き換えることを確認しました。</label>
      <div className="button-stack">
        <button className="button" disabled={blocked || !confirmed} onClick={() => void run(async () => {
          if (!confirmed) return;
          try { await restoreMobileBackup(preview.token); }
          finally { setPreview(null); setConfirmed(false); }
        }, "復元しました。")}>このバックアップから復元</button>
        <button className="button button--secondary" disabled={blocked} onClick={() => {
          setPreview(null); setConfirmed(false); setMessage("復元を取り消しました。");
        }}>復元を取り消す</button>
      </div>
    </div>}
    <p role="status">{busy ? "バックアップを処理しています…" : message}</p>
  </section></div>;
}

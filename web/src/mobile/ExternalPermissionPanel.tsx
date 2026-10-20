import { useState } from "react";
import { apiPost } from "../api";

export function ExternalPermissionPanel() {
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function save(): Promise<void> {
    setBusy(true); setMessage("");
    try {
      await apiPost("/api/v1/research/permission", {
        service: "account_codex", checked_at: new Date().toISOString(),
        personal_analysis_only: confirmed, training_disabled: confirmed,
        private_input: confirmed, private_output: confirmed, data_entitlement_confirmed: confirmed,
      });
      setMessage("この連携先の条件確認を24時間有効で保存しました。");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "条件を保存できませんでした。"); }
    finally { setBusy(false); }
  }
  return <details className="research-disclosure"><summary>既存連携の外部送信条件</summary>
    <p>手動コピーの代わりにアカウント連携を使う場合の確認です。連携先ごとに設定を確認してください。</p>
    <label className="checkbox"><input type="checkbox" checked={confirmed} disabled={busy}
      onChange={event => setConfirmed(event.target.checked)} />現在のデータ契約の範囲で、本人分析だけに使用し、連携先も学習利用なし・入力と結果を非公開にしています</label>
    <p className="setting-footnote">ChatGPTの学習設定とCodexの環境共有設定は別です。公開・共有や学習利用のfeedback送信は行わないでください。</p>
    <div className="button-stack"><button className="button button--secondary" disabled={!confirmed || busy}
      onClick={() => void save()}>この連携先の条件確認を保存</button></div>
    <p role="status">{message}</p>
  </details>;
}

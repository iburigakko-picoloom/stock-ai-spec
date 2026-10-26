import { useEffect, useState } from "react";
import { ChatGPT, chatGPTFailure, type ChatGPTStatus, type ConnectionProbe, type ReasoningEffort } from "./chatgpt";
import { Link } from "react-router-dom";
import { Field, KV, SettingGroup } from "../Adopted";
import { ExternalPermissionPanel } from "./ExternalPermissionPanel";

const depths: [ReasoningEffort, string][] = [
  ["low", "低"], ["medium", "標準"], ["high", "高"], ["xhigh", "さらに高"], ["max", "最大"],
];

export function ChatGPTPanel() {
  const [status, setStatus] = useState<ChatGPTStatus | null>(null);
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState<ReasoningEffort>("medium");
  const [busy, setBusy] = useState(false);
  const [signingIn, setSigningIn] = useState(false);
  const [message, setMessage] = useState("");
  const [probe, setProbe] = useState<ConnectionProbe | null>(null);
  const [disconnectConfirmed, setDisconnectConfirmed] = useState(false);
  useEffect(() => {
    let active = true;
    void ChatGPT.getStatus().then(value => {
      if (active) { setStatus(value); setModel(value.selection.model); setEffort(value.selection.effort); }
    }).catch(() => { if (active) setMessage("ChatGPTの連携状態を確認できません。画面を開き直してください。"); });
    return () => { active = false; };
  }, []);

  async function run(task: () => Promise<void>) {
    setBusy(true); setMessage("");
    try { await task(); }
    catch (error) {
      const code = error && typeof error === "object" && "code" in error && typeof error.code === "string" ? error.code : undefined;
      setMessage(chatGPTFailure(code) ?? (error instanceof Error ? error.message : "ChatGPTとの接続を確認してください。"));
      try { setStatus(await ChatGPT.getStatus()); } catch { /* Keep the last observed state on a read failure. */ }
    }
    finally { setBusy(false); setSigningIn(false); }
  }
  function changeModel(value: string) { setModel(value); setProbe(null); }
  async function connect() {
    setSigningIn(true);
    const connected = await ChatGPT.signIn(); setStatus(connected); setProbe(null);
    if (connected.planEnabled) {
      const current = await ChatGPT.listModels(); setStatus(current);
      setModel(current.selection.model); setEffort(current.selection.effort);
      setMessage("連携しました。調査に使うモデルと考える深さを確認してください。");
    } else setMessage("ログインできました。調査にはChatGPTの利用枠を使う許可が必要です。");
  }
  const selectedExists = status?.models.some(item => item.slug === model) ?? false;
  return <div className="subscreen sub-settings chatgpt-panel"><div className="ss-compact">
    <SettingGroup number="01" title="利用条件"><ExternalPermissionPanel compact /><Link className="button secondary" to="/today/chatgpt">手動相談</Link><p className="subhint">手動相談はログイン不要です。</p></SettingGroup>
    <SettingGroup number="02" title="任意のアカウント連携">
    <p className="connection-status">{status?.connected
      ? `${status.accountLabel ?? "ChatGPT"} · ${status.planEnabled ? "利用枠の連携済み" : "利用枠の許可が必要"}`
      : status?.disconnecting ? "連携を解除しています…" : status?.reauthorizationRequired ? "ログインの更新が必要です" : status ? "未連携" : "連携状態を確認しています…"}</p>
    {(!status?.connected || !status.planEnabled) && <div className="button-stack">
      <button className="button button--primary" disabled={!status || busy || status.disconnecting} onClick={() => void run(connect)}>Continue with ChatGPT</button>
    </div>}
    </SettingGroup><SettingGroup number="03" title="調査設定">
    {!status?.planEnabled && <><Field label="モデル"><select className="input" disabled><option>連携後に選択</option></select></Field><Field label="調査の深さ"><select className="input" disabled value={effort}>{depths.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></Field><KV label="接続テスト" value="連携・調査設定の保存後に実行" /></>}
    {status?.planEnabled && <div className="settings-content">
      <div className="button-stack">
        <button className="button button--secondary" disabled={busy} onClick={() => void run(async () => {
          setStatus(await ChatGPT.listModels()); setMessage("このアカウントのモデル一覧を取得しました。");
        })}>使えるモデルを読み込む</button>
      </div>
      <Field label="調査モデル"><select className="input" value={model} disabled={busy || status.models.length === 0} onChange={event => changeModel(event.target.value)}>
        <option value="">モデルを選択</option>
        {model && !selectedExists && <option value={model}>{model}（一覧の再確認が必要）</option>}
        {status.models.map(item => <option key={item.slug} value={item.slug}>{item.displayName}</option>)}
      </select></Field>
      <Field label="考える深さ"><select className="input" value={effort} disabled={busy} onChange={event => { setEffort(event.target.value as ReasoningEffort); setProbe(null); }}>
        {depths.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></Field>
      <p className="setting-footnote">対応する深さと検索機能は、選んだモデルで接続確認します。高い設定ほど処理時間・利用枠を使う傾向があります。</p>
      <div className="button-stack">
        <button className="button button--primary" disabled={busy || !selectedExists} onClick={() => void run(async () => {
          setStatus(await ChatGPT.saveSelection({ model, effort })); setProbe(null); setMessage("調査モデルと考える深さを保存しました。");
        })}>調査設定を保存</button>
        <button className="button button--secondary" disabled={busy || !selectedExists || status.selection.model !== model || status.selection.effort !== effort}
          onClick={() => void run(async () => { setProbe(null); setProbe(await ChatGPT.probe()); setMessage("指定したモデル・深さで、検索と出典の受取を確認しました。"); })}>
          検索付きで接続を確認
        </button>
      </div>
      <p className="setting-footnote">接続確認もChatGPTの利用枠を使います。上限後の追加クレジット利用は、ChatGPTの設定でOFFにできます。</p>
    </div>}
    {probe && <div className="connection-probe">
      <strong>接続確認の結果</strong><p>{probe.text}</p>
      <ul>{probe.citations.map((item, index) => <li key={`${item.url}-${index}`}><a href={item.url} target="_blank" rel="noreferrer">{item.title}</a></li>)}</ul>
      <small>{probe.model} · {depths.find(([value]) => value === probe.effort)?.[1]} · {probe.completedAt}</small>
    </div>}
    <p role="status">{busy ? (signingIn ? "OpenAIの画面でログインしてください。" : "ChatGPTへ接続しています…") : message}</p>
    {signingIn && <div className="button-stack"><button className="button button--secondary" onClick={() => void ChatGPT.cancelSignIn().catch(() => setMessage("ログインの中止を確認できませんでした。画面を開き直してください。"))}>ログインを中止</button></div>}
    <section className="settings-disclosure">
      <h3 className="plain-section-title">連携について</h3>
      <div className="settings-content">
        <p>利用枠はChatGPT・Codexと共有します。別料金のAPIへ自動切替しません。APIキーや口座残高は調査へ送りません。</p>
        <p>数値モデルの提案とChatGPTの調査は別々に保存・表示します。ここでの接続成功はモデル採用や投資判断の正しさを示すものではありません。</p>
        {status?.connected && <div className="button-stack"><button className="button button--secondary" disabled={busy || status.disconnecting} onClick={() => void run(connect)}>ログインし直す</button></div>}
        {status?.connected && <div className="danger-zone">
          <label className="check-label"><input type="checkbox" checked={disconnectConfirmed} onChange={event => setDisconnectConfirmed(event.target.checked)} />この端末のChatGPT連携を解除する</label>
          <button className="button button--secondary" disabled={busy || !disconnectConfirmed} onClick={() => void run(async () => {
            const disconnected = await ChatGPT.signOut();
            setStatus(disconnected); setModel(""); setProbe(null); setDisconnectConfirmed(false);
            setMessage(disconnected.revocationConfirmed ? "ChatGPTのセッションを失効し、この端末の資格情報を削除しました。" : "この端末の資格情報を削除しました。OpenAI側の失効は確認できていません。ChatGPTの設定でアプリの接続を確認してください。");
          })}>確認して連携解除</button>
        </div>}
      </div>
    </section>
  </SettingGroup></div></div>;
}

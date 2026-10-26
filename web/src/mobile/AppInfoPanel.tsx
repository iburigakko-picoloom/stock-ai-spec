import { useEffect, useState } from "react";
import { StockAI, type ReleaseInfo } from "./native";

export function AppInfoPanel() {
  const [info,setInfo]=useState<{versionName:string;versionCode:number}|null>(null);
  const [release,setRelease]=useState<ReleaseInfo|null>(null);
  const [busy,setBusy]=useState(false), [message,setMessage]=useState("");
  useEffect(()=>{let active=true; void StockAI.appInfo().then(value=>{if(active)setInfo(value);}).catch(()=>{if(active)setMessage("インストール済みの版を取得できません。");});return()=>{active=false;};},[]);
  return <>
    <section className="numbered-section"><small>01</small><h2>バージョン・更新</h2><dl className="summary-list"><div><dt>アプリ</dt><dd>株AI</dd></div><div><dt>バージョン</dt><dd>{info?.versionName ?? "未取得"}</dd></div><div><dt>ビルド</dt><dd>{info?.versionCode ?? "未取得"}</dd></div></dl>
      <button className="button button--secondary" disabled={busy} onClick={()=>{setBusy(true);setMessage("");void StockAI.checkUpdate().then(value=>{setRelease(value);setMessage(value.available ? `${value.versionName}へ更新できます。` : "利用できる更新はありません。");}).catch(()=>setMessage("更新情報を取得できません。現在のアプリを利用できます。")).finally(()=>setBusy(false));}}>更新を確認</button>
      {release?.available && <button className="button button--primary" disabled={busy} onClick={()=>{setBusy(true);void StockAI.installUpdate({versionCode:release.versionCode}).then(value=>setMessage(value.needsPermission ? "Androidの設定で更新を許可してください。" : "Androidの確認画面でインストールしてください。")).catch(()=>setMessage("更新を取得できませんでした。")).finally(()=>setBusy(false));}}>更新</button>}
      {message && <p role="status">{message}</p>}
    </section>
    <section className="numbered-section"><small>02</small><h2>変更履歴</h2><p className="setting-footnote">{release?.notes || "「更新を確認」で公開版の変更内容を取得します。"}</p></section>
    <section className="numbered-section"><small>03</small><h2>ライセンス・ソース</h2><a className="quiet-link" href="/python/licenses.html" target="_blank" rel="noreferrer">オープンソースの表示・ソース取得先</a></section>
  </>;
}

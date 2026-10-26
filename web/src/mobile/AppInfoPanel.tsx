import { useEffect, useState } from "react";
import { StockAI, type ReleaseInfo } from "./native";
import { KV, SettingGroup } from "../Adopted";

export function AppInfoPanel() {
  const [info,setInfo]=useState<{versionName:string;versionCode:number}|null>(null);
  const [release,setRelease]=useState<ReleaseInfo|null>(null);
  const [busy,setBusy]=useState(false), [message,setMessage]=useState("");
  useEffect(()=>{let active=true; void StockAI.appInfo().then(value=>{if(active)setInfo(value);}).catch(()=>{if(active)setMessage("インストール済みの版を取得できません。");});return()=>{active=false;};},[]);
  return <div className="subscreen sub-settings"><div className="ss-compact">
    <SettingGroup number="01" title="バージョン・更新"><KV label="アプリ" value="株AI" /><KV label="バージョン" value={info?.versionName ?? "未取得"} /><KV label="ビルド" value={info?.versionCode ?? "未取得"} />
      <button className="button button--secondary" disabled={busy} onClick={()=>{setBusy(true);setMessage("");void StockAI.checkUpdate().then(value=>{setRelease(value);setMessage(value.available ? `${value.versionName}へ更新できます。` : "利用できる更新はありません。");}).catch(()=>setMessage("更新情報を取得できません。現在のアプリを利用できます。")).finally(()=>setBusy(false));}}>更新を確認</button>
      {release?.available && <button className="button button--primary" disabled={busy} onClick={()=>{setBusy(true);void StockAI.installUpdate({versionCode:release.versionCode}).then(value=>setMessage(value.needsPermission ? "Androidの設定で更新を許可してください。" : "Androidの確認画面でインストールしてください。")).catch(()=>setMessage("更新を取得できませんでした。")).finally(()=>setBusy(false));}}>更新</button>}
      {message && <p role="status">{message}</p>}
    </SettingGroup>
    <SettingGroup number="02" title="変更履歴"><p className="subhint">{release?.notes || "「更新を確認」で公開版の変更内容を取得します。"}</p></SettingGroup>
    <SettingGroup number="03" title="ライセンス・ソース"><a className="quiet-link" href="/python/licenses.html" target="_blank" rel="noreferrer">オープンソースの表示・ソース取得先</a></SettingGroup>
  </div></div>;
}

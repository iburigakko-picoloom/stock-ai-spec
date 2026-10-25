import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiPost } from "../api";
import { isAndroid } from "./native";

export function ReferenceAnalysis({ onSaved, hasSaved }: { onSaved: () => void; hasSaved: boolean }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [target, setTarget] = useState("market");
  const acting = useRef(false);
  if (!isAndroid()) return null;
  async function generate() {
    if (acting.current) return;
    acting.current = true; setBusy(true); setMessage("");
    try {
      const result = await apiPost<{ phase: string; blocking_reasons: string[] }>("/api/v1/mobile/daily/generate", { reference_only: true });
      if (result.phase === "reference_saved") { onSaved(); setMessage("参考分析を保存しました。"); }
      else {
        const codes = result.blocking_reasons;
        if (codes.some(x => x.includes("PERSONAL") || x.includes("LEDGER") || x.includes("RECONCILIATION"))) {
          setMessage("口座・保有と残高の確定を確認してください。"); setTarget("accounts");
        } else if (codes.some(x => x.includes("MODEL_BUNDLE") || x.startsWith("ENSEMBLE_"))) {
          setMessage("取り込んだモデルの利用条件を確認してください。"); setTarget("model");
        } else {
          setMessage("分析に必要な株価・銘柄一覧・履歴が不足しています。市場データを取得してください。"); setTarget("market");
        }
      }
    } catch {
      setMessage("参考分析を保存できませんでした。市場データの取得状況を確認してください。保存済み分析は保持しています。"); setTarget("market");
    } finally { acting.current = false; setBusy(false); }
  }
  return <section className="section" aria-label="最新データの参考分析">
    {!hasSaved && <><h2>表示できる分析がまだありません</h2><p>休場日でも、直近の確定株価で参考分析を作れます。</p></>}
    <button className="button button--primary" disabled={busy} onClick={() => void generate()}>{busy ? "参考分析を計算・保存中…" : "最新データで分析する"}</button>
    {busy && <><progress aria-label="参考分析を計算中" style={{ width: "100%" }} /><p>画面を閉じても処理を続けます。</p></>}
    {!hasSaved && <p className="setting-footnote">現在の登録内容を使う閲覧用の分析です。当日の売買提案とは別です。</p>}
    {message && <p role="status">{message}</p>}
    {message && message !== "参考分析を保存しました。" && <Link className="button button--secondary" to={`/settings?edit=${target}`}>{target === "market" ? "市場データを取得する" : "登録内容を確認する"}</Link>}
  </section>;
}

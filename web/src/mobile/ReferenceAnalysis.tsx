import { useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { apiPost } from "../api";
import { isAndroid } from "./native";

export function ReferenceAnalysis({ onSaved, hasSaved, disabled = false, onBusy }: { onSaved: () => void; hasSaved: boolean; disabled?: boolean; onBusy?: (value: boolean) => void }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [target, setTarget] = useState("market");
  const acting = useRef(false);
  const location = useLocation();
  if (!isAndroid()) return null;
  async function generate() {
    if (acting.current || disabled) return;
    acting.current = true; setBusy(true); onBusy?.(true); setMessage("");
    try {
      const result = await apiPost<{ phase: string; blocking_reasons: string[] }>("/api/v1/mobile/daily/generate", { reference_only: true });
      if (result.phase === "reference_saved") { onSaved(); setMessage("参考分析を保存しました。"); }
      else {
        const codes = result.blocking_reasons;
        if (codes.some(x => x === "PERSONAL_HOLDINGS_UNCONFIRMED" || x === "HOLDINGS_NEED_RECONCILIATION")) {
          setMessage("実保有の登録内容を確認してください。"); setTarget("holdings");
        } else if (codes.some(x => x.includes("PERSONAL") || x.includes("LEDGER") || x.includes("RECONCILIATION"))) {
          setMessage("口座・保有と残高の確定を確認してください。"); setTarget("accounts");
        } else if (codes.some(x => x.includes("MODEL_BUNDLE") || x.startsWith("ENSEMBLE_"))) {
          setMessage("取り込んだモデルの利用条件を確認してください。"); setTarget("model");
        } else if (codes.some(x => x.startsWith("UNIVERSE_") || x === "NO_USABLE_FORECAST" || x.startsWith("HELD_FORECAST_MISSING") || x === "REFERENCE_MARKET_DATE_MISMATCH")) {
          setMessage("分析に必要な株価・銘柄一覧・履歴が不足しています。市場データを取得してください。"); setTarget("market");
        } else {
          setMessage(codes.length ? `分析を完了できませんでした。診断コード：${codes.join(" / ")}` : "分析を完了できませんでした。停止理由が記録されていません。"); setTarget("");
        }
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "分析を完了できませんでした。途中保存から再開できます。"); setTarget("");
    } finally { acting.current = false; setBusy(false); onBusy?.(false); }
  }
  return <section className="section" aria-label="最新データの参考分析">
    {!hasSaved && <><h2>表示できる分析がまだありません</h2><p>休場日でも、直近の確定株価で参考分析を作れます。</p></>}
    <button className="button button--primary" disabled={busy || disabled} onClick={() => void generate()}>{busy ? "参考分析を計算・保存中…" : "最新データで分析する"}</button>
    {busy && <p>画面を閉じても処理を続けます。途中結果は自動保存します。</p>}
    {!hasSaved && <p className="setting-footnote">現在の登録内容を使う閲覧用の分析です。当日の売買提案とは別です。</p>}
    {message && <p role="status">{message}</p>}
    {message && target && !(location.pathname === "/settings" && new URLSearchParams(location.search).get("edit") === target) && message !== "参考分析を保存しました。" && <Link className="button button--secondary" to={target === "holdings" ? "/holdings" : `/settings?edit=${target}`}>{target === "market" ? "市場データを取得する" : target === "holdings" ? "実保有を登録・編集" : "登録内容を確認する"}</Link>}
  </section>;
}

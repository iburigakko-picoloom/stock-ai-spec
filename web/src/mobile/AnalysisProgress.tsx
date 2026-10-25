import { useEffect, useState } from "react";
import { isAndroid, StockAI, type AnalysisStatus } from "./native";

function blockedReason(codes: string[]) {
  const code = codes[0] ?? "";
  if (code === "ENSEMBLE_RANK_POPULATION_INCOMPLETE") return "モデルが必要とする銘柄の株価履歴が不足しています。市場データとモデルの対象条件を確認してください。";
  if (code === "NO_USABLE_FORECAST" || code.startsWith("HELD_FORECAST_MISSING")) return "予測に必要な株価履歴が不足しています。市場データを確認してください。";
  if (/PERSONAL|LEDGER|RECONCILIATION/.test(code)) return "口座・保有の登録内容を確認してください。";
  if (code.includes("MODEL_BUNDLE") || code.startsWith("ENSEMBLE_")) return `取り込んだモデルの利用条件を確認してください。${code ? `（${code}）` : ""}`;
  if (code.startsWith("UNIVERSE_") || code === "REFERENCE_MARKET_DATE_MISMATCH") return "銘柄一覧と株価の日付が揃っていません。市場データを確認してください。";
  return code ? `分析に必要な条件を満たしていません。（${code}）` : "分析に必要な情報を確認できませんでした。予測設定で停止理由を確認してください。";
}

export function AnalysisProgress({ busy = false }: { busy?: boolean }) {
  const [status, setStatus] = useState<AnalysisStatus | null>(null);
  useEffect(() => {
    if (!isAndroid()) return;
    let alive = true;
    const refresh = () => { void StockAI.analysisStatus().then(value => { if (alive) setStatus(value); }).catch(() => {}); };
    refresh();
    const timer = window.setInterval(refresh, 1000);
    window.addEventListener("focus", refresh);
    return () => { alive = false; window.clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, []);
  if (!busy && !["running", "interrupted", "blocked"].includes(status?.state ?? "")) return null;
  const percent = status?.percent;
  const paused = status?.state === "interrupted" || status?.state === "blocked";
  const blocked = status?.state === "blocked";
  const reason = ({ timeout: "処理時間の上限で中断しました。", memory: "計算環境が終了しました。", calculation: "計算・保存を完了できませんでした。" } as Record<string, string>)[status?.failure ?? ""] ?? (status?.state === "blocked" ? "分析の完了条件を満たしていません。" : "");
  const phase = ({ preparing: "データ準備中", features: "銘柄を計算中", predicting: "モデルで予測中", saving: "予測結果を保存中" } as Record<string, string>)[status?.phase ?? ""] ?? "予測を計算中";
  return <div className="analysis-progress" aria-live="polite">
    <p>{blocked ? "分析を完了できませんでした" : `${paused ? "中断・途中保存済み" : phase}${typeof percent === "number" ? ` ${percent}%` : ""}`}</p>
    {!blocked && <progress aria-label="予測の保存済み進捗" max={100} value={typeof percent === "number" ? percent : undefined} style={{ width: "100%" }} />}
    <p className="setting-footnote">{blocked ? blockedReason(status?.blockingReasons ?? []) : paused ? `${reason} 同じ分析を開始すると、保存済みの続きから再開します。` : "完了した計算量の割合です。途中結果を自動保存しています。"}</p>
  </div>;
}

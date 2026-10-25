import { useEffect, useState } from "react";
import { isAndroid, StockAI, type AnalysisStatus } from "./native";

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
  if (!busy && !["running", "interrupted"].includes(status?.state ?? "")) return null;
  const percent = status?.percent;
  const paused = status?.state === "interrupted" && !busy;
  const phase = ({ preparing: "データ準備中", features: "銘柄を計算中", predicting: "モデルで予測中" } as Record<string, string>)[status?.phase ?? ""] ?? "予測を計算中";
  return <div className="analysis-progress" aria-live="polite">
    <p>{paused ? "中断・途中保存済み" : phase}{typeof percent === "number" ? ` ${percent}%` : ""}</p>
    <progress aria-label="予測の保存済み進捗" max={100} value={typeof percent === "number" ? percent : undefined} style={{ width: "100%" }} />
    <p className="setting-footnote">{paused ? "同じ分析を開始すると、保存済みの続きから再開します。" : "完了した計算量の割合です。途中結果を自動保存しています。"}</p>
  </div>;
}

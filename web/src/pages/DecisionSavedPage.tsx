import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { PageHeader, StatePanel } from "../components";
import { useApiData } from "../hooks";
import type { TodayResponse } from "../types";

interface SavedDecision {
  decision_id: string;
  version: number;
  saved_at: string;
  confirms_manual_order_only: boolean;
}

export function DecisionSavedPage(): ReactNode {
  const today = useApiData<TodayResponse & { decision: SavedDecision | null }>("/api/v1/execution-context");
  const proposalId = today.data?.proposal?.proposalId;
  const decision = today.data?.decision;
  if (today.loading || today.error || !proposalId || !decision) return <div className="page"><Link className="back-link" to="/today">← 今日へ戻る</Link><PageHeader title="保存済み判断" /><StatePanel title={today.loading ? "保存済み判断を確認しています" : today.error ? "保存済み判断を取得できません" : "保存済み判断はありません"} detail={today.error || (!today.loading ? "今日の提案から判断を保存してください。" : undefined)} /></div>;
  return (
    <div className="page">
      <PageHeader eyebrow={`Version ${decision.version}`} title="判断を保存しました" />
      <section className="success-panel">
        <span aria-hidden="true">✓</span>
        <strong>ローカル台帳へ保存済み</strong>
        <p>AI提案は変更されていません。証券会社への注文・通信は行っていません。</p>
      </section>
      <div className="button-stack">
        <Link className="button button--primary" to="/today/executions">実行結果を記録</Link>
        <Link className="button button--secondary" to="/today/review">判断を修正して新versionで保存</Link>
        <Link className="text-link" to="/today">今日へ戻る</Link>
      </div>
    </div>
  );
}

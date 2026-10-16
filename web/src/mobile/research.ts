import { apiPost } from "../api";
import { ChatGPT, chatGPTFailure, type ResearchExecution, type ResearchRunView } from "./chatgpt";

interface Claim extends ResearchRunView {
  state: "ready" | "running" | "completed" | "blocked";
  attempt?: ResearchRunView["attempts"][number];
  request_json?: string;
  request_sha256?: string;
}
const active = new Map<string, Promise<ResearchRunView>>();

export function researchFailure(code: string | null | undefined): string {
  const connectionMessage = chatGPTFailure(code ?? undefined);
  if (connectionMessage) return connectionMessage;
  if (code?.includes("unsupported") || code === "HTTP_400") return "選んだモデル・考える深さ・検索機能の対応を設定で確認してください。";
  if (code === "MODEL_SELECTION_CHANGED") return "調査開始時からモデル設定が変わりました。表示中の設定に戻すか、新しい設定で調査してください。";
  if (code?.includes("SIGN_IN") || code?.includes("TOKEN") || code === "HTTP_401") return "ChatGPTへの再ログインが必要です。設定で連携を確認してください。";
  if (code?.includes("PERMISSION") || code === "HTTP_403") return "ChatGPTの利用枠・検索機能の利用権限を設定で確認してください。";
  if (code === "INVALID_RESEARCH_RESPONSE") return "調査は完了条件を満たしませんでした。検索・出典・回答の完了状態を確認できていません。";
  return "調査は未完了です。保存済みの結果を残しています。接続を確認して中断した段階を再試行できます。";
}

async function saveExecution(attemptId: string, result: ResearchExecution): Promise<ResearchRunView> {
  if (result.attemptId !== attemptId) throw new Error("調査の実行記録が一致しません。画面を開き直してください。");
  if (result.state === "running") throw new Error("この調査は実行中です。完了を待ってから状況を確認してください。");
  const body = result.state === "completed" ? {
    response: result.response, started_at: result.startedAt, completed_at: result.completedAt,
  } : {
    error_code: "errorCode" in result && /^[A-Za-z0-9_]{1,100}$/.test(result.errorCode)
      ? result.errorCode : "EXECUTION_RECEIPT_UNAVAILABLE",
    interrupted: result.state !== "failed",
  };
  // On Android apiPost resolves only after encrypted native state has committed.
  const saved = await apiPost<ResearchRunView>(`/api/v1/research/${attemptId}/receipt`, body);
  if (result.state === "completed") {
    // Keep the durable native response if acknowledgment fails; it is safe to
    // submit the same receipt again, and no second provider request is needed.
    await ChatGPT.forgetExecution({ attemptId }).catch(() => undefined);
  }
  const outcome = saved.attempts.find(item => item.attempt_id === attemptId);
  if (!outcome || outcome.status !== "completed") throw new Error(researchFailure(outcome?.error_code));
  return saved;
}

async function drive(
  runId: string, retry: boolean, progress: (message: string) => void,
): Promise<ResearchRunView> {
  for (let stage = 0; stage < 3; stage++) {
    const claim = await apiPost<Claim>(`/api/v1/research/${runId}/claim`, { retry });
    retry = false;
    if (claim.state === "completed") return claim;
    if (claim.state === "blocked") throw new Error(researchFailure(claim.attempt?.error_code));
    const attempt = claim.attempt;
    if (!attempt) throw new Error("調査の開始記録を確認できません。");
    let result: ResearchExecution;
    if (claim.state === "running") {
      progress("保存済みの実行状況を確認しています…");
      // A native observation seals an absent attempt before reporting it lost,
      // preventing a delayed caller from submitting that same attempt afterward.
      result = await ChatGPT.recoverExecution({ attemptId: attempt.attempt_id });
    } else {
      if (!claim.request_json || !claim.request_sha256) throw new Error("調査の入力を確認できません。");
      progress(attempt.phase === "independent" ? "公開情報から独立した企業調査をしています…" : "独立調査と数値予測を照合しています…");
      const configuration = claim.run.context.configuration;
      try {
        result = await ChatGPT.respond({
          attemptId: attempt.attempt_id, requestJson: claim.request_json,
          requestSha256: claim.request_sha256, model: configuration.model, effort: configuration.effort,
        });
      } catch {
        // A rejected JavaScript call does not prove whether the native request
        // completed. Inspect the specific execution before changing its state.
        result = await ChatGPT.recoverExecution({ attemptId: attempt.attempt_id });
      }
    }
    if ((result.state === "completed" || result.requestSha256) && (!claim.request_sha256 || result.requestSha256 !== claim.request_sha256)) {
      throw new Error("調査入力と受取記録が一致しません。自動再送せず停止しました。");
    }
    const saved = await saveExecution(attempt.attempt_id, result);
    if (saved.record) return saved;
  }
  throw new Error("調査の状態を確認できません。画面を開き直してください。");
}

export function runResearch(
  runId: string, options: { retry?: boolean; progress?: (message: string) => void } = {},
): Promise<ResearchRunView> {
  const existing = active.get(runId);
  if (existing) return existing;
  const task = drive(runId, options.retry ?? false, options.progress ?? (() => undefined));
  active.set(runId, task);
  void task.finally(() => { active.delete(runId); }).catch(() => undefined);
  return task;
}

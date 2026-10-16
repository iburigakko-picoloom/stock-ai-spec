import { registerPlugin } from "@capacitor/core";

export type ReasoningEffort = "low" | "medium" | "high" | "xhigh" | "max";
export interface ChatGPTStatus {
  connected: boolean;
  planEnabled: boolean;
  accountLabel: string | null;
  state: "disconnected" | "authorizing" | "connected";
  selection: { model: string; effort: ReasoningEffort };
  models: { slug: string; displayName: string }[];
  apiFallback: false;
  reauthorizationRequired?: boolean;
  disconnecting?: boolean;
  revocationConfirmed?: boolean | null;
}

export function chatGPTFailure(code: string | undefined): string | undefined {
  if (!code) return undefined;
  if (["invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused", "SIGN_IN_REQUIRED"].includes(code))
    return "ChatGPTへのログインを更新してください。調査結果とモデル設定は保存されています。";
  if (code === "subscription_sharing_user_not_eligible") return "このアカウントではChatGPTの利用枠を連携できません。利用資格やワークスペースの設定を確認してください。";
  if (code === "subscription_sharing_usage_limit_exceeded" || code === "HTTP_429") return "このアプリのChatGPT利用上限に達しました。ChatGPTの利用状況を確認してください。";
  if (code === "subscription_sharing_usage_unavailable" || code === "subscription_sharing_user_unavailable" || code === "HTTP_503") return "ChatGPTを一時的に利用できません。連携情報は保持しています。時間をおいて再試行してください。";
  if (code === "PLAN_PERMISSION_REQUIRED") return "ChatGPTの利用枠を使う許可が必要です。設定画面でログインを更新してください。";
  if (code === "SIGN_OUT_PENDING") return "ChatGPTの連携解除を処理しています。完了を待ってください。";
  if (code === "SAVED_ACCOUNT_MISMATCH") return "登録済みのChatGPTアカウントと一致しません。同じアカウントでログインしてください。";
  return undefined;
}
export interface ConnectionProbe {
  text: string;
  citations: { url: string; title: string }[];
  model: string;
  effort: ReasoningEffort;
  completedAt: string;
}
export interface ResearchContext {
  prediction_snapshot_id: string;
  symbol: string;
  company_name: string;
  numerical_as_of: string;
  research_as_of: string;
  configuration: { model: string; effort: ReasoningEffort; prompt_version: string };
  revision: number;
}
export interface ResearchPass {
  pass_id: string;
  context: ResearchContext;
  phase: "independent" | "comparison";
  served_model: string;
  started_at: string;
  completed_at: string;
  text: string;
  sources: { url: string; title: string; published_at: string | null }[];
  searched: boolean;
}
export interface ResearchRecord {
  research_id: string;
  context: ResearchContext;
  independent: ResearchPass;
  comparison: ResearchPass;
  affects_numerical_proposal: false;
}
export interface ResearchAttempt {
  attempt_id: string;
  run_id: string;
  phase: "independent" | "comparison";
  status: "running" | "completed" | "failed" | "interrupted";
  started_at: string;
  finished_at: string | null;
  pass_id: string | null;
  error_code: string | null;
}
export interface ResearchRunView {
  run: { run_id: string; context: ResearchContext };
  passes: ResearchPass[];
  attempts: ResearchAttempt[];
  record: ResearchRecord | null;
}
export type ResearchExecution = {
  attemptId: string;
  requestSha256?: string;
} & ({ state: "completed"; response: Record<string, unknown>; startedAt: string; completedAt: string }
  | { state: "running" | "missing" | "acknowledged" }
  | { state: "failed" | "interrupted"; errorCode: string });
interface ChatGPTNative {
  getStatus(): Promise<ChatGPTStatus>;
  signIn(): Promise<ChatGPTStatus>;
  cancelSignIn(): Promise<void>;
  signOut(): Promise<ChatGPTStatus>;
  listModels(): Promise<ChatGPTStatus>;
  saveSelection(value: ChatGPTStatus["selection"]): Promise<ChatGPTStatus>;
  probe(): Promise<ConnectionProbe>;
  respond(value: {
    attemptId: string; requestJson: string; requestSha256: string;
    model: string; effort: ReasoningEffort;
  }): Promise<ResearchExecution>;
  getExecution(value: { attemptId: string }): Promise<ResearchExecution>;
  recoverExecution(value: { attemptId: string }): Promise<ResearchExecution>;
  forgetExecution(value: { attemptId: string }): Promise<void>;
}
export const ChatGPT = registerPlugin<ChatGPTNative>("StockAIChatGPT");

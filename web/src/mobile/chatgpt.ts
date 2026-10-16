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

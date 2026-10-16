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
interface ChatGPTNative {
  getStatus(): Promise<ChatGPTStatus>;
  signIn(): Promise<ChatGPTStatus>;
  cancelSignIn(): Promise<void>;
  signOut(): Promise<ChatGPTStatus>;
  listModels(): Promise<ChatGPTStatus>;
  saveSelection(value: ChatGPTStatus["selection"]): Promise<ChatGPTStatus>;
  probe(): Promise<ConnectionProbe>;
}
export const ChatGPT = registerPlugin<ChatGPTNative>("StockAIChatGPT");

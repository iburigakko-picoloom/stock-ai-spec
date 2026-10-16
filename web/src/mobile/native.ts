import { Capacitor, registerPlugin } from "@capacitor/core";

export interface NativeState { generation: number; payload: string }
export interface NativeMarketReceipt {
  date: string; acquisitionId: string; received_at?: string; status: number;
  datasets?: Record<string, unknown[]>; valuations?: unknown[]; failedDataset?: string;
  purpose?: string; source_pages?: unknown[];
}
export interface ReleaseInfo {
  available: boolean; versionName: string; versionCode: number;
  notes: string; sha256: string; url: string; size: number;
}
export interface StockAINative {
  compute(input: { method: "GET" | "POST"; path: string; body: string }): Promise<{ status: number; body: unknown }>;
  restoreState(input: { payload: string }): Promise<{ generation: number }>;
  readState(): Promise<NativeState>;
  writeState(input: NativeState): Promise<{ generation: number }>;
  keyStatus(): Promise<{ configured: boolean }>;
  saveApiKey(input: { apiKey: string }): Promise<void>;
  clearApiKey(): Promise<void>;
  checkUpdate(): Promise<ReleaseInfo>;
  installUpdate(input: { versionCode: number }): Promise<{ needsPermission: boolean }>;
  fetchMarket(input: { date: string }): Promise<NativeMarketReceipt>;
  fetchMembership(input: { date: string }): Promise<NativeMarketReceipt>;
  acknowledgeMembership(input: { date: string; acquisitionId: string }): Promise<void>;
  restartMembership(input: { date: string }): Promise<void>;
  acknowledgeMarket(input: { date: string; acquisitionId: string }): Promise<void>;
  restartMarket(input: { date: string }): Promise<void>;
  exportBackup(input: { password: string }): Promise<void>;
  importBackup(input: { password: string }): Promise<NativeState>;
  importModel(): Promise<{ content: string }>;
}
export const isAndroid = (): boolean => Capacitor.isNativePlatform() && Capacitor.getPlatform() === "android";
export const StockAI = registerPlugin<StockAINative>("StockAI");

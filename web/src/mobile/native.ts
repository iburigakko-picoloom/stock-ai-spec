import { Capacitor, registerPlugin } from "@capacitor/core";

export interface NativeState { generation: number; payload: string }
export interface BackupPreview { token: string; characters: number }
export interface DailyStatus {
  enabled: boolean; state: string; firstDay?: string; day?: string | null;
  updatedAt?: string; retryAt?: string | null; notificationsEnabled: boolean;
}
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
  appInfo(): Promise<{ applicationId: string; versionName: string; versionCode: number }>;
  analysisStatus(): Promise<AnalysisStatus>;
  readSavedView(input: { path: string }): Promise<{ available: boolean; savedAt?: string; readOnly?: boolean; body?: unknown }>;
  dailyStatus(): Promise<DailyStatus>;
  startDaily(): Promise<DailyStatus>;
  stopDaily(): Promise<DailyStatus>;
  requestDailyNotifications(): Promise<{ granted: boolean }>;
  compute(input: { method: "GET" | "POST"; path: string; body: string }): Promise<{ status: number; body: unknown }>;
  restoreState(input: { payload: string }): Promise<{ generation: number }>;
  readState(): Promise<NativeState>;
  writeState(input: NativeState): Promise<{ generation: number }>;
  keyStatus(): Promise<{ configured: boolean }>;
  saveApiKey(input: { apiKey: string }): Promise<void>;
  clearApiKey(): Promise<void>;
  checkUpdate(): Promise<ReleaseInfo>;
  installUpdate(input: { versionCode: number }): Promise<{ needsPermission: boolean }>;
  selectUpdate(): Promise<{ needsPermission: boolean; cancelled?: boolean }>;
  fetchMarket(input: { date: string }): Promise<NativeMarketReceipt>;
  fetchMembership(input: { date: string }): Promise<NativeMarketReceipt>;
  acknowledgeMembership(input: { date: string; acquisitionId: string }): Promise<void>;
  restartMembership(input: { date: string }): Promise<void>;
  acknowledgeMarket(input: { date: string; acquisitionId: string }): Promise<void>;
  restartMarket(input: { date: string }): Promise<void>;
  exportBackup(input: { password: string }): Promise<void>;
  importBackup(input: { password: string }): Promise<BackupPreview>;
  discardBackup(input: { token: string }): Promise<void>;
  restoreBackup(input: { token: string; confirmed: true }): Promise<{ generation: number }>;
  importModel(): Promise<{ content: string }>;
}
export interface AnalysisStatus {
  state: "idle" | "running" | "interrupted" | "blocked" | "complete";
  phase?: string; percent?: number | null; savedUnits?: number; totalUnits?: number;
    savedRevision?: number; failure?: string; blockingReasons?: string[];
    responseStatus?: number; responseCode?: string; diagnostic?: string;
}
export const isAndroid = (): boolean => Capacitor.isNativePlatform() && Capacitor.getPlatform() === "android";
export const StockAI = registerPlugin<StockAINative>("StockAI");

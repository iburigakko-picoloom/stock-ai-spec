import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "jp.stockai.app",
  appName: "StockAI",
  webDir: "dist",
  server: { androidScheme: "https" },
  android: { allowMixedContent: false, webContentsDebuggingEnabled: false },
};
export default config;

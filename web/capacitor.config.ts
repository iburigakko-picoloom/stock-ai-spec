import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "jp.stockai.app",
  appName: "StockAI",
  webDir: "dist",
  loggingBehavior: "none",
  server: { androidScheme: "https" },
  // The application compute owner supplies the APK-only Worker loader. An
  // Activity recreation must not replace it with the UI WebView's asset server.
  android: { allowMixedContent: false, webContentsDebuggingEnabled: false, resolveServiceWorkerRequests: false },
};
export default config;

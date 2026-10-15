import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./mobile-tests",
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:5196",
    browserName: "chromium",
    channel: process.platform === "win32" ? "msedge" : undefined,
    serviceWorkers: "block",
  },
  webServer: {
    command: "npm run dev -- --port 5196 --strictPort",
    url: "http://127.0.0.1:5196",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});

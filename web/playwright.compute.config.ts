import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./compute-tests",
  workers: 1,
  timeout: 180_000,
  reporter: "line",
  use: { baseURL: "http://127.0.0.1:5197", browserName: "chromium", channel: process.platform === "win32" ? "msedge" : undefined, serviceWorkers: "block" },
  webServer: { command: "npx vite preview --port 5197 --strictPort", url: "http://127.0.0.1:5197", reuseExistingServer: false },
});

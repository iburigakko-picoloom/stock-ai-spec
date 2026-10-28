import { defineConfig } from "@playwright/test";

// Service-worker and precache tests require the production build, not the Vite dev server.
export default defineConfig({
  testDir: "./mobile-tests",
  testMatch: "**/offline-screen-bundles.spec.ts",
  workers: 1,
  timeout: 60_000,
  reporter: "line",
  use: { baseURL: "http://127.0.0.1:5197", browserName: "chromium",
    channel: process.platform === "win32" ? "msedge" : undefined, serviceWorkers: "allow" },
  webServer: { command: "node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 5197 --strictPort",
    url: "http://127.0.0.1:5197", reuseExistingServer: false, timeout: 30_000 },
});

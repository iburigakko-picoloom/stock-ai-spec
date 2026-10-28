import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), {
    name: "precache-screen-assets",
    apply: "build",
    async writeBundle(options, bundle) {
      const assets = Object.keys(bundle).filter(name => name.endsWith(".js") || name.endsWith(".css"));
      const swPath = resolve(options.dir ?? "dist", "sw.js");
      const source = await readFile(swPath, "utf8");
      const marker = "/* BUILD_ASSETS */ []";
      if (!source.includes(marker)) throw new Error("Service worker asset marker is missing");
      await writeFile(swPath, source.replace(marker, JSON.stringify(assets.map(name => `/${name}`))));
    },
  }],
  build: { rolldownOptions: { input: { app: "index.html", compute: "compute.html" } } },
  server: {
    host: "127.0.0.1",
    port: 5173,
    watch: { ignored: ["**/.demo-artifacts/**"] },
    proxy: {
      "/api": "http://127.0.0.1:8765",
    },
  },
  test: {
    environment: "jsdom",
    exclude: [...configDefaults.exclude, "e2e/**", "mobile-tests/**", "compute-tests/**", "android/**"],
    setupFiles: "./src/test-setup.ts",
  },
});

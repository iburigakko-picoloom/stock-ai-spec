import { readFileSync, writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

test("offline bounded search scores 300 candidates plus a holding exactly like PC", async ({ page, context }, info) => {
  const fixture = JSON.parse(readFileSync(new URL("../../.demo-artifacts/android/mobile-golden.json", import.meta.url), "utf-8")).bounded;
  await context.route("https://**", route => route.abort());
  await page.route("**/bounded-test", route => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Synthetic bounded solver parity</title>" }));
  await page.goto("/bounded-test");
  const output = await page.evaluate(async data => {
    const worker = new Worker("/mobile-tests/bounded-worker.ts", { type: "module" });
    try {
      return await new Promise<{ error?: string; result: unknown; elapsed_ms: number }>((resolve, reject) => {
        worker.onmessage = event => resolve(event.data);
        worker.onerror = event => reject(new Error(event.message));
        worker.postMessage(data);
      });
    } finally { worker.terminate(); }
  }, fixture);
  expect(output.error).toBeUndefined();
  expect(output.result).toEqual(fixture.expected);
  const evidence = info.outputPath("synthetic-300-solver.json");
  writeFileSync(evidence, JSON.stringify({ synthetic_only: true, physical_device: false, elapsed_ms: output.elapsed_ms, audit: fixture.expected.search_audit }));
  await info.attach("synthetic-300-solver.json", { contentType: "application/json", path: evidence });
});

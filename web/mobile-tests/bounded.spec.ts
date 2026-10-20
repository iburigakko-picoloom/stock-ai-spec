import { readFileSync, writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

for (const index of [0, 1, 2]) test(`filing relief cannot fund a purchase before cash tax recovery (${index})`, async ({ page, context }) => {
  const fixture = JSON.parse(readFileSync(new URL("../../.demo-artifacts/android/mobile-golden.json", import.meta.url), "utf-8")).withholding[index];
  await context.route("https://**", route => route.abort());
  await page.route("**/withholding-test", route => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Synthetic cash tax parity</title>" }));
  await page.goto("/withholding-test");
  const output = await page.evaluate(async data => {
    const worker = new Worker("/mobile-tests/bounded-worker.ts", { type: "module" });
    try {
      return await new Promise<{ error?: string; result: { estimated_cash_after: Record<string, string>; lines: { symbol: string; recommended_shares: number; estimated_tax_cash_withholding: string; estimated_tax_effect: string }[] } }>((resolve, reject) => {
        worker.onmessage = event => resolve(event.data);
        worker.onerror = event => reject(new Error(event.message));
        worker.postMessage(data);
      });
    } finally { worker.terminate(); }
  }, fixture);
  expect(output.error).toBeUndefined();
  expect(output.result).toEqual(fixture.expected);
  expect(Number(output.result.estimated_cash_after.bucket)).toBe(index === 2 ? 398000 : 98000);
  expect(output.result.lines.every(line => Number(line.estimated_tax_cash_withholding) >= 0)).toBe(true);
  expect(output.result.lines.reduce((sum, line) => sum + Number(line.estimated_tax_cash_withholding), 0)).toBe(2000);
  expect(output.result.lines.reduce((sum, line) => sum + Number(line.estimated_tax_effect), 0)).toBe(0);
  expect(output.result.lines.find(line => line.symbol === "B")!.recommended_shares).toBe(0);
  if (index === 2) expect(Number(output.result.lines.find(line => line.symbol === "z-loss")!.estimated_tax_cash_withholding)).toBe(0);
});

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

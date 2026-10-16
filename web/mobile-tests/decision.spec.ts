import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

test("frozen prices and original forecast produce the same saved personal quantities on PC and WASM", async ({ page, context }) => {
  const fixture = JSON.parse(readFileSync(new URL("../../.demo-artifacts/android/mobile-golden.json", import.meta.url), "utf-8")).decision;
  await context.route("https://**", route => route.abort());
  await page.route("**/decision-test", route => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Synthetic share proposal parity</title>" }));
  await page.goto("/decision-test");
  const output = await page.evaluate(async data => {
    const worker = new Worker("/mobile-tests/decision-worker.ts", { type: "module" });
    try {
      return await new Promise<{ error?: string; result: unknown; restored: unknown; active: boolean; today: { status: number; body: { proposal: { isResearchOnly: boolean; lines: { symbol: string; recommendedShares: number }[] } } } }>((resolve, reject) => {
        worker.onmessage = event => resolve(event.data);
        worker.onerror = event => reject(new Error(event.message));
        worker.postMessage(data);
      });
    } finally { worker.terminate(); }
  }, fixture);
  expect(output.error).toBeUndefined();
  expect(output.result).toEqual(fixture.expected);
  expect(output.restored).toEqual(fixture.expected);
  expect(output.active).toBe(true);
  expect(output.today.status).toBe(200);
  expect(output.today.body.proposal.isResearchOnly).toBe(true);
  expect(Object.fromEntries(output.today.body.proposal.lines.map(x => [x.symbol, x.recommendedShares]))).toEqual({ "1000": 100, "1001": 100, "7203": 37 });
});

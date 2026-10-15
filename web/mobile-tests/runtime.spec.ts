import { readFileSync } from "node:fs";
import { test, expect } from "@playwright/test";

test("offline Python preserves input and matches PC 41/51 features", async ({ page, context }) => {
  const golden = JSON.parse(readFileSync(new URL("../../.demo-artifacts/android/mobile-golden.json", import.meta.url), "utf-8"));
  await context.route("https://**", route => route.abort());
  await page.route("**/mobile-test", route => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Offline runtime verification</title>" }));
  await page.goto("/mobile-test");
  const result = await page.evaluate(async (input) => {
    const worker = new Worker("/src/mobile/compute-worker.ts", { type: "module" });
    let sequence = 0;
    async function send(value: Record<string, unknown>): Promise<Record<string, unknown>> {
      return new Promise((resolve, reject) => {
        const id = ++sequence;
        worker.onmessage = event => {
          if (event.data.id === id) {
            if (event.data.error) reject(new Error(event.data.error));
            else resolve(event.data);
          }
        };
        worker.onerror = event => reject(new Error(event.message));
        worker.postMessage({ ...value, id });
      });
    }
    await send({ command: "initialize", state: "" });
    const health = await send({ command: "request", method: "GET", path: "/api/v1/health" });
    const values = await send({ command: "request", method: "POST", path: "/api/v1/mobile/features", body: JSON.stringify(input) });
    const portfolio = { schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: null, maximum_drawdown_percent: null, accounts: [], holdings: [] };
    const saved = await send({ command: "request", method: "POST", path: "/api/v1/mobile/portfolio", body: JSON.stringify(portfolio) });
    worker.terminate();
    return { health, values, saved };
  }, golden.inputs);
  expect(result.health.result).toMatchObject({ status: 200, body: { orderSubmissionAvailable: false } });
  expect(result.saved.result).toMatchObject({ status: 200, body: { portfolio: { holdings_status: "none", investment_budget_yen: null } } });
  expect(result.saved.state).toBeTruthy();
  const computed = result.values.result as { status: number; body: { features: Record<string, Record<string, unknown>[]> } };
  expect(computed.status).toBe(200);
  for (const horizon of ["5", "20"]) {
    const rows = computed.body.features[horizon];
    expect(rows).toHaveLength(golden.expected[horizon].length);
    rows.forEach((row, index) => {
      const expected = golden.expected[horizon][index];
      expect(Object.keys(row)).toEqual(Object.keys(expected));
      for (const [key, value] of Object.entries(expected)) {
        if (typeof value === "number") expect(Number(row[key])).toBeCloseTo(value, 7);
        else expect(row[key]).toBe(value);
      }
    });
  }
});

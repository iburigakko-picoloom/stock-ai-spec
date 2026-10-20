import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

for (const returnOnly of [false, true]) test(`received history ${returnOnly ? "return-only research" : "complete risk"} computes real features, forecasts, costs and manual review before exact WASM restore`, async ({ page, context }, testInfo) => {
  const fixture = JSON.parse(readFileSync(new URL("../../.demo-artifacts/android/mobile-golden.json", import.meta.url), "utf-8"))[returnOnly ? "received_return_only" : "received_forecast"];
  expect(fixture.synthetic_only).toBe(true);
  const external: string[] = [];
  await context.route("https://**", route => { external.push(route.request().url()); return route.abort(); });
  await page.route("**/received-test", route => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Synthetic received-history integration</title>" }));
  await page.goto("/received-test");
  const output = await page.evaluate(async data => {
    const worker = new Worker("/mobile-tests/received-worker.ts", { type: "module" });
    try {
      return await new Promise<{ error?: string; predictions: unknown; proposal: Record<string, unknown> | null; daily_rows: number; target_pairs: number; risk_groups: number; restored_exact: boolean; ledger_unchanged: boolean; executions: number; rejected_status: number; answer_count: number; table_counts: Record<string, number>; manual_review: { lines: { symbol: string; target_shares: number; share_difference: number }[]; estimated_cost_yen: string }; model_risk_available: boolean; adopted: boolean }>((resolve, reject) => {
        worker.onmessage = event => resolve(event.data);
        worker.onerror = event => reject(new Error(event.message));
        worker.postMessage(data);
      });
    } finally { worker.terminate(); }
  }, fixture);
  await testInfo.attach("received-wasm-result", { body: JSON.stringify(output, null, 2), contentType: "application/json" });
  expect(output.error).toBeUndefined();
  expect(output).toMatchObject({ daily_rows: 6480, target_pairs: 21, risk_groups: 2,
    restored_exact: true, ledger_unchanged: true, executions: 0, rejected_status: 422,
    answer_count: 1, adopted: false });
  expect(output.model_risk_available).toBe(!returnOnly);
  expect(output.table_counts["operations.sqlite3"]).toBeGreaterThan(0);
  expect(output.table_counts["mobile.sqlite3"]).toBeGreaterThan(0);
  // Numerical comparison uses the existing portable tolerance. Original
  // architecture-specific Pandas source hashes and dependent lineage IDs are
  // independently validated by production code, not rewritten for equality.
  function parity(actual: unknown, expected: unknown): void {
    if (typeof expected === "number") {
      expect(typeof actual).toBe("number");
      expect(Math.abs(Number(actual) - expected)).toBeLessThanOrEqual(1e-7 + 1e-6 * Math.abs(expected));
    } else if (Array.isArray(expected)) {
      expect(Array.isArray(actual)).toBe(true);
      const values = actual as unknown[];
      expect(values).toHaveLength(expected.length);
      expected.forEach((value, index) => parity(values[index], value));
    } else if (expected !== null && typeof expected === "object") {
      const values = actual as Record<string, unknown>;
      expect(values).not.toBeNull();
      expect(Object.keys(values).sort()).toEqual(Object.keys(expected).sort());
      for (const [key, value] of Object.entries(expected)) parity(values[key], value);
    } else expect(actual).toEqual(expected);
  }
  parity(output.predictions, fixture.predictions.map((value: Record<string, unknown>) => ({
    ...value, data_snapshot_id: fixture.wasm_data_snapshot_id,
  })));
  const lineage = new Set(["proposal_id", "daily_audit", "personal_guard"]);
  const numerical = (value: Record<string, unknown>) => Object.fromEntries(Object.entries(value).filter(([key]) => !lineage.has(key)));
  if (returnOnly) expect(output.proposal).toBeNull();
  else parity(numerical(output.proposal!), numerical(fixture.proposal));
  const source = JSON.parse(readFileSync(new URL("../../.demo-artifacts/android/mobile-golden.json", import.meta.url), "utf-8")).received_forecast;
  const expectedLines = source.proposal.lines as { symbol: string; recommended_shares: number; transaction_cost: Record<string, string> }[];
  let expectedCost = 0;
  for (const line of output.manual_review.lines) {
    const reference = expectedLines.find(x => x.symbol === line.symbol)!;
    expect(line.target_shares).toBe(reference.recommended_shares);
    expectedCost += ["commission", "spread", "slippage", "market_impact"].reduce((total, key) => total + Number(reference.transaction_cost[key]), 0);
  }
  expect(expectedCost).toBeGreaterThan(0);
  parity(Number(output.manual_review.estimated_cost_yen), expectedCost);
  expect(external).toEqual([]);
});

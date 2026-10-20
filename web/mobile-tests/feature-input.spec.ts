import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

for (const native of [false, true]) test(`initial-history DataFrames match records precision, PC features and restored source identity (native bytes: ${native})`, async ({ page, context }) => {
  const fixture = JSON.parse(readFileSync(new URL("../../.demo-artifacts/android/mobile-golden.json", import.meta.url), "utf-8")).feature_inputs;
  await context.route("https://**", route => route.abort());
  await page.route("**/feature-input-test", route => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Synthetic feature-input parity</title>" }));
  await page.goto("/feature-input-test");
  const output = await page.evaluate(async data => {
    if (data.native) {
      const initializer = new Worker("/src/mobile/compute-worker.ts", { type: "module" });
      try {
        const bytes = new TextEncoder().encode(data.state);
        if (bytes.length <= 2 * 1024 * 1024) throw new Error("multi-chunk fixture required");
        const restored = await new Promise<{ state: string; error?: string }>((resolve, reject) => {
          initializer.onmessage = event => resolve(event.data);
          initializer.onerror = event => reject(new Error(event.message));
          initializer.postMessage({ id: 1, command: "initialize", state_bytes: bytes.buffer }, [bytes.buffer]);
          if (bytes.byteLength !== 0) reject(new Error("native input ownership was not transferred"));
        });
        if (restored.error || typeof restored.state !== "string") throw new Error(restored.error || "state missing");
        data.state = restored.state;
      } finally { initializer.terminate(); }
    }
    const worker = new Worker("/mobile-tests/feature-input-worker.ts", { type: "module" });
    try {
      return await new Promise<{ error?: string; records_exact: boolean; source_unchanged: boolean; restored_exact: boolean; model_count: number; legacy_source_ids_exact: boolean; pc_source_ids_exact: boolean; latest_closed_price_rows: number; na_hash: number; source_ids: string[][]; daily_rows: number; result: { as_of: string; features: Record<string, Record<string, unknown>[]> } }>((resolve, reject) => {
        worker.onmessage = event => resolve(event.data);
        worker.onerror = event => reject(new Error(event.message));
        worker.postMessage(data);
      });
    } finally { worker.terminate(); }
  }, { ...fixture, native });
  expect(output.error).toBeUndefined();
  expect(output).toMatchObject({ records_exact: true, source_unchanged: true, restored_exact: true, model_count: 0, daily_rows: 1080 });
  expect(output.legacy_source_ids_exact).toBe(true);
  expect(output.pc_source_ids_exact).toBe(true);
  expect(output.latest_closed_price_rows).toBe(4);
  expect(output.na_hash).toBe(fixture.wasm_na_hash);
  expect(output.source_ids).toEqual(fixture.source_ids);
  expect(output.result.as_of).toBe(fixture.cutoff);
  for (const horizon of ["5", "20"]) {
    expect(output.result.features[horizon]).toHaveLength(4);
    output.result.features[horizon].forEach((row, index) => {
      const reference = fixture.expected.features[horizon][index];
      expect(Object.keys(row)).toEqual(Object.keys(reference));
      for (const [name, value] of Object.entries(reference)) {
        if (typeof value === "number") expect(Number(row[name])).toBeCloseTo(value, 7);
        else expect(row[name]).toEqual(value);
      }
    });
  }
});

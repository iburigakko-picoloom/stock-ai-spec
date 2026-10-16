import { readFileSync } from "node:fs";
import { test, expect } from "@playwright/test";

test("offline Python preserves input and matches PC features, nine model vectors and four-head bundle", async ({ page, context }) => {
  const golden = JSON.parse(readFileSync(new URL("../../.demo-artifacts/android/mobile-golden.json", import.meta.url), "utf-8"));
  await context.route("https://**", route => route.abort());
  await page.route("**/mobile-test", route => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Offline runtime verification</title>" }));
  await page.goto("/mobile-test");
  const result = await page.evaluate(async (input) => {
    let worker = new Worker("/src/mobile/compute-worker.ts", { type: "module" });
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
    const membership = await send({ command: "request", method: "GET", path: "/api/v1/mobile/market/membership" });
    const universe = await send({ command: "request", method: "GET", path: "/api/v1/mobile/market/current-universe" });
    const values = await send({ command: "request", method: "POST", path: "/api/v1/mobile/features", body: JSON.stringify(input.inputs) });
    const insufficient = await send({ command: "request", method: "POST", path: "/api/v1/mobile/features", body: JSON.stringify({ ...input.inputs, daily: input.inputs.daily.slice(-4) }) });
    const models = [];
    for (const vector of input.models) {
      models.push(await send({ command: "request", method: "POST", path: "/api/v1/mobile/models/parity", body: JSON.stringify({ model: vector.model, rows: vector.rows }) }));
    }
    const bundle = await send({ command: "request", method: "POST", path: "/api/v1/mobile/models/bundle/parity", body: JSON.stringify({ content: input.bundle.content, rows: input.bundle.rows }) });
    const bundleStatus = await send({ command: "request", method: "GET", path: "/api/v1/mobile/models" });
    const daily = await send({ command: "request", method: "GET", path: "/api/v1/mobile/daily" });
    const portfolio = { schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: null, maximum_drawdown_percent: null, accounts: [], holdings: [] };
    const saved = await send({ command: "request", method: "POST", path: "/api/v1/mobile/portfolio", body: JSON.stringify(portfolio) });
    worker.terminate();
    worker = new Worker("/src/mobile/compute-worker.ts", { type: "module" });
    await send({ command: "initialize", state: saved.state });
    const restored = await send({ command: "request", method: "GET", path: "/api/v1/mobile/portfolio" });
    worker.terminate();
    return { health, membership, universe, values, saved, models, bundle, bundleStatus, daily, insufficient, restored };
  }, { inputs: golden.inputs, models: golden.models, bundle: golden.bundle });
  expect(result.health.result).toMatchObject({ status: 200, body: { orderSubmissionAvailable: false } });
  expect(result.membership.result).toMatchObject({ status: 200, body: { available_at_cutoff: false } });
  expect(result.universe.result).toMatchObject({ status: 200, body: { blocking_reasons: ["current_membership_missing"], holdings_recorded: false } });
  expect(result.saved.result).toMatchObject({ status: 200, body: { portfolio: { holdings_status: "none", investment_budget_yen: null } } });
  expect(result.saved.state).toBeTruthy();
  expect(result.insufficient.result).toMatchObject({ status: 422 });
  expect(result.restored.result).toEqual(result.saved.result);
  expect(result.models).toHaveLength(9);
  expect(result.bundleStatus.result).toMatchObject({ status: 200, body: { imported_bundle_count: 0, bundle_ready: false, model_adopted: false } });
  expect(result.daily.result).toEqual({ status: 200, body: null });
  const probe = result.bundle.result as { status: number; body: { heads: { horizon: number; task: string; values: number[] }[] } };
  expect(result.bundle.result).toMatchObject({ status: 200, body: { bundle_id: golden.bundle.bundle_id, sha256: golden.bundle.sha256, persisted: false, research_only: true, model_adopted: false } });
  expect(probe.body.heads).toHaveLength(4);
  probe.body.heads.forEach((head, index) => {
    const expected = golden.bundle.expected[index];
    expect([head.horizon, head.task]).toEqual([expected.horizon, expected.task]);
    expect(head.values).toHaveLength(expected.values.length);
    head.values.forEach((value, row) => {
      expect(Math.abs(value - expected.values[row])).toBeLessThanOrEqual(1e-7 + 1e-6 * Math.abs(expected.values[row]));
    });
  });
  result.models.forEach((reply, index) => {
    const computed = reply.result as { status: number; body: { values: number[]; research_only: boolean; model_adopted: boolean } };
    expect(computed.status).toBe(200);
    expect(computed.body.research_only).toBe(true);
    expect(computed.body.model_adopted).toBe(false);
    computed.body.values.forEach((value, row) => {
      const reference = golden.models[index].expected[row];
      expect(Math.abs(value - reference)).toBeLessThanOrEqual(1e-7 + 1e-6 * Math.abs(reference));
    });
  });
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

test("offline personal settings compile and confirmed balances survive a new interpreter", async ({ page, context }) => {
  await context.route("https://**", route => route.abort());
  await page.route("**/mobile-personal-test", route => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Offline personal account verification</title>" }));
  await page.goto("/mobile-personal-test");
  const result = await page.evaluate(async () => {
    let worker = new Worker("/src/mobile/compute-worker.ts", { type: "module" });
    let sequence = 0;
    type Reply = { state: string; result: { status: number; body: Record<string, unknown> } };
    async function send(value: Record<string, unknown>): Promise<Reply> {
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
    async function request(method: string, path: string, body?: unknown) {
      return send({ command: "request", method, path, body: JSON.stringify(body ?? null) });
    }
    await send({ command: "initialize", state: "" });
    const account = "11111111-1111-4111-8111-111111111111";
    const profile = { schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: "200000",
      maximum_drawdown_percent: 20, accounts: [{ id: account, name: "Synthetic account", account_type: "taxable_specified",
        withholding_mode: "withholding", available_cash_yen: "1000.0001" }], holdings: [] };
    const saved = await request("POST", "/api/v1/mobile/portfolio", { expected_revision_id: null, portfolio: profile });
    const settings = { schema_version: "manual-personal-settings-v1", portfolio_revision_id: saved.result.body.revision_id,
      cash_basis: "deployable_after_reserved", budget_basis: "maximum_total_equity_market_value",
      nisa_capacity_basis: "remaining_purchase_notional_no_same_day_sale_restore", tax_year: new Date(Date.now() + 9 * 3600000).getUTCFullYear(),
      accounts: [{ account_id: account, reserved_cash_yen: "100", pending_activity: "none", realized_gain_ytd: "0",
        realized_loss_ytd: "0", loss_carryforward_user_input: "0", nisa_annual_capacity_user_input: null, nisa_lifetime_capacity_user_input: null }],
      cost_assumptions: { commission_fixed_yen: "0", commission_bps: "0", minimum_commission_yen: "0", zero_commission_confirmed: true,
        full_spread_bps: "10", slippage_bps: "5", impact_bps_at_full_adv: "25" },
      tax_assumptions: { effective_from: "2020-01-01", taxable_rate_percent: "20", nisa_opportunity_cost_percent: "0" },
      research_decision_policy: "daily-decision-engine-v2", research_conditions_reviewed: true };
    const extra = await request("POST", "/api/v1/mobile/personal/settings", { expected_revision_id: null, settings });
    const preview = await request("POST", "/api/v1/mobile/personal/initial/preview", {});
    const refused = await request("POST", "/api/v1/mobile/personal/initial/confirm", { preview_id: preview.result.body.preview_id, confirmed: false });
    const applied = await request("POST", "/api/v1/mobile/personal/initial/confirm", { preview_id: preview.result.body.preview_id, confirmed: true });
    const home = await request("GET", "/api/v1/home");
    worker.terminate();
    worker = new Worker("/src/mobile/compute-worker.ts", { type: "module" });
    await send({ command: "initialize", state: applied.state });
    const restored = await request("GET", "/api/v1/home");
    const restoredExtra = await request("GET", "/api/v1/mobile/personal/settings");
    const ready = await request("GET", "/api/v1/mobile/personal/readiness");
    worker.terminate();
    return { extra, preview, refused, applied, home, restored, restoredExtra, ready };
  });
  expect(result.extra.result.status).toBe(200);
  expect(result.preview.result.body.blocking_reasons).toEqual([]);
  expect(result.refused.result.status).toBe(422);
  expect(result.applied.result.status).toBe(200);
  expect(result.home.result.body).toMatchObject({ portfolio: { cashValue: "1100.0001", equityValue: "0", holdingsCount: 0 }, initialLedger: { referencePriceDate: null } });
  expect(result.restored.result.body).toEqual(result.home.result.body);
  expect(result.restoredExtra.result.body).toEqual(result.extra.result.body);
  expect(result.ready.result.body).toMatchObject({ input_gaps: [], comparison: { proposal: null, research_only: true } });
});

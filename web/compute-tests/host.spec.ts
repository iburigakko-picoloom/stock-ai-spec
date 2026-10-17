import { expect, test } from "@playwright/test";

test("production compute entry boots offline under the native CSP and returns durable state", async ({ page, context }) => {
  await context.route("https://**", route => route.abort());
  await page.route("**/compute.html", async route => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), "Content-Security-Policy": "default-src 'none'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; worker-src 'self' blob:; connect-src 'self'; frame-src 'none'; base-uri 'none'; form-action 'none'" } });
  });
  await page.addInitScript(() => {
    const host = window as unknown as { StockAICompute: unknown; ready: boolean; replies: Record<string, unknown> };
    host.replies = {}; host.ready = false;
    host.StockAICompute = { ready: () => { host.ready = true; }, complete: (id: string, payload: string) => { host.replies[id] = JSON.parse(payload); } };
  });
  await page.goto("/compute.html");
  await expect.poll(() => page.evaluate(() => (window as unknown as { ready: boolean }).ready)).toBe(true);
  async function send(id: number, command: Record<string, unknown>): Promise<{ error?: string; state: string | null; result: { status: number; body: { orderSubmissionAvailable?: boolean; portfolio?: { holdings_status: string } } } | null }> {
    await page.evaluate(value => (window as unknown as { stockAICompute: (input: unknown) => void }).stockAICompute(value), { ...command, id });
    await expect.poll(() => page.evaluate(key => Boolean((window as unknown as { replies: Record<string, unknown> }).replies[key]), String(id)), { timeout: 120_000 }).toBe(true);
    return page.evaluate(key => (window as unknown as { replies: Record<string, never> }).replies[key], String(id));
  }
  const initialized = await send(1, { command: "initialize", state: "" });
  expect(initialized.error).toBeUndefined();
  expect(initialized.state).toBeTruthy();
  const health = await send(2, { command: "request", method: "GET", path: "/api/v1/health" });
  expect(health.result).toMatchObject({ status: 200, body: { orderSubmissionAvailable: false } });
  expect(health.state).toBeNull();
  const saved = await send(3, { command: "request", method: "POST", path: "/api/v1/mobile/portfolio", body: JSON.stringify({ schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: null, maximum_drawdown_percent: null, accounts: [], holdings: [] }) });
  expect(saved.error).toBeUndefined();
  expect(saved.result).toMatchObject({ status: 200, body: { portfolio: { holdings_status: "none" } } });
  expect(saved.state).toBeTruthy();
  const invalid = await send(4, { command: "request", method: "POST", path: "/api/v1/mobile/portfolio", body: "{" });
  expect(invalid.result?.status).toBe(422);
  expect(invalid.state).toBeTruthy();
  const afterFailure = await send(5, { command: "request", method: "GET", path: "/api/v1/mobile/portfolio" });
  expect(afterFailure.result).toEqual(saved.result);
  expect(afterFailure.state).toBeNull();
});

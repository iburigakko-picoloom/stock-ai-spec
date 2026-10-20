import { expect, test } from "@playwright/test";

// Actual Android settings route with an isolated, synthetic native bridge.
// No interpreter, credential store, provider request or personal database is used.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const calls: { plugin: string; method: string; operation?: string }[] = [];
    Object.assign(window, {
      __settingsCalls: calls,
      CapacitorCustomPlatform: { name: "android" },
      Capacitor: {
        PluginHeaders: [
          { name: "StockAI", methods: ["compute", "keyStatus", "checkUpdate", "dailyStatus", "saveApiKey", "clearApiKey"].map(name => ({ name, rtype: "promise" })) },
          { name: "StockAIChatGPT", methods: [{ name: "getStatus", rtype: "promise" }] },
        ],
        nativePromise: async (plugin: string, method: string, options?: { method: string; path: string }) => {
          calls.push({ plugin, method, operation: options?.method });
          if (method === "compute") return { status: 200, body: await (await fetch(options!.path)).json() };
          if (method === "keyStatus") return { configured: false };
          if (method === "checkUpdate") return { available: false };
          if (method === "dailyStatus") return { enabled: false, state: "idle", notificationsEnabled: false };
          if (method === "getStatus") return { connected: false, planEnabled: false, selection: { model: "", effort: "medium" }, models: [] };
          if (method === "saveApiKey") return new Promise<void>(resolve => Object.assign(window, { __finishSettingsSave: resolve }));
          throw new Error(`Unexpected native operation: ${plugin}.${method}`);
        },
      },
    });
  });
  const profile = { revision_id: "a".repeat(64), saved_at: "2026-10-20T09:00:00+09:00", portfolio: {
    schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: null,
    maximum_drawdown_percent: null, accounts: [], holdings: [],
  } };
  const payloads: Record<string, unknown> = {
    "/api/v1/settings": { runtimeMode: "TEST", data: {}, runtime: {} },
    "/api/v1/mobile/portfolio": profile,
    "/api/v1/mobile/market": { latest_data_date: null, completed_dates: [] },
    "/api/v1/mobile/market/plan": { first_day: "2024-10-20", last_day: "2026-10-19" },
    "/api/v1/mobile/market/membership": { available_at_cutoff: false },
    "/api/v1/mobile/market/universe-policy": { mode: "legacy300", experimental: false },
    "/api/v1/mobile/models": { approved_bundle_count: 0, imported_bundle_count: 0, bundle_ready: false, model_adopted: false },
    "/api/v1/mobile/daily": null,
    "/api/v1/mobile/decision": null,
    "/api/v1/mobile/personal/settings": { saved: null, current_portfolio: profile },
    "/api/v1/mobile/personal/readiness": { input_gaps: ["accounts"], initial_ledger: {
      blocking_reasons: ["accounts"], prices: { date: null, prices: {} }, portfolio: null,
    }, comparison: { blocking_reasons: [{ code: "FORECAST_MISSING" }], research_only: true } },
  };
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (!(path in payloads)) throw new Error(`Unexpected fixture API: ${path}`);
    return route.fulfill({ json: payloads[path] });
  });
  await page.goto("/#/settings");
  await expect(page.getByRole("heading", { name: "設定", exact: true })).toBeVisible();
});

for (const width of [320, 390]) for (const font of [100, 150]) {
  test(`Android settings stay compact and separated at ${width}px / ${font}%`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 844 });
    await page.addStyleTag({ content: `html { font-size: ${font}%; }` });
    const groups = page.locator(".settings-group");
    await expect(groups).toHaveCount(7);
    await expect(page.locator(".device-settings input:visible, .device-settings select:visible, .device-settings button:visible")).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "口座・資金" })).toHaveCount(0);
    await page.screenshot({ path: info.outputPath(`settings-${width}-${font}.png`), fullPage: true });

    const account = groups.filter({ has: page.locator("summary > span > strong", { hasText: /^口座・保有$/ }) });
    await account.locator(":scope > summary").click();
    await page.getByLabel("投資上限（円・未定は空欄）").fill("1234567");
    await account.locator(":scope > summary").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByLabel("投資上限（円・未定は空欄）")).not.toBeVisible();
    await page.keyboard.press("Space");
    await expect(page.getByLabel("投資上限（円・未定は空欄）")).toHaveValue("1234567");

    for (const group of await groups.all()) {
      await group.evaluate(node => { (node as HTMLDetailsElement).open = true; });
    }
    for (const detail of await page.locator(".device-settings details:not(.settings-group)").all()) {
      await detail.evaluate(node => { (node as HTMLDetailsElement).open = true; });
    }
    await expect(page.getByRole("button", { name: "APIキーを保存" })).toBeVisible();
    await expect(page.getByRole("button", { name: "口座・保有を保存" })).toBeVisible();
    await expect(page.getByRole("button", { name: "このバックアップに復元" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "手動でChatGPTに相談" })).toHaveAttribute("href", "#/today/chatgpt");
    const controls = await page.locator(".device-settings button:visible, .device-settings a.button:visible").evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect(); return { height: box.height, top: box.top, bottom: box.bottom };
    }));
    for (let i = 0; i < controls.length; i++) {
      expect(controls[i].height).toBeGreaterThanOrEqual(48);
      if (i > 0) expect(controls[i].top - controls[i - 1].bottom).toBeGreaterThanOrEqual(12);
    }
    for (const summary of await groups.locator(":scope > summary").all()) expect((await summary.boundingBox())!.height).toBeGreaterThanOrEqual(48);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await account.screenshot({ path: info.outputPath(`account-${width}-${font}.png`) });
    const calls = await page.evaluate(() => (window as unknown as { __settingsCalls: { method: string; operation?: string }[] }).__settingsCalls);
    expect(calls.every(call => ["compute", "keyStatus", "checkUpdate", "dailyStatus", "getStatus"].includes(call.method) && (!call.operation || call.operation === "GET"))).toBe(true);
  });
}

test("collapsing an active API-key save preserves the pending action and its feedback", async ({ page }) => {
  const group = page.locator(".settings-group").filter({ has: page.locator("summary > span > strong", { hasText: /^市場データ$/ }) });
  await group.locator(":scope > summary").click();
  await page.getByLabel("J-Quants APIキー", { exact: true }).fill("synthetic-ui-test-key");
  await page.getByRole("button", { name: "APIキーを保存" }).click();
  await group.locator(":scope > summary").click();
  await expect(page.getByText("端末内で処理しています…", { exact: true })).toBeVisible();
  await group.locator(":scope > summary").click();
  await expect(page.getByRole("button", { name: "APIキーを保存" })).toBeDisabled();
  await page.evaluate(() => (window as unknown as { __finishSettingsSave: () => void }).__finishSettingsSave());
  await expect(page.getByText("APIキーを端末に暗号化保存しました。")).toBeVisible();
  await expect(page.getByLabel("J-Quants APIキー", { exact: true })).toHaveValue("");
  expect(await page.evaluate(() => (window as unknown as { __settingsCalls: { method: string }[] }).__settingsCalls.filter(x => x.method === "saveApiKey").length)).toBe(1);
});

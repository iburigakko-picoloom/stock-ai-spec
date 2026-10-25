import { expect, test } from "@playwright/test";
import type { PersonalSettings } from "../src/mobile/personal";

// Actual Android settings route with an isolated, synthetic native bridge.
// No interpreter, credential store, provider request or personal database is used.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const calls: { plugin: string; method: string; operation?: string }[] = [];
    let dailyStatus = { enabled: true, state: "waiting_cutoff", notificationsEnabled: true };
    Object.assign(window, {
      __settingsCalls: calls,
      CapacitorCustomPlatform: { name: "android" },
      Capacitor: {
        PluginHeaders: [
          { name: "StockAI", methods: ["compute", "keyStatus", "checkUpdate", "installUpdate", "dailyStatus", "saveApiKey", "clearApiKey", "stopDaily", "startDaily", "requestDailyNotifications"].map(name => ({ name, rtype: "promise" })) },
          { name: "StockAIChatGPT", methods: [{ name: "getStatus", rtype: "promise" }] },
        ],
        nativePromise: async (plugin: string, method: string, options?: { method: string; path: string; body?: string }) => {
          calls.push({ plugin, method, operation: options?.method });
          if (method === "compute") return { status: 200, body: await (await fetch(options!.path, {
            method: options!.method, headers: { "Content-Type": "application/json" }, body: options!.method === "POST" ? options!.body : undefined,
          })).json() };
          if (method === "keyStatus") return { configured: localStorage.getItem("settingsTestKey") !== "missing" };
          if (method === "checkUpdate") return localStorage.getItem("settingsTestUpdate") === "available" ? {
            available: true, versionName: "0.1.27-candidate", versionCode: 10027,
            notes: "試験用の長い変更内容です。".repeat(80), sha256: "a".repeat(64), url: "https://example.invalid/StockAI.apk", size: 123,
          } : { available: false };
          if (method === "installUpdate") return { needsPermission: true };
          if (method === "dailyStatus") return { ...dailyStatus, state: localStorage.getItem("settingsTestDailyState") ?? dailyStatus.state };
          if (method === "requestDailyNotifications") return { granted: dailyStatus.notificationsEnabled };
          if (method === "startDaily") return (dailyStatus = { ...dailyStatus, enabled: true, state: "queued" });
          if (method === "stopDaily") {
            if ((window as unknown as { __failSettingsStop?: boolean }).__failSettingsStop) throw new Error("合成停止エラー");
            return new Promise(resolve => Object.assign(window, { __finishSettingsStop: () => {
              dailyStatus = { ...dailyStatus, enabled: false, state: "paused" }; resolve(dailyStatus);
            } }));
          }
          if (method === "getStatus") return { connected: false, planEnabled: false, selection: { model: "", effort: "medium" }, models: [] };
          if (method === "saveApiKey") return new Promise<void>(resolve => Object.assign(window, { __finishSettingsSave: resolve }));
          throw new Error(`Unexpected native operation: ${plugin}.${method}`);
        },
      },
    });
  });
  const profile = { revision_id: "a".repeat(64), saved_at: "2026-10-20T09:00:00+09:00", portfolio: {
    schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: "500000",
    maximum_drawdown_percent: 10, accounts: [{ id: "synthetic-account", name: "試験用口座", account_type: "taxable_specified", withholding_mode: "withholding", available_cash_yen: "500000" }], holdings: [],
  } };
  const payloads: Record<string, unknown> = {
    "/api/v1/settings": { runtimeMode: "TEST", data: {}, runtime: {} },
    "/api/v1/mobile/portfolio": profile,
    "/api/v1/mobile/personal/current": { ledger: null, profile, settings: null },
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
    if (route.request().method() !== "GET") throw new Error("Unexpected write in read-only settings fixture");
    const path = new URL(route.request().url()).pathname;
    if (!(path in payloads)) throw new Error(`Unexpected fixture API: ${path}`);
    return route.fulfill({ json: payloads[path] });
  });
  await page.goto("/#/settings");
  await expect(page.getByRole("heading", { name: "設定", exact: true })).toBeVisible();
});

for (const width of [320, 390]) test(`reference analysis from Today at ${width}px`, async ({ page }, info) => {
  let saved = false;
  await page.route("**/api/v1/today", route => route.fulfill({ json: {
    businessDate: "2026-10-24", pipelineState: "BLOCKED", isStale: true,
    blockingReason: "NUMERICAL_FORECAST_INCOMPLETE", runtimeMode: "RESEARCH", proposal: null,
    savedAnalysis: saved ? { snapshotId: "synthetic-reference", asOf: "2026-10-24T23:00:00+09:00",
      generatedAt: "2026-10-24T23:00:00+09:00", dataAsOf: "2026-10-24T22:00:00+09:00",
      modelVersion: "mobile-bundle:" + "a".repeat(64), readOnly: true, holdingSymbols: ["1234"],
      analysisKind: "latest_available_reference", priceDate: "2026-10-23",
      predictions: [{ symbol: "1234", expected_return_5d: .01, expected_return_20d: .02, rank_score_20d: .8 }] } : null,
  } }));
  await page.route("**/api/v1/mobile/daily/generate", route => {
    expect(route.request().postDataJSON()).toEqual({ reference_only: true });
    saved = true;
    return route.fulfill({ json: { phase: "reference_saved", blocking_reasons: [] } });
  });
  await page.setViewportSize({ width, height: 844 });
  await page.evaluate(() => { localStorage.setItem("settingsTestDailyState", "closed"); document.documentElement.style.fontSize = "150%"; });
  await page.goto("/#/today");
  await page.getByRole("button", { name: "最新データで分析する" }).click();
  await expect(page.getByRole("heading", { name: "2026-10-23の終値による参考分析" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "提案を表示できない理由" })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({ path: info.outputPath(`reference-${width}.png`), fullPage: true });
});

for (const width of [320, 390]) test(`daily calculation stage at ${width}px with large text`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 844 });
  await page.evaluate(() => localStorage.setItem("settingsTestDailyState", "calculating"));
  await page.goto("/#/settings?edit=daily");
  await page.evaluate(() => { document.documentElement.style.fontSize = "150%"; window.dispatchEvent(new Event("focus")); });
  const progress = page.getByRole("progressbar", { name: "数値計算の完了工程" });
  await expect(progress).toHaveAttribute("value", "1");
  expect((await progress.boundingBox())!.width).toBeGreaterThan(width * .7);
  await expect(page.getByText("予測を計算しています", { exact: true })).toBeVisible();
  await expect(page.getByText("工程2/3：予測計算・保存")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({ path: info.outputPath(`calculation-${width}.png`), fullPage: true });
  await page.evaluate(() => { localStorage.setItem("settingsTestDailyState", "compute_wait"); window.dispatchEvent(new Event("focus")); });
  await expect(progress).toHaveCount(0);
  await expect(page.getByText("Androidの計算待ち・アプリで保存状態を確認してください")).toBeVisible();
});

test("SBI simple setup saves explicit confirmations without typing supplemental amounts", async ({ page }, info) => {
  let received: { settings: PersonalSettings } | undefined;
  await page.route("**/api/v1/mobile/personal/settings", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    received = route.request().postDataJSON();
    await route.fulfill({ json: { saved: { revision_id: "b".repeat(64), saved_at: "2026-10-24T10:00:00Z", settings: received!.settings } } });
  });
  await page.setViewportSize({ width: 320, height: 844 });
  await page.evaluate(() => document.documentElement.style.fontSize = "150%");
  await page.getByRole("button", { name: /^証券口座/ }).click();
  await page.getByRole("button", { name: /^取引の確認/ }).click();
  await page.getByRole("button", { name: "標準の計算条件を使う" }).click();
  await page.getByLabel("国内株式の「ゼロ革命」").selectOption("free");
  await page.getByLabel("口座・保有に入力した現金額").selectOption("deployable_after_reserved");
  await page.getByLabel("注文用・出金用などに確保している現金").selectOption("none");
  await page.getByLabel("残高に未反映の売買・入出金や、未決済の取引").selectOption("none");
  await page.getByLabel("今年の売却による利益・損失").selectOption("none");
  await page.getByLabel("前年以前から繰り越して使う損失").selectOption("none");
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await page.getByRole("button", { name: "補足設定を保存", exact: true }).click();
  await expect(page.getByText("保存しました。", { exact: true })).toBeVisible();
  expect(received!.settings).toMatchObject({ cash_basis: "deployable_after_reserved", budget_basis: "maximum_total_equity_market_value", research_conditions_reviewed: true,
    accounts: [{ reserved_cash_yen: "0", pending_activity: "none", realized_gain_ytd: "0", realized_loss_ytd: "0", loss_carryforward_user_input: "0", nisa_annual_capacity_user_input: null }],
    cost_assumptions: { zero_commission_confirmed: true, commission_fixed_yen: "0", full_spread_bps: "10" }, tax_assumptions: { taxable_rate_percent: "20.315" } });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  await page.screenshot({ path: info.outputPath("sbi-simple-saved.png"), fullPage: true });
});

// Synthetic inset values exercise the same CSS properties injected by
// Capacitor SystemBars. Native cutout/keyboard behavior is checked separately.
for (const layout of [
  { name: "portrait notch", width: 390, height: 844, top: 48, right: 0, bottom: 24, left: 0 },
  { name: "landscape cutout", width: 844, height: 390, top: 24, right: 20, bottom: 24, left: 48 },
  { name: "native padded WebView", width: 390, height: 844, top: 0, right: 0, bottom: 0, left: 0 },
]) {
  test(`system safe area protects header, sticky update and navigation: ${layout.name}`, async ({ page }, info) => {
    await page.setViewportSize({ width: layout.width, height: layout.height });
    const setInsets = async (bottom: number) => page.evaluate(({ layout, bottom }) => {
      for (const [side, value] of Object.entries({ ...layout, bottom })) {
        if (["top", "right", "bottom", "left"].includes(side)) document.documentElement.style.setProperty(`--safe-area-inset-${side}`, `${value}px`);
      }
    }, { layout, bottom });
    // Retained tabs remain mounted but hidden. Measure the one visible header.
    const brand = page.locator(".app-brand:visible");
    await expect(brand).toHaveCount(1);
    const baseline = (await brand.boundingBox())!;
    const basePadding = await page.locator(".app-main").evaluate(node => Number.parseFloat(getComputedStyle(node).paddingBottom));
    await setInsets(layout.bottom);
    expect((await brand.boundingBox())!.y).toBe(baseline.y + layout.top);
    const safeBrand = (await brand.boundingBox())!;
    expect(safeBrand.x).toBeGreaterThanOrEqual(layout.left);
    expect(safeBrand.x + safeBrand.width).toBeLessThanOrEqual(layout.width - layout.right);
    if (layout.width <= 800) expect(safeBrand.x).toBe(baseline.x + layout.left);
    await page.evaluate(() => localStorage.setItem("settingsTestUpdate", "available"));
    await page.reload();
    await setInsets(layout.bottom);
    const banner = page.getByRole("region", { name: "アプリの更新" });
    await expect(banner).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, 600));
    expect((await banner.boundingBox())!.y).toBe(layout.top);
    const button = (await banner.getByRole("button", { name: "更新", exact: true }).boundingBox())!;
    expect(button.y).toBeGreaterThanOrEqual(layout.top);
    expect(button.x + button.width).toBeLessThanOrEqual(layout.width - layout.right);
    const links = page.getByRole("navigation", { name: "メインナビゲーション" }).getByRole("link");
    const first = (await links.first().boundingBox())!;
    const last = (await links.last().boundingBox())!;
    expect(first.x).toBeGreaterThanOrEqual(layout.left);
    expect(last.x + last.width).toBeLessThanOrEqual(layout.width - layout.right);
    expect(last.y + last.height).toBeLessThanOrEqual(layout.height - layout.bottom);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(layout.width);
    const cover = await page.locator(".app-shell").evaluate(node => {
      const style = getComputedStyle(node, "::before");
      return { height: Number.parseFloat(style.height), position: style.position, pointerEvents: style.pointerEvents };
    });
    expect(cover).toEqual({ height: layout.top, position: "fixed", pointerEvents: "none" });
    await page.screenshot({ path: info.outputPath(`safe-area-${layout.name}.png`) });
    // SystemBars changes the bottom value when the keyboard becomes visible.
    // Reuse the updated value immediately, without adding a second inset.
    await setInsets(0);
    const mainPadding = await page.locator(".app-main").evaluate(node => getComputedStyle(node).paddingBottom);
    expect(Number.parseFloat(mainPadding)).toBeCloseTo(basePadding, 2);
    await setInsets(layout.bottom);
    expect(await page.locator(".app-main").evaluate(node => Number.parseFloat(getComputedStyle(node).paddingBottom))).toBeCloseTo(basePadding + layout.bottom, 2);
  });
}

for (const width of [320, 390]) for (const font of [100, 150]) {
  test(`blue settings and compact top update notice at ${width}px / ${font}%`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 844 });
    await page.evaluate(() => localStorage.setItem("settingsTestUpdate", "available"));
    await page.reload();
    await expect(page.getByRole("region", { name: "アプリの更新" })).toBeVisible();
    await page.addStyleTag({ content: `html { font-size: ${font}%; }` });
    const banner = page.getByRole("region", { name: "アプリの更新" });
    await expect(banner.getByText("新しいバージョンがあります")).toBeVisible();
    await expect(banner.locator("details p")).not.toBeVisible();
    const metrics = await page.evaluate(() => {
      const banner = document.querySelector(".app-update")!;
      const button = banner.querySelector("button")!.getBoundingClientRect();
      const summary = banner.querySelector("summary")!.getBoundingClientRect();
      return { top: banner.getBoundingClientRect().top, height: banner.getBoundingClientRect().height,
        beforeBrand: !!(banner.compareDocumentPosition(document.querySelector(".app-brand")!) & Node.DOCUMENT_POSITION_FOLLOWING),
        width: document.documentElement.scrollWidth, buttonHeight: button.height, summaryHeight: summary.height, gap: summary.top - button.bottom,
        brand: getComputedStyle(document.querySelector(".brand-mark")!).color,
        icon: getComputedStyle(document.querySelector(".settings-menu-icon")!).stroke,
        toggle: getComputedStyle(document.querySelector(".settings-switch--on")!).backgroundColor,
      };
    });
    expect(metrics.top).toBe(0); expect(metrics.beforeBrand).toBe(true);
    expect(metrics.height).toBeLessThan(220); expect(metrics.width).toBeLessThanOrEqual(width);
    expect(metrics.buttonHeight).toBeGreaterThanOrEqual(48); expect(metrics.summaryHeight).toBeGreaterThanOrEqual(48);
    expect(metrics.gap).toBeGreaterThanOrEqual(12);
    expect(metrics.brand).toBe("rgb(16, 35, 71)"); expect(metrics.icon).toBe("rgb(8, 102, 229)"); expect(metrics.toggle).toBe(metrics.icon);
    const calls = await page.evaluate(() => (window as unknown as { __settingsCalls: { method: string }[] }).__settingsCalls);
    expect(calls.some(x => x.method === "installUpdate")).toBe(false);
    await page.screenshot({ path: info.outputPath(`blue-update-${width}-${font}.png`), fullPage: false });
    await page.evaluate(() => window.scrollTo(0, 600));
    await expect(banner).toBeVisible();
    expect((await banner.boundingBox())!.y).toBe(0);
    await banner.getByText("変更内容を見る").click();
    await expect(banner.locator("details p")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await banner.getByRole("button", { name: "更新", exact: true }).click();
    await expect(banner.getByRole("status")).toContainText("Androidの設定で更新を許可");
  });

  test(`Android settings stay compact and separated at ${width}px / ${font}%`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 844 });
    await page.addStyleTag({ content: `html { font-size: ${font}%; }` });
    const overview = page.locator(".settings-overview");
    await expect(overview.locator(".settings-menu-section")).toHaveCount(5);
    await expect(page.locator(".device-settings input:visible, .device-settings select:visible")).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "口座・資金" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^J-Quants API/ })).toContainText("設定済み");
    await expect(page.getByRole("button", { name: /^予測期間/ })).toContainText("5日・20日");
    await expect(page.getByRole("button", { name: /^運用資金/ })).toContainText("¥500,000");
    for (const row of await overview.locator("button").all()) expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(48);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    for (const value of await overview.locator(".settings-menu-value").all()) expect(await value.evaluate(node => node.getBoundingClientRect().height <= Number.parseFloat(getComputedStyle(node).lineHeight) + 9)).toBe(true);
    // A full-content preview keeps the fixed navigation at the bottom; the
    // interaction and overflow checks still use the normal 844px viewport.
    await page.setViewportSize({ width, height: await page.evaluate(() => document.documentElement.scrollHeight) });
    await page.screenshot({ path: info.outputPath(`settings-${width}-${font}.png`), fullPage: true });
    await page.setViewportSize({ width, height: 844 });

    await page.getByRole("button", { name: /^運用資金/ }).click();
    await expect(page.getByRole("heading", { name: "運用資金", exact: true })).toBeFocused();
    await page.getByLabel("投資上限（円・未定は空欄）").fill("1234567");
    await expect(page.getByLabel("許容する最大下落率（%・未定は空欄）")).not.toBeVisible();
    await page.getByRole("button", { name: "← 設定一覧へ" }).click();
    await expect(page.getByLabel("投資上限（円・未定は空欄）")).not.toBeVisible();
    await expect(page.getByRole("button", { name: /^運用資金/ })).toContainText("¥500,000");
    await page.getByRole("button", { name: /^運用資金/ }).focus();
    await page.keyboard.press("Space");
    await expect(page.getByLabel("投資上限（円・未定は空欄）")).toHaveValue("1234567");
    await page.goBack();

    for (const title of ["証券口座", "J-Quants API", "許容下落率", "予測期間", "完了通知", "バックアップ・復元", "ChatGPT", "アプリ情報・詳細"]) {
      await page.getByRole("button", { name: new RegExp(`^${title}`) }).click();
      for (const detail of await page.locator(".settings-edit-content:not([hidden]) details").all()) {
        await detail.evaluate(node => { (node as HTMLDetailsElement).open = true; });
      }
      const controls = await page.locator(".device-settings button.button:visible, .device-settings a.button:visible").evaluateAll(nodes => nodes.map(node => {
        const box = node.getBoundingClientRect(); return { height: box.height, top: box.top, bottom: box.bottom };
      }));
      for (let i = 0; i < controls.length; i++) {
        expect(controls[i].height).toBeGreaterThanOrEqual(48);
        if (i > 0) expect(controls[i].top - controls[i - 1].bottom).toBeGreaterThanOrEqual(12);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      if (title === "ChatGPT") await expect(page.getByRole("link", { name: "手動でChatGPTに相談" })).toHaveAttribute("href", "#/today/chatgpt");
      if (title === "証券口座") await page.screenshot({ path: info.outputPath(`account-${width}-${font}.png`), fullPage: true });
      await page.getByRole("button", { name: "← 設定一覧へ" }).click();
    }
    const calls = await page.evaluate(() => (window as unknown as { __settingsCalls: { method: string; operation?: string }[] }).__settingsCalls);
    expect(calls.every(call => ["compute", "keyStatus", "checkUpdate", "dailyStatus", "getStatus"].includes(call.method) && (!call.operation || call.operation === "GET"))).toBe(true);
  });
}

test("returning to the list during an API-key save preserves the pending action and feedback", async ({ page }) => {
  await page.getByRole("button", { name: /^J-Quants API/ }).click();
  await page.getByLabel("J-Quants APIキー", { exact: true }).fill("synthetic-ui-test-key");
  await page.getByRole("button", { name: "APIキーを保存" }).click();
  await page.getByRole("button", { name: "← 設定一覧へ" }).click();
  await expect(page.getByRole("status").filter({ hasText: "端末に保存中…" })).toBeVisible();
  await expect(page.locator(".save-progress-spinner")).toHaveCount(1);
  await page.getByRole("button", { name: /^J-Quants API/ }).click();
  await expect(page.getByRole("button", { name: "APIキーを保存" })).toBeDisabled();
  await page.evaluate(() => (window as unknown as { __finishSettingsSave: () => void }).__finishSettingsSave());
  await expect(page.getByText("APIキーを保存しました。")).toBeVisible();
  await expect(page.getByLabel("J-Quants APIキー", { exact: true })).toHaveValue("");
  expect(await page.evaluate(() => (window as unknown as { __settingsCalls: { method: string }[] }).__settingsCalls.filter(x => x.method === "saveApiKey").length)).toBe(1);
});

test("automatic-update switch waits for native acknowledgment and does not hide failures", async ({ page }) => {
  const toggle = page.getByRole("switch", { name: "営業日に自動更新" });
  await expect(toggle).toBeChecked();
  await page.evaluate(() => Object.assign(window, { __failSettingsStop: true }));
  await toggle.click();
  await expect(page.locator(".settings-overview [role=alert]")).toHaveText("合成停止エラー");
  await expect(toggle).toBeChecked();
  await page.evaluate(() => Object.assign(window, { __failSettingsStop: false }));
  await toggle.click();
  await expect(toggle).toBeChecked();
  await expect(toggle).toBeDisabled();
  await page.keyboard.press("Space");
  expect(await page.evaluate(() => (window as unknown as { __settingsCalls: { method: string }[] }).__settingsCalls.filter(x => x.method === "stopDaily").length)).toBe(2);
  await page.evaluate(() => (window as unknown as { __finishSettingsStop: () => void }).__finishSettingsStop());
  await expect(toggle).not.toBeChecked();
  await toggle.click();
  await expect(toggle).toBeChecked();
  expect(await page.evaluate(() => (window as unknown as { __settingsCalls: { method: string }[] }).__settingsCalls.filter(x => x.method === "startDaily").length)).toBe(1);
});

test("unknown settings show missing values without inventing an API connection or balances", async ({ page }) => {
  await page.evaluate(() => localStorage.setItem("settingsTestKey", "missing"));
  await page.route("**/api/v1/mobile/portfolio", route => route.fulfill({ json: null }));
  await page.reload();
  await expect(page.getByRole("button", { name: /^J-Quants API/ })).toContainText("未設定");
  await expect(page.getByRole("button", { name: /^証券口座/ })).toContainText("未登録");
  await expect(page.getByRole("button", { name: /^運用資金/ })).toContainText("未設定");
  await expect(page.getByRole("button", { name: /^許容下落率/ })).toContainText("未設定");
  await expect(page.getByText("接続済み", { exact: true })).toHaveCount(0);
});

test("saving capital keeps other editors' unsaved account changes out of the saved portfolio", async ({ page }) => {
  let received: { expected_revision_id: string; portfolio: { investment_budget_yen: string; maximum_drawdown_percent: number; accounts: { name: string; available_cash_yen: string }[]; holdings: unknown[] } } | null = null;
  await page.route("**/api/v1/mobile/portfolio", async route => {
    if (route.request().method() === "GET") return route.fallback();
    received = route.request().postDataJSON();
    return route.fulfill({ json: { revision_id: "b".repeat(64), saved_at: "2026-10-20T10:00:00+09:00", portfolio: received!.portfolio } });
  });
  await page.getByRole("button", { name: /^証券口座/ }).click();
  await page.getByRole("button", { name: /^現金・買付余力/ }).click();
  await page.getByLabel("現金入力（円）").fill("123456");
  await page.getByRole("button", { name: "← 証券口座へ" }).click();
  await page.getByRole("button", { name: "← 設定一覧へ" }).click();
  await page.getByRole("button", { name: /^運用資金/ }).click();
  await page.getByLabel("投資上限（円・未定は空欄）").fill("600000");
  await page.getByRole("button", { name: "運用資金を保存", exact: true }).click();
  await expect(page.getByText("運用資金を端末に保存しました。")).toBeVisible();
  expect(received!.expected_revision_id).toBe("a".repeat(64));
  expect(received!.portfolio.investment_budget_yen).toBe("600000");
  expect(received!.portfolio.accounts[0]).toMatchObject({ name: "試験用口座", available_cash_yen: "500000" });
  expect(received!.portfolio.maximum_drawdown_percent).toBe(10);
  expect(received!.portfolio.holdings).toEqual([]);
  await page.getByRole("button", { name: "← 設定一覧へ" }).click();
  await expect(page.getByRole("button", { name: /^運用資金/ })).toContainText("¥600,000");
  await page.getByRole("button", { name: /^証券口座/ }).click();
  await page.getByRole("button", { name: /^現金・買付余力/ }).click();
  await expect(page.getByLabel("現金入力（円）")).toHaveValue("123456");
});


for (const width of [320, 390]) {
  test(`account setup list and separate editors at ${width}px with large text`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 844 });
    await page.evaluate(() => document.documentElement.style.fontSize = "150%");
    await page.getByRole("button", { name: /^証券口座/ }).click();
    await expect(page.getByRole("button", { name: /^現金・買付余力/ })).toContainText("入力済み");
    await expect(page.getByRole("button", { name: /^取引の確認/ })).toContainText("未入力");
    await expect(page.getByRole("button", { name: /^初回残高/ })).toContainText("未登録");
    await expect(page.getByRole("textbox", { name: "口座の呼び名" })).toHaveCount(0);
    await page.screenshot({ path: info.outputPath(`account-overview-${width}.png`), fullPage: true });
    for (const title of ["現金・買付余力", "取引の確認", "初回残高"]) {
      await page.getByRole("button", { name: new RegExp(`^${title}`) }).click();
      await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await page.screenshot({ path: info.outputPath(`account-editor-${title}-${width}.png`), fullPage: true });
      await page.getByRole("button", { name: "← 証券口座へ" }).click();
    }
  });
}

for (const width of [320, 390]) test(`current balances and holdings editor at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 844 });
  await page.evaluate(() => document.documentElement.style.fontSize = "150%");
  const ledger = { portfolio_id: "synthetic-current", as_of: "2026-10-24T09:00:00Z",
    account_buckets: [{ bucket_id: "a", account_type: "taxable_specified", withholding_mode: "withholding" }],
    positions: [], cash: [{ account_bucket_id: "a", available_cash: "1040000", reserved_cash: "440000" }], tax_states: [],
  };
  await page.route("**/api/v1/mobile/personal/current", route => route.fulfill({ json: { ledger, profile: null, settings: null } }));
  await page.getByRole("button", { name: /^証券口座/ }).click();
  await page.getByRole("button", { name: /^現金・買付余力/ }).click();
  await expect(page.getByLabel("買付余力（円）")).toHaveValue("600000");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({ path: info.outputPath(`current-cash-${width}.png`), fullPage: true });
  await page.evaluate(() => { window.location.hash = "/holdings"; });
  await page.getByRole("button", { name: "保有株を追加", exact: true }).click();
  await page.getByLabel("銘柄コード").fill("7203");
  await page.getByLabel("口座区分").selectOption("new:nisa");
  await expect(page.getByRole("button", { name: "この保有を削除" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({ path: info.outputPath(`current-holdings-${width}.png`), fullPage: true });
});

import { expect, test } from "@playwright/test";

for (const width of [320, 390]) test(`market acquisition controls remain separated at ${width}px with enlarged text`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 844 });
  await page.route("**/api/v1/mobile/market", route => route.fulfill({ json: { latest_data_date: "2026-10-16", completed_dates: [] } }));
  await page.route("**/api/v1/mobile/market/plan", route => route.fulfill({ json: { first_day: "2025-08-01", last_day: "2026-10-16" } }));
  await page.route("**/api/v1/mobile/market/universe-policy", route => route.fulfill({ json: { mode: "topix500-preview", experimental: true } }));
  await page.route("**/api/v1/mobile/market/current-universe", route => route.fulfill({ json: {
    as_of: "2026-10-17T11:30:00+09:00", latest_source_date: "2026-10-16", window_dates: [],
    membership_mode: "preselected", membership_source_date: "2026-10-17", holdings_recorded: true,
    new_candidates: Array.from({ length: 493 }, (_, i) => ({ symbol: String(1000 + i), company_name: "Synthetic" })),
    decision_symbols: [...Array.from({ length: 493 }, (_, i) => String(1000 + i)), "ZZZZ"],
    held_only: ["ZZZZ"], blocking_reasons: ["held_instrument_unsupported_or_not_listed"],
    excluded: [{ symbol: "ZZZZ", reason: "HELD_INSTRUMENT_UNSUPPORTED_OR_NOT_LISTED" }],
  } }));
  await page.route("**/api/v1/mobile/market/membership", route => route.fulfill({ json: {
    date: "2026-10-17", cutoff: "2026-10-17T11:30:00+09:00", latest_received_at: null,
    available_at_cutoff: false, is_business_day: null, acquisitionId: null,
    eligible_acquisition_id: null, after_cutoff: false,
  } }));
  await page.route("**/api/v1/mobile/models", route => route.fulfill({ json: {
    approved_bundle_count: 1, imported_bundle_count: 1, bundle_ready: true, model_adopted: false,
  } }));
  await page.route("**/api/v1/mobile/decision", route => route.fulfill({ json: {
    run_id: "synthetic-decision", phase: "published", outcome: "proposal", is_active: true,
    checked_at: "2026-10-17T11:50:00+09:00", blocking_reasons: [],
  } }));
  await page.route("**/api/v1/mobile/personal/settings", route => route.fulfill({ json: {
    saved: null, current_portfolio: { revision_id: "a".repeat(64), saved_at: "2026-10-17T09:00:00+09:00",
      portfolio: { schema_version: "manual-portfolio-v1", holdings_status: "none",
        investment_budget_yen: null, maximum_drawdown_percent: null, accounts: [], holdings: [] } },
  } }));
  await page.route("**/api/v1/mobile/personal/readiness", route => route.fulfill({ json: {
    input_gaps: ["accounts"], initial_ledger: { preview_id: "c".repeat(64), blocking_reasons: ["accounts"],
      prices: { date: null, prices: {}, source_hash: null }, portfolio: null },
    comparison: { ledger_portfolio_id: null, blocking_reasons: [{ code: "FORECAST_MISSING" }], research_only: true },
  } }));
  await page.route("**/api/v1/mobile/daily", route => route.fulfill({ json: {
    run_id: "synthetic-layout", phase: "published", outcome: "forecast",
    checked_at: "2026-10-17T11:50:00+09:00", scope: { as_of: "2026-10-17T11:30:00+09:00",
      universe: { latest_source_date: "2026-10-16" } },
    snapshot: { generated_at: "2026-10-17T11:50:00+09:00", data_as_of: "2026-10-17T02:15:00Z",
      predictions: [] }, outputs: [
      { horizon: 5, task: "regression", values: [["1234", .01]] },
      { horizon: 20, task: "regression", values: [["1234", .04]] },
    ], excluded_candidates: [], blocking_reasons: [],
  } }));
  await page.goto("/mobile-tests/market-layout.html");
  await expect(page.getByRole("button", { name: "履歴の取得を開始・再開" })).toBeEnabled();
  await expect(page.getByRole("region", { name: "毎日の自動処理" }).getByRole("button", { name: "開始", exact: true })).toBeEnabled();
  await page.addStyleTag({ content: "html { font-size: 150%; }" });
  await page.getByText("取得範囲・訂正データ・計算の確認", { exact: true }).click();
  await expect(page.getByLabel("開始日", { exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "予測対象", exact: true })).toHaveValue("topix500-preview");
  await page.getByRole("button", { name: "候補と全保有の対象を確認" }).click();
  await expect(page.getByText("TOPIX500区分の493社＋対象外の保有1社＝評価対象494社")).toBeVisible();
  await expect(page.getByText("ZZZZ：対応する国内普通株として確認できません。")).toBeVisible();
  await page.getByText("算出できた予測を見る 1社", { exact: true }).click();
  await expect(page.getByRole("cell", { name: "4%" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "株数の探索方法" })).toHaveValue("daily-decision-engine-v3-bounded");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  for (const group of await page.locator(".button-stack").all()) {
    const controls = await group.locator("button:visible").evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect(); return { height: box.height, top: box.top, bottom: box.bottom };
    }));
    for (const control of controls) expect(control.height).toBeGreaterThanOrEqual(48);
    for (let i = 1; i < controls.length; i++) expect(controls[i].top - controls[i - 1].bottom).toBeGreaterThanOrEqual(12);
  }
  await expect(page.getByRole("region", { name: "毎日の自動処理" }).getByRole("button", { name: "開始", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "毎日の自動処理" }).getByRole("button", { name: "自動処理を停止", exact: true })).toHaveCount(0);
  for (const select of await page.locator("select:visible").all()) {
    expect((await select.boundingBox())!.height).toBeGreaterThanOrEqual(48);
  }
  const buttons = await page.locator("button:visible, a.button:visible").evaluateAll(nodes => nodes.map(node => {
    const box = node.getBoundingClientRect(); return { height: box.height, top: box.top, bottom: box.bottom };
  }));
  for (let i = 0; i < buttons.length; i++) {
    expect(buttons[i].height).toBeGreaterThanOrEqual(48);
    if (i > 0) expect(buttons[i].top - buttons[i - 1].bottom).toBeGreaterThanOrEqual(12);
  }
  await page.screenshot({ path: info.outputPath(`market-layout-${width}.png`), fullPage: true });
  await page.getByRole("region", { name: "毎日の自動処理" }).screenshot({ path: info.outputPath(`daily-${width}.png`) });
  await page.getByRole("region", { name: "端末内のモデルと予測" }).screenshot({ path: info.outputPath(`model-decision-${width}.png`) });
  await page.getByRole("region", { name: "補足設定と初回台帳" }).screenshot({ path: info.outputPath(`personal-policy-${width}.png`) });
  for (const [state, label] of [
    ["forecast_saved", "原予測を保存済み・株数判定待ち"],
    ["deciding", "株数を計算しています"],
    ["compute_wait", "Androidの計算待ち・アプリで保存状態を確認してください"],
    ["credentials", "APIキー・契約を確認して再開してください"],
  ]) {
    await page.goto(`/mobile-tests/market-layout.html?dailyState=${state}`);
    await page.addStyleTag({ content: "html { font-size: 150%; }" });
    const daily = page.getByRole("region", { name: "毎日の自動処理" });
    await expect(daily.getByRole("status")).toHaveText(label);
    await expect(daily.getByRole("button", { name: "自動処理を停止" })).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const boxes = await daily.locator("button:visible").evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect(); return { height: box.height, top: box.top, bottom: box.bottom };
    }));
    for (const box of boxes) expect(box.height).toBeGreaterThanOrEqual(48);
    expect(boxes).toHaveLength(state === "credentials" ? 2 : 1);
    if (state === "credentials") {
      expect(boxes[1].top - boxes[0].bottom).toBeGreaterThanOrEqual(12);
      await expect(daily.getByRole("button", { name: "続きから再開" })).toBeEnabled();
    } else await expect(daily.getByRole("button", { name: "開始", exact: true })).toHaveCount(0);
    await daily.screenshot({ path: info.outputPath(`daily-${state}-${width}.png`) });
  }
});

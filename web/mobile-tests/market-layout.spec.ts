import { expect, test } from "@playwright/test";

for (const width of [320, 390]) test(`market acquisition controls remain separated at ${width}px with enlarged text`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 844 });
  await page.route("**/api/v1/mobile/market", route => route.fulfill({ json: { latest_data_date: null, completed_dates: [] } }));
  await page.route("**/api/v1/mobile/market/plan", route => route.fulfill({ json: { first_day: "2025-08-01", last_day: "2026-10-16" } }));
  await page.route("**/api/v1/mobile/market/membership", route => route.fulfill({ json: {
    date: "2026-10-17", cutoff: "2026-10-17T11:30:00+09:00", latest_received_at: null,
    available_at_cutoff: false, is_business_day: null, acquisitionId: null,
    eligible_acquisition_id: null, after_cutoff: false,
  } }));
  await page.goto("/mobile-tests/market-layout.html");
  await expect(page.getByRole("button", { name: "履歴の取得を開始・再開" })).toBeEnabled();
  await page.addStyleTag({ content: "html { font-size: 150%; }" });
  await page.getByText("取得範囲・訂正データ・計算の確認", { exact: true }).click();
  await expect(page.getByLabel("開始日", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  for (const group of await page.locator(".button-stack").all()) {
    const controls = await group.locator("button").evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect(); return { height: box.height, top: box.top, bottom: box.bottom };
    }));
    for (const control of controls) expect(control.height).toBeGreaterThanOrEqual(48);
    for (let i = 1; i < controls.length; i++) expect(controls[i].top - controls[i - 1].bottom).toBeGreaterThanOrEqual(12);
  }
  await page.screenshot({ path: info.outputPath(`market-layout-${width}.png`), fullPage: true });
});

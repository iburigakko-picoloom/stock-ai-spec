import { expect, test } from "@playwright/test";

test("balance history completes automatically and restores its scroll position", async ({ page }) => {
  const data = Array.from({ length: 32 }, (_, index) => ({
    portfolio_id: `synthetic-${index}`,
    as_of: "2026-10-26T09:00:00Z",
    positions: Array.from({ length: 8 }, (_, symbol) => ({
      symbol: String(1000 + symbol), account_bucket_id: "synthetic-account",
      shares: index + symbol, average_acquisition_price: "1000",
    })),
    cash: [], applied_execution_ids: [],
  }));
  await page.setViewportSize({ width: 320, height: 720 });
  await page.route("**/api/v1/**", route => route.fulfill({
    json: new URL(route.request().url()).pathname === "/api/v1/portfolio/history" ? data : null,
  }));
  await page.goto("/assets/history");
  const cards = page.locator(".subscreen article.card");
  await expect(cards).toHaveCount(data.length);
  await expect(page.getByText("初回残高")).toBeVisible();
  await expect(page.getByText("残りの履歴を表示しています…")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);

  const saved = await page.evaluate(() => {
    const main = document.querySelector<HTMLElement>(".app-shell--adopted .app-main")!;
    main.scrollTo(0, Math.floor((main.scrollHeight - main.clientHeight) * 0.6));
    return main.scrollTop;
  });
  expect(saved).toBeGreaterThan(0);
  await page.waitForTimeout(100); // Allow the browser to dispatch its scroll event.
  await page.getByRole("link", { name: "資産管理", exact: true }).evaluate(link => (link as HTMLAnchorElement).click());
  await page.waitForURL("**/assets");
  await page.goBack();
  await expect(cards).toHaveCount(data.length);
  await expect.poll(() => page.evaluate(() => document.querySelector<HTMLElement>(".app-shell--adopted .app-main")!.scrollTop))
    .toBe(saved);
});

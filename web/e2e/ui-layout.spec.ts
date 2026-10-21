import { expect, test } from "@playwright/test";

// The shared E2E server uses a disposable fixture database, never production data.
for (const width of [360, 390, 430, 1280]) {
  test(`UI routes stay readable at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width > 760 ? 960 : 844 });
    await page.clock.setFixedTime(new Date("2026-01-08T03:00:00.000Z"));
    for (const [path, heading, ready] of [
      ["/today", "今日", ".proposal-hero"],
      ["/", "ホーム", ".hero-balance"],
      ["/ranking", "ランキング", ".ranking-list, .state-panel"],
      ["/settings", "設定", ".settings-list"],
      ["/validation", "検証", ".validation-hero, .state-panel"],
    ]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
      await expect(page.locator(ready).first()).toBeVisible();
      await expect(page.getByText(/読み込んでいます|確認しています/)).toHaveCount(0);
      const overflowing = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      expect(overflowing, `${path} should not scroll horizontally`).toBe(false);
      await expect(page.getByRole("navigation", { name: "メインナビゲーション" }).getByRole("link")).toHaveCount(5);
      if (path === "/today") {
        const action = page.getByRole("link", { name: "判断を確認" });
        await action.scrollIntoViewIfNeeded();
        await expect(action).toBeInViewport();
        await expect(page.getByText("取引後の推定現金（合計）")).toBeAttached();
        expect(await page.locator(".proposal-metadata").getAttribute("open")).toBeNull();
        await page.screenshot({ path: testInfo.outputPath(`今日-viewport-${width}.png`) });
      }
      await page.screenshot({ path: testInfo.outputPath(`${heading}-${width}.png`), fullPage: true });
    }
  });
}

test("settings tabs work by keyboard and stale proposals remain unavailable", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("tab", { name: "口座・資金" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "AI・データ" })).toBeFocused();
  await expect(page.getByRole("link", { name: "モデル", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "資金", exact: true })).toHaveCount(0);
  const response = await page.request.get("/api/v1/today");
  const today = await response.json();
  await page.route("**/api/v1/today", (route) => route.fulfill({ json: { ...today, isStale: true } }));
  await page.goto("/today");
  await expect(page.getByText("今日は提案を表示できません")).toBeVisible();
  await expect(page.getByRole("link", { name: "判断を確認" })).toHaveCount(0);
  await page.goto("/today/review");
  await expect(page.getByText("有効な当日提案がありません")).toBeVisible();
  await expect(page.getByRole("button", { name: "判断を保存" })).toHaveCount(0);
});

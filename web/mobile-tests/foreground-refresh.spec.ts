import { expect, test } from "@playwright/test";

test("returning to a history screen groups visibility, focus and online refreshes", async ({ page }) => {
  let reads = 0;
  let release!: () => void;
  const waiting = new Promise<void>(resolve => { release = resolve; });
  const snapshot = (date: string) => [{
    portfolio_id: "synthetic-ledger", as_of: "2026-10-26T09:00:00Z", positions: [], cash: [],
    applied_execution_ids: [], correctionRecord: { date, reason: "", kind: "deposit" },
  }];
  await page.route("**/api/v1/**", async route => {
    if (new URL(route.request().url()).pathname !== "/api/v1/portfolio/history") {
      await route.fulfill({ json: null }); return;
    }
    reads++;
    if (reads === 2) await waiting;
    await route.fulfill({ json: snapshot(reads === 1 ? "以前の履歴" : "最新の履歴") });
  });
  await page.goto("/assets/history");
  await expect(page.getByText("以前の履歴")).toBeVisible();
  await page.evaluate(() => {
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("focus"));
    window.dispatchEvent(new Event("online"));
  });
  await expect.poll(() => reads).toBe(2);
  await expect(page.getByText("前回の履歴を表示中・更新を確認しています。")).toBeVisible();
  release();
  await expect(page.getByText("最新の履歴")).toBeVisible();
  await page.waitForTimeout(200);
  expect(reads).toBe(2);
});

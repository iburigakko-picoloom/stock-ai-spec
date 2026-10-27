import { expect, test } from "@playwright/test";

test.use({ serviceWorkers: "allow" });

test("unvisited screen bundles remain available after the installed web app goes offline", async ({ page, context }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload();
  await page.waitForFunction(() => !!navigator.serviceWorker.controller);
  const cachedPaths = await page.evaluate(async () => (await (await caches.open("stock-ai-shell-v1")).keys()).map(request => new URL(request.url).pathname));
  expect(cachedPaths.some(path => /\/TodayPage-.*\.js$/.test(path))).toBe(true);
  expect(cachedPaths.some(path => /\/SettingsPage-.*\.js$/.test(path))).toBe(true);

  await context.setOffline(true);
  for (const [path, expected] of [["/today", "今日"], ["/ranking", "ランキング"], ["/settings", "設定"]] as const) {
    await page.locator(`a[href="${path}"]`).first().click();
    await expect(page.getByText("画面を準備しています…")).toHaveCount(0);
    if (path === "/settings") await expect(page.getByText("設定を取得できません")).toBeVisible();
    else await expect(page.getByRole("heading", { name: expected })).toBeVisible();
    expect(errors).toEqual([]);
  }
});


test("an open old version can use its cached screen chunk after the server updates", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload();
  await page.waitForFunction(() => !!navigator.serviceWorker.controller);
  const result = await page.evaluate(async () => {
    const path = "/assets/OldScreen-abcdefgh.js";
    const cache = await caches.open("stock-ai-shell-v1");
    await cache.put(path, new Response("export const oldVersion = true;", { headers: { "Content-Type": "text/javascript" } }));
    const response = await fetch(path);
    return { status: response.status, body: await response.text() };
  });
  expect(result).toEqual({ status: 200, body: "export const oldVersion = true;" });
});


test("an HTML fallback is not cached as a missing script", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload();
  await page.waitForFunction(() => !!navigator.serviceWorker.controller);
  const cached = await page.evaluate(async () => {
    const path = "/assets/MissingScreen-abcdefgh.js";
    await fetch(path);
    return !!(await (await caches.open("stock-ai-shell-v1")).match(path));
  });
  expect(cached).toBe(false);
});

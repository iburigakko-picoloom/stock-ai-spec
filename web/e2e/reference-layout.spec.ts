import { expect, test, type Page } from "@playwright/test";

// Only the existing disposable local fixture server is used. No owner data,
// provider credentials, external AI or real securities orders are involved.
for (const width of [320, 390]) for (const font of [100, 150]) {
  test(`current navigation and opened screens at ${width}px / ${font}%`, async ({ page }, info) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width, height: 844 });
    await page.clock.setFixedTime(new Date("2026-01-08T03:00:00.000Z"));
    const fontStyle = `html { font-size: ${font}%; }`;
    const check = async (name: string, target: Page = page): Promise<void> => {
      await target.addStyleTag({ content: fontStyle });
      await expect(target.locator(".app-brand")).toHaveCount(1);
      await expect(target.locator("h1")).toHaveCount(1);
      expect(await target.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      const heights = await target.locator(".button:visible, .back-link:visible, .segmented button:visible, .ranking-row:visible")
        .evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().height));
      for (const height of heights) expect(height, `${name} touch target`).toBeGreaterThanOrEqual(44);
      const fixed = target.locator(".sticky-action");
      if (await fixed.count()) {
        const actions = (await fixed.boundingBox())!;
        const nav = (await target.locator(".bottom-nav").boundingBox())!;
        expect(actions.y + actions.height, "fixed actions must clear navigation").toBeLessThanOrEqual(nav.y + 1);
      }
      await target.screenshot({ path: info.outputPath(`${name}-${width}-${font}.png`) });
    };
    const go = async (path: string, heading: string): Promise<void> => {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    };

    await go("/", "ホーム");
    await expect(page.getByRole("region", {name:"資産残高"})).toBeVisible();
    await check("home");
    const held = page.locator(".home-stock-button").first();
    await expect(held).toBeVisible();
    await held.click();
    await expect(page.getByRole("heading", { name: "実際の保有" })).toBeVisible();
    await expect(page.getByRole("navigation").getByRole("link", { name: "ホーム", exact: true })).toHaveAttribute("aria-current", "page");
    await check("holding-detail");
    await page.getByRole("link", { name: "← 戻る", exact: true }).click();
    await expect(page.getByRole("heading", { name: "ホーム", exact: true })).toBeVisible();

    await go("/ranking", "ランキング");
    await expect(page.locator(".ranking-row").first()).toBeVisible();
    await check("ranking");
    await page.locator(".ranking-row").first().click();
    await expect(page.getByRole("heading", { name: "実際の保有" })).toBeVisible();
    await expect(page.getByRole("navigation").getByRole("link", { name: "ランキング", exact: true })).toHaveAttribute("aria-current", "page");
    await check("ranking-detail");
    await page.getByRole("link", { name: "← 戻る", exact: true }).click();
    await expect(page.getByRole("heading", { name: "ランキング", exact: true })).toBeVisible();

    await go("/today", "今日");
    await expect(page.getByRole("region", {name:"提案サマリー"})).toBeVisible();
    await check("today");
    await page.getByRole("link", { name: "ChatGPTに相談 ↗", exact: true }).click();
    await expect(page.getByRole("heading", { name: "ChatGPTと相談", exact: true })).toBeVisible();
    await check("consultation");
    await page.getByRole("link", { name: "← 戻る", exact: true }).click();
    await page.getByRole("link", { name: "判断を確認", exact: true }).click();
    await expect(page.getByRole("heading", {name:"判断後の試算・確認中"})).toBeVisible();
    await expect(page.getByRole("button", { name: "判断を保存", exact: true })).toBeEnabled();
    await check("decision-review");
    // Saves a proposal decision only in the disposable fixture. No execution
    // is recorded or applied to holdings, cash or the tax ledger.
    const beforeDecision = await (await page.request.get("/api/v1/home")).json();
    await page.getByRole("button", { name: "判断を保存", exact: true }).click();
    await expect(page.getByRole("heading", { name: "判断を保存しました", exact: true })).toBeVisible();
    const afterDecision = await (await page.request.get("/api/v1/home")).json();
    expect(afterDecision.portfolio).toEqual(beforeDecision.portfolio);
    expect(afterDecision.holdings).toEqual(beforeDecision.holdings);
    await check("decision-saved");
    await page.getByRole("link", { name: "実行結果を記録", exact: true }).click();
    await expect(page.locator(".execution-entry:not([hidden])").first()).toBeVisible();
    await check("execution-editor");

    await go("/validation", "検証");
    await expect(page.locator(".screen-review .card, .state-panel").first()).toBeVisible();
    await check("validation");
    await page.getByRole("link", {name:"モデル比較"}).click();
    await expect(page.getByRole("heading", { name: "Champion / Challenger" })).toBeVisible();
    await check("diagnosis-open");
    await go("/settings", "設定");
    await check("settings");
    await page.getByRole("tab", { name: "AI・データ" }).click();
    await page.getByRole("link", { name: "データ・運用状態", exact: true }).click();
    await expect(page.getByRole("heading", { name: "データ・運用状態", exact: true })).toBeVisible();
    await check("data-details");
  });
}

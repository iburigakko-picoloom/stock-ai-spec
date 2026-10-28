import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

for (const width of [320, 390]) test(`execution validation preserves editable inputs at ${width}px`, async ({ page }, info) => {
  const fixture = JSON.parse(readFileSync(new URL("../../.demo-artifacts/android/mobile-golden.json", import.meta.url), "utf-8")).withholding[1].today;
  let writes = 0;
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/today") return route.fulfill({ json: fixture });
    if (path === "/api/v1/execution-context") return route.fulfill({ json: { ...fixture, decision: { decision_id: "fixture-decision", version: 1,
      lines: fixture.proposal.lines.map((line: { lineId: string; recommendedShares: number }) => ({ proposal_line_id: line.lineId, selected_target_shares: line.recommendedShares })) } } });
    if (path.endsWith("/executions")) return route.fulfill(++writes === 1
      ? { status: 422, json: { detail: "約定単価を確認してください" } } : { json: { ok: true } });
    return route.fulfill({ json: null });
  });
  await page.setViewportSize({ width, height: 844 });
  await page.goto("/today/executions");
  await page.addStyleTag({ content: "html { font-size: 150%; }" });
  await page.getByLabel("実行状態").first().selectOption("filled");
  const price = page.getByLabel("平均約定単価").first();
  await price.fill("1234");
  await page.getByRole("button", { name: "この結果を記録" }).first().click();
  await expect(page.getByText("約定単価を確認してください", { exact: true })).toBeVisible();
  await expect(price).toHaveValue("1234");
  await expect(price).toBeEnabled();
  const overflow = await page.locator("body *").evaluateAll(nodes => nodes.filter(node => node.getBoundingClientRect().right > window.innerWidth + 0.5).slice(0, 8).map(node => ({ tag: node.tagName, className: node.className, right: node.getBoundingClientRect().right })));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), JSON.stringify(overflow)).toBe(true);
  for (const box of await page.getByRole("button").all()) expect((await box.boundingBox())!.height).toBeGreaterThanOrEqual(48);
  expect((await page.getByLabel("実行日時", { exact: true }).first().boundingBox())!.width).toBeGreaterThanOrEqual(width - 80);
  expect(await page.locator(".execution-entry:not([hidden]) .subrow strong").nth(1).evaluate(node => {
    const range = document.createRange(); range.selectNodeContents(node);
    const rects = [...range.getClientRects()];
    return rects.length > 0 && Math.max(...rects.map(rect => rect.top)) < Math.min(...rects.map(rect => rect.bottom));
  })).toBe(true);
  await page.evaluate(() => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); window.scrollTo(0, 0); });
  await page.screenshot({ path: info.outputPath(`execution-recovery-${width}.png`), fullPage: true });
  await price.fill("1235");
  await page.getByRole("button", { name: "この結果を記録" }).first().click();
  await expect(page.getByRole("button", { name: "記録済み", exact: true })).toBeDisabled();
  expect(writes).toBe(2);
});

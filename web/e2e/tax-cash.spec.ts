import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

for (const width of [320, 390]) test(`cash withholding stays distinct with enlarged text at ${width}px`, async ({ page }, info) => {
  const fixture = JSON.parse(readFileSync(new URL("../../.demo-artifacts/android/mobile-golden.json", import.meta.url), "utf-8")).withholding[1];
  await page.route("**/api/v1/**", route => route.fulfill({ json: new URL(route.request().url()).pathname === "/api/v1/today" ? fixture.today : null }));
  await page.setViewportSize({ width, height: 844 });
  await page.goto("/today");
  const cashDetails = page.getByText("口座別の現金・推定改善を確認", { exact: true });
  await expect(cashDetails).toBeVisible();
  await page.addStyleTag({ content: "html { font-size: 150%; }" });
  await cashDetails.click();
  const details = page.locator("details").filter({ has: cashDetails });
  await expect(details.getByText("売却時の源泉徴収見込み", { exact: true })).toBeVisible();
  await expect(details.getByText("2,000円", { exact: true })).toBeVisible();
  const moneyLines = await details.locator("dd").evaluateAll(nodes => nodes.map(node => {
    const range = document.createRange(); range.selectNodeContents(node);
    return range.getClientRects().length;
  }));
  expect(moneyLines).toEqual([1, 1, 1]);
  await expect(page.getByText("98,000円", { exact: true }).first()).toBeVisible();
  const metric = page.locator(".metric").filter({ hasText: "推定税影響" });
  await expect(metric.getByText("0円", { exact: true })).toBeVisible();
  const overflow = await page.locator("body *").evaluateAll(nodes => nodes.filter(node => node.getBoundingClientRect().right > window.innerWidth + 0.5).slice(0, 12).map(node => ({ tag: node.tagName, className: node.className, right: node.getBoundingClientRect().right })));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), JSON.stringify(overflow)).toBe(true);
  const target = await cashDetails.boundingBox();
  expect(target!.height).toBeGreaterThanOrEqual(48);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: info.outputPath(`tax-cash-${width}.png`), fullPage: true });
});

import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

for (const width of [320, 390]) test(`cash withholding stays distinct with enlarged text at ${width}px`, async ({ page }, info) => {
  const fixture = JSON.parse(readFileSync(new URL("../../.demo-artifacts/android/mobile-golden.json", import.meta.url), "utf-8")).withholding[1];
  await page.route("**/api/v1/**", route => route.fulfill({ json: new URL(route.request().url()).pathname === "/api/v1/today" ? fixture.today : null }));
  await page.setViewportSize({ width, height: 844 });
  await page.goto("/today");
  const cashDetails = page.getByRole("link", { name: "詳細・更新状況" });
  await expect(cashDetails).toBeVisible();
  await page.addStyleTag({ content: "html { font-size: 150%; }" });
  await cashDetails.click();
  const details = page.locator("section").filter({ has: page.getByRole("heading", { name: "口座別の現金・推定改善" }) });
  await expect(details.getByText("売却時の源泉徴収見込み", { exact: true })).toBeVisible();
  await expect(details.getByText("¥2,000", { exact: true })).toBeVisible();
  const moneyLines = await details.locator("dd").evaluateAll(nodes => nodes.map(node => {
    const range = document.createRange(); range.selectNodeContents(node);
    return range.getClientRects().length;
  }));
  expect(moneyLines.length).toBeGreaterThanOrEqual(5);
  expect(moneyLines.every(count=>count===1)).toBe(true);
  await expect(details.locator(".summary-list > div").filter({hasText:"bucket"})).toContainText("¥98,000");
  await expect(details.locator(".summary-list > div").filter({hasText:"推定税影響"})).toContainText("¥0");
  const overflow = await page.locator("body *").evaluateAll(nodes => nodes.filter(node => node.getBoundingClientRect().right > window.innerWidth + 0.5).slice(0, 12).map(node => ({ tag: node.tagName, className: node.className, right: node.getBoundingClientRect().right })));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), JSON.stringify(overflow)).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: info.outputPath(`tax-cash-${width}.png`), fullPage: true });
});

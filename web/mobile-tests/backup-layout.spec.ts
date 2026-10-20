import { expect, test } from "@playwright/test";

for (const width of [320, 390]) test(`backup confirmation remains separated at ${width}px with enlarged text`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 844 });
  await page.route("**/src/mobile/native.ts", route => route.fulfill({ contentType: "application/javascript", body: `
    export const StockAI = {
      exportBackup: async () => {},
      importBackup: async () => ({ token: "synthetic-layout-preview", characters: 96781956 }),
      discardBackup: async () => {},
      restoreBackup: async () => { throw new Error("layout fixture never restores state"); },
    };
  ` }));
  await page.goto("/mobile-tests/backup-layout.html");
  await page.addStyleTag({ content: "html { font-size: 150%; }" });
  await page.getByLabel("バックアップのパスワード（12文字以上）").fill("synthetic-layout-password");
  await page.getByRole("button", { name: "復元ファイルを選ぶ" }).click();
  const restore = page.getByRole("button", { name: "このバックアップから復元" });
  await expect(restore).toBeDisabled();
  await page.getByRole("checkbox").check(); await expect(restore).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const boxes = await page.locator("button:visible").evaluateAll(nodes => nodes.map(node => {
    const box = node.getBoundingClientRect(); return { height: box.height, top: box.top, bottom: box.bottom };
  }));
  for (let index = 0; index < boxes.length; index++) {
    expect(boxes[index].height).toBeGreaterThanOrEqual(48);
    if (index) expect(boxes[index].top - boxes[index - 1].bottom).toBeGreaterThanOrEqual(12);
  }
  await page.screenshot({ path: info.outputPath(`backup-confirmation-${width}.png`), fullPage: true });
  await page.getByRole("button", { name: "復元を取り消す" }).click();
  await expect(restore).toHaveCount(0);
});

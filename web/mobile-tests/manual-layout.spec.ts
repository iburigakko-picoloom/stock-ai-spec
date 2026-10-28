import { expect, test } from "@playwright/test";

for (const width of [320, 390]) test(`manual ChatGPT keeps share quantities and controls readable at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 844 });
  await page.route("**/src/mobile/native.ts", route => route.fulfill({ contentType: "application/javascript", body: "export const isAndroid = () => true; export const StockAI = {};" }));
  await page.route("**/src/api.ts", route => route.fulfill({ contentType: "application/javascript", body: `
    export async function apiGet() { return {ready:true,selected_input:null,answers:[]}; }
    export async function apiPost(path) {
      if (path.endsWith('/export')) return {input_record_id:'synthetic',input_snapshot_id:'a'.repeat(64),expires_at:'2026-10-18T12:00:00+09:00',prompt:'合成試験の入力。実データではありません。',response_mode:'chatgpt-readable-report-v2'};
      return {review:{lines:[{symbol:'TEST',account:'A1',current_shares:100000000,target_shares:99999900,share_difference:-100}],estimated_cost_yen:'100',estimated_cash_after:{A1:'100000'},applied_to_ledger:false}};
    }
  ` }));
  await page.goto("/mobile-tests/manual-layout.html");
  await page.addStyleTag({ content: "html { font-size: 150%; }" });
  for (const box of await page.getByRole("checkbox").all()) await box.check();
  await page.getByRole("button", { name: "作成・コピー" }).click();
  await expect(page.getByRole("textbox", { name: "ChatGPTへ渡す入力" })).toHaveValue(/合成試験/);
  await expect(page.getByRole("textbox", { name: "ChatGPTの回答JSON" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "ChatGPTを開く" })).toHaveAttribute("href", "https://chatgpt.com/");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const controls = await page.locator("button:visible").evaluateAll(nodes => nodes.map(node => {
    const r=node.getBoundingClientRect();return {height:r.height,top:r.top,bottom:r.bottom};
  }));
  for (let i=0;i<controls.length;i++) {
    expect(controls[i].height).toBeGreaterThanOrEqual(48);
    if (i) expect(controls[i].top-controls[i-1].bottom).toBeGreaterThanOrEqual(12);
  }
  await page.screenshot({ path: info.outputPath(`manual-chatgpt-${width}.png`), fullPage:true });
});

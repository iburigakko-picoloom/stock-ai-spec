import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

test("manual ChatGPT browser copy, reload and expiry use the actual offline validator", async ({ page, context }) => {
  const fixture = JSON.parse(readFileSync(new URL("../../.demo-artifacts/android/mobile-golden.json", import.meta.url), "utf-8")).decision;
  expect(fixture.synthetic_only).toBe(true);
  const external: string[] = [];
  await context.route("https://**", route => { external.push(route.request().url()); return route.abort(); });
  await context.route("**/synthetic-manual-fixture.json", route => route.fulfill({ json: fixture }));
  await context.route("**/src/mobile/native.ts", route => route.fulfill({ contentType: "application/javascript",
    body: 'export { isAndroid, StockAI } from "/mobile-tests/manual-bridge.ts";' }));
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.clock.setFixedTime(new Date(fixture.now));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/mobile-tests/manual-layout.html");
  const create = page.getByRole("button", { name: "作成・コピー" });
  await expect(create).toBeDisabled({ timeout: 120_000 });
  for (const box of await page.getByRole("checkbox").all()) await box.check();
  await create.click();
  const prompt = page.getByRole("textbox", { name: "ChatGPTへ渡す入力" });
  await expect(prompt).toHaveValue(fixture.manual_exchange.exported.prompt);
  const expiry = await page.getByText("入力の有効期限：").textContent();
  await page.getByRole("button", { name: "プロンプトをコピー" }).click();
  await expect(page.getByRole("status")).toHaveText("プロンプトをコピーしました。");
  // Windows clipboard normalizes line endings; the saved prompt above stays exact.
  expect((await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, "\n")).toBe(fixture.manual_exchange.exported.prompt);

  await page.reload();
  await expect(prompt).toHaveValue(fixture.manual_exchange.exported.prompt, { timeout: 120_000 });
  await expect(page.getByText("入力の有効期限：")).toHaveText(expiry!);
  for (const box of await page.getByRole("checkbox").all()) await expect(box).not.toBeChecked();
  await expect(create).toBeDisabled();
  await expect(page.getByRole("textbox", { name: "ChatGPTの回答JSON" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "回答を検証して保存" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "ChatGPTを開く" })).toHaveAttribute("href", "https://chatgpt.com/");

  // Expiry is enforced by Python, including a copy attempted from an old screen.
  await expect(prompt).toHaveValue(fixture.manual_exchange.exported.prompt);
  await page.evaluate(async () => {
    const url = "/mobile-tests/manual-bridge.ts";
    await (await import(/* @vite-ignore */ url)).advance(16);
    await navigator.clipboard.writeText("synthetic-expiry-sentinel");
  });
  await page.getByRole("button", { name: "プロンプトをコピー" }).click();
  await expect(page.getByText("処理を完了できません", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("synthetic-expiry-sentinel");
  expect(external).toEqual([]);
});

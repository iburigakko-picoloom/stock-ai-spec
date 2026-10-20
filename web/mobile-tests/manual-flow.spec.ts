import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

test("manual ChatGPT browser copy, recreation, strict import and history use the actual offline validator", async ({ page, context }) => {
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
  const create = page.getByRole("button", { name: "プロンプトを作成" });
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
  const answer = page.getByRole("textbox", { name: "ChatGPTの回答JSON" });
  const save = page.getByRole("button", { name: "回答を検証して保存" });
  const invalid = JSON.parse(fixture.manual_exchange.answer_json);
  invalid.input_snapshot_id = "0".repeat(64);
  const invalidJson = JSON.stringify(invalid);
  await answer.fill(invalidJson);
  await save.click();
  await expect(page.getByText("処理を完了できません", { exact: true })).toBeVisible();
  await expect(answer).toHaveValue(invalidJson);
  await expect(answer).toBeEnabled();
  await expect(page.getByRole("heading", { name: "保存したChatGPT提案" })).toHaveCount(0);
  await answer.fill(fixture.manual_exchange.answer_json);
  await save.click();
  await expect(page.getByRole("status")).toContainText("保有・現金・税台帳は更新していません");
  await expect(page.getByRole("heading", { name: "保存したChatGPT提案" })).toBeVisible();

  // Identical resubmission is accepted without creating another history record.
  await save.click();
  await expect(page.getByRole("status")).toContainText("保有・現金・税台帳は更新していません");
  await page.reload();
  const history = page.locator("details.section").filter({ has: page.getByText("保存した相談履歴（直近20件）", { exact: true }) });
  await expect(history).toBeVisible({ timeout: 120_000 });
  await history.locator(":scope > summary").click();
  await expect(history.locator(":scope > details")).toHaveCount(1);
  await history.locator(":scope > details > summary").click();
  await expect(history.getByText("保存時の提案です。現在の保有状態ではありません。")).toBeVisible();

  // Expiry is enforced by Python, including a copy attempted from an old screen.
  await expect(prompt).toHaveValue(fixture.manual_exchange.exported.prompt);
  await page.evaluate(async () => {
    const url = "/mobile-tests/manual-bridge.ts";
    await (await import(/* @vite-ignore */ url)).advance(16);
    await navigator.clipboard.writeText("synthetic-expiry-sentinel");
  });
  await answer.fill(fixture.manual_exchange.answer_json);
  await page.getByRole("button", { name: "プロンプトをコピー" }).click();
  await expect(page.getByText("処理を完了できません", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("synthetic-expiry-sentinel");
  await expect(answer).toHaveValue(fixture.manual_exchange.answer_json);
  await save.click();
  await expect(page.getByText("処理を完了できません", { exact: true })).toBeVisible();
  await expect(page.getByRole("status")).toHaveCount(0);
  expect(external).toEqual([]);
});

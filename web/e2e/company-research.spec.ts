import { expect, test } from "@playwright/test";

// Explicit browser-only fixtures: this file is not shipped in the application.
for (const width of [320, 390]) {
  test(`company research remains readable with enlarged text at ${width}px`, async ({ page }, info) => {
    const context = { prediction_snapshot_id: "fixture-snapshot", symbol: "1234", company_name: "画面確認用会社",
      numerical_as_of: "2026-01-08T11:30:00+09:00", research_as_of: "2026-01-08T11:40:00+09:00",
      configuration: { model: "synthetic-model-for-layout-verification", effort: "high", prompt_version: "v1" }, revision: 1 };
    const independent = { pass_id: "first", context, phase: "independent", served_model: context.configuration.model,
      started_at: context.research_as_of, completed_at: "2026-01-08T11:43:00+09:00", text: "独立調査：利益の質に注目し、反対材料も確認しました。\n公開時刻が確認できない項目は未確認です。",
      sources: [{ url: "https://example.com/ir", title: "画面確認用の公開IR・決算資料", published_at: null }], searched: true };
    const comparison = { ...independent, pass_id: "second", phase: "comparison", completed_at: "2026-01-08T11:45:00+09:00",
      text: "照合結果：数値予測は強気ですが、企業調査では不確実性を重視しています。数値の入力締切後の追加情報は別の時点の情報として扱います。" };
    const record = { research_id: "fixture-record", context, independent, comparison, affects_numerical_proposal: false };
    await page.route("**/api/v1/stocks/1234", route => route.fulfill({ json: {
      symbol: "1234", positions: [], proposalLines: [], proposal: null,
      forecast: { snapshotId: context.prediction_snapshot_id, asOf: context.numerical_as_of, generatedAt: context.numerical_as_of,
        isStale: false, mode: "research", blockingReasons: ["画面確認用の数値です"], researchEligible: true,
        prediction: { expected_return_5d: .02, expected_return_20d: .05, large_loss_probability: .1 } },
      researchRuns: [{ run: { run_id: "fixture-run", context }, passes: [independent, comparison], attempts: [], record }],
      chatgptResearch: [record],
    } }));
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/stocks/1234");
    await expect(page.getByRole("heading", { name: "ChatGPTの見解" })).toBeVisible();
    await page.addStyleTag({ content: "html { font-size: 150%; }" });
    await page.getByText("照合結果と出典を見る", { exact: true }).click();
    await page.getByText("数値予測を見る前の独立調査", { exact: true }).click();
    await expect(page.getByText(independent.text, { exact: true }).first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const controls = await page.locator(".company-research > details > summary").evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect(); return { height: box.height, top: box.top, bottom: box.bottom };
    }));
    for (const control of controls) expect(control.height).toBeGreaterThanOrEqual(48);
    for (let i = 1; i < controls.length; i++) expect(controls[i].top - controls[i - 1].bottom).toBeGreaterThanOrEqual(12);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: info.outputPath(`company-research-${width}.png`), fullPage: true });
  });
}

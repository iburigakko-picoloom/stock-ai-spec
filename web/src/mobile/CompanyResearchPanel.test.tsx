import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { CompanyResearchPanel } from "./CompanyResearchPanel";
import type { ResearchRecord, ResearchRunView } from "./chatgpt";
import type { StockDetail } from "../types";

vi.mock("./native", () => ({ isAndroid: () => false, StockAI: {} }));
afterEach(cleanup);
const context = { prediction_snapshot_id: "snapshot", symbol: "A", company_name: "試験会社", numerical_as_of: "2026-10-16T11:30:00+09:00",
  research_as_of: "2026-10-16T11:35:00+09:00", configuration: { model: "synthetic-model", effort: "high" as const, prompt_version: "v1" }, revision: 1 };
const first = { pass_id: "first", context, phase: "independent" as const, served_model: "synthetic-model", started_at: context.research_as_of,
  completed_at: "2026-10-16T11:36:00+09:00", text: "数値を見る前の独立調査。慎重に判断。", sources: [{ url: "https://example.com/ir", title: "公式IR", published_at: null }], searched: true };
const second = { ...first, pass_id: "second", phase: "comparison" as const, completed_at: "2026-10-16T11:38:00+09:00", text: "数値は強気だが、調査は不確実性を重視。" };
const record: ResearchRecord = { research_id: "record", context, independent: first, comparison: second, affects_numerical_proposal: false };
const forecast: StockDetail["forecast"] = { snapshotId: "snapshot", asOf: context.numerical_as_of, generatedAt: context.numerical_as_of, isStale: false,
  mode: "research", blockingReasons: [], prediction: { expected_return_5d: .05, expected_return_20d: .1, large_loss_probability: .1 }, researchEligible: true };

test("completed findings expose independent and comparison evidence with clickable citations", () => {
  render(<MemoryRouter><CompanyResearchPanel symbol="A" forecast={forecast} runs={[]} records={[record]} onChanged={vi.fn()} /></MemoryRouter>);
  expect(screen.getByText("数値予測と推奨株数は変更しません。", { exact: false })).toBeInTheDocument();
  fireEvent.click(screen.getByText("数値予測を見る前の独立調査"));
  expect(screen.getByText(first.text)).toBeVisible();
  const links = screen.getAllByRole("link", { name: "公式IR", hidden: true });
  expect(links[0]).toHaveAttribute("href", "https://example.com/ir");
  expect(links[0]).toHaveAttribute("rel", "noreferrer");
  expect(screen.queryByRole("button", { name: "ChatGPTで調査" })).not.toBeInTheDocument();
});

test("partial research remains visibly incomplete and model text is rendered without executing HTML", () => {
  const view: ResearchRunView = { run: { run_id: "run", context }, passes: [{ ...first, text: "<img src=x onerror=alert(1)>未確認" }], attempts: [], record: null };
  const { container } = render(<MemoryRouter><CompanyResearchPanel symbol="A" forecast={forecast} runs={[view]} records={[]} onChanged={vi.fn()} /></MemoryRouter>);
  expect(screen.getByText("独立調査を保存済み・照合待ち")).toBeInTheDocument();
  expect(screen.getAllByText("<img src=x onerror=alert(1)>未確認").length).toBeGreaterThan(0);
  expect(container.querySelector("img")).toBeNull();
});

test("earlier judgments remain accessible in history after a new revision", () => {
  const earlier: ResearchRunView = { run: { run_id: "old", context }, passes: [first, second], attempts: [], record };
  const nextContext = { ...context, revision: 2, research_as_of: "2026-10-16T12:00:00+09:00" };
  const latest: ResearchRunView = { run: { run_id: "new", context: nextContext }, passes: [], attempts: [], record: null };
  render(<MemoryRouter><CompanyResearchPanel symbol="A" forecast={forecast} runs={[earlier, latest]} records={[record]} onChanged={vi.fn()} /></MemoryRouter>);
  fireEvent.click(screen.getByText("調査履歴・再調査"));
  const earlierSummary = screen.getByText(/第1回/);
  fireEvent.click(earlierSummary);
  const history = earlierSummary.closest("details")!;
  expect(within(history).getByText(first.text)).toBeVisible();
  expect(within(history).getByText(second.text)).toBeVisible();
});

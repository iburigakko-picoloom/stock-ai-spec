import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppShell, dateTime, yen } from "./components";
import { DecisionReviewPage } from "./pages/DecisionReviewPage";
import { ExecutionPage } from "./pages/ExecutionPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StockDetailPage } from "./pages/StockDetailPage";
import { TodayPage } from "./pages/TodayPage";
import { HomePage } from "./pages/HomePage";
import { RankingPage } from "./pages/RankingPage";
import { ValidationPage } from "./pages/ValidationPage";
import type { TodayResponse } from "./types";

const proposal = {
  proposalId: "proposal-1",
  asOf: "2026-08-24T11:30:00+09:00",
  generatedAt: "2026-08-24T11:36:00+09:00",
  modelBundleVersion: "fixture-model",
  decisionEngineVersion: "engine-v1",
  status: "READY",
  isResearchOnly: false,
  isOrderInstruction: false as const,
  estimatedSellValue: "100000",
  estimatedBuyValue: "100000",
  estimatedTransactionCost: "200",
  estimatedTaxEffect: "0",
  estimatedCashAfter: { bucket: "100000" },
  changeCount: 2,
  holdExpectedValue: "1000",
  proposedExpectedValue: "1200",
  netImprovement: "200",
  noTradeReason: null,
  lines: [
    {
      lineId: "sell-line",
      symbol: "A",
      companyName: "売却会社",
      accountBucketId: "bucket",
      currentShares: 100,
      recommendedShares: 0,
      shareDifference: -100,
      action: "SELL" as const,
      referencePrice: "1000",
      currentMarketValue: "100000",
      recommendedMarketValue: "0",
      estimatedRequiredOrReleasedCash: "-100000",
      holdExpectedValue: "0",
      proposedExpectedValue: "0",
      estimatedTransactionCost: "100",
      estimatedTaxEffect: "0",
      netExpectedImprovement: "100",
      downsideLevel: 0.2,
      uncertaintyLevel: 0.1,
      positiveReasons: ["全体最適化で売却"],
      negativeReasons: [],
    },
    {
      lineId: "buy-line",
      symbol: "B",
      companyName: "購入会社",
      accountBucketId: "bucket",
      currentShares: 0,
      recommendedShares: 100,
      shareDifference: 100,
      action: "BUY" as const,
      referencePrice: "1000",
      currentMarketValue: "0",
      recommendedMarketValue: "100000",
      estimatedRequiredOrReleasedCash: "100000",
      holdExpectedValue: "0",
      proposedExpectedValue: "0",
      estimatedTransactionCost: "100",
      estimatedTaxEffect: "0",
      netExpectedImprovement: "100",
      downsideLevel: 0.1,
      uncertaintyLevel: 0.1,
      positiveReasons: ["予測順位が高い"],
      negativeReasons: [],
    },
    {
      lineId: "hold-line",
      symbol: "C",
      companyName: "維持会社",
      accountBucketId: "bucket",
      currentShares: 100,
      recommendedShares: 100,
      shareDifference: 0,
      action: "HOLD" as const,
      referencePrice: "1000",
      currentMarketValue: "100000",
      recommendedMarketValue: "100000",
      estimatedRequiredOrReleasedCash: "0",
      holdExpectedValue: "0",
      proposedExpectedValue: "0",
      estimatedTransactionCost: "0",
      estimatedTaxEffect: "0",
      netExpectedImprovement: "0",
      downsideLevel: 0.1,
      uncertaintyLevel: 0.1,
      positiveReasons: [],
      negativeReasons: [],
    },
    {
      lineId: "skip-line",
      symbol: "D",
      companyName: "見送会社",
      accountBucketId: "bucket",
      currentShares: 0,
      recommendedShares: 0,
      shareDifference: 0,
      action: "SKIP" as const,
      referencePrice: "1000",
      currentMarketValue: "0",
      recommendedMarketValue: "0",
      estimatedRequiredOrReleasedCash: "0",
      holdExpectedValue: "0",
      proposedExpectedValue: "0",
      estimatedTransactionCost: "0",
      estimatedTaxEffect: "0",
      netExpectedImprovement: "0",
      downsideLevel: 0.1,
      uncertaintyLevel: 0.1,
      positiveReasons: [],
      negativeReasons: [],
    },
  ],
};

const today: TodayResponse = {
  businessDate: "2026-08-24",
  pipelineState: "PROPOSAL_READY",
  isStale: false,
  blockingReason: null,
  runtimeMode: "DETERMINISTIC_FIXTURE_ONLY",
  proposal,
};

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Goal 5 PWA", () => {
  it("preserves edited targets on identical refresh and blocks save until their review completes", async () => {
    const pending: ((value: Response) => void)[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/today") return Promise.resolve(jsonResponse(structuredClone(today)));
      if (String(input).endsWith("/review")) return new Promise<Response>(resolve => pending.push(resolve));
      throw new Error(`unexpected ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const review = { estimated_cash_after: {}, estimated_buy_value: "0", estimated_sell_value: "0",
      estimated_transaction_cost: "0", estimated_tax_effect: "0", resulting_positions: 0, constraint_violations: [] };
    render(<MemoryRouter><DecisionReviewPage /></MemoryRouter>);
    await waitFor(() => expect(pending).toHaveLength(1));
    await act(async () => pending[0](jsonResponse(review)));
    expect(screen.getByRole("button", { name: "判断を保存" })).toBeEnabled();
    await userEvent.selectOptions(screen.getByLabelText("購入会社の目標株数"), "0");
    expect(screen.getByRole("button", { name: "判断を保存" })).toBeDisabled();
    await waitFor(() => expect(pending).toHaveLength(2));
    act(() => window.dispatchEvent(new Event("focus")));
    await waitFor(() => expect(screen.getByLabelText("購入会社の目標株数")).toHaveValue("0"));
    expect(pending).toHaveLength(2);
    await act(async () => pending[1](jsonResponse(review)));
    expect(screen.getByRole("button", { name: "判断を保存" })).toBeEnabled();
  });
  it("shows a completed cash-only day without a fictitious proposal or review", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...today, pipelineState: "CASH_ONLY", proposal: null })));
    render(<MemoryRouter><TodayPage /></MemoryRouter>);
    await screen.findByText("分析完了・全現金維持");
    expect(screen.queryByText("次回の分析を待っています")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "判断を確認" })).not.toBeInTheDocument();
  });
  it("keeps missing amounts distinct from a real zero", () => {
    for (const value of [undefined, null, "", " ", "invalid"]) expect(yen(value)).toBe("—");
    expect(yen("0")).toBe("0円");
    expect(yen("125000")).toBe("125,000円");
  });

  it("formats times in Japan rather than the browser time zone", () => {
    expect(dateTime("2026-08-24T02:30:00Z")).toBe("8/24 11:30");
    expect(dateTime("not-a-date")).toBe("—");
  });

  it("hides a stale proposal and does not offer review", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...today, isStale: true })));
    render(<MemoryRouter><TodayPage /></MemoryRouter>);
    await screen.findByText("今日の提案をまだ表示できません");
    expect(screen.queryByText("購入会社")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "判断を確認" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "データの更新状況を確認" })).toHaveAttribute("href", "/settings?edit=market");
  });

  it("also blocks a stale proposal on the direct review route without posting", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ...today, isStale: true }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><DecisionReviewPage /></MemoryRouter>);
    await screen.findByText("有効な当日提案がありません");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "判断を保存" })).not.toBeInTheDocument();
  });

  it("shows cash from each account without exposing model details by default", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...today, proposal: { ...proposal, estimatedCashAfter: { taxable: "100000", nisa: "25000" }, netImprovement: "-200" } })));
    render(<MemoryRouter><TodayPage /></MemoryRouter>);
    await screen.findByText("125,000円");
    expect(screen.getByText("fixture-model").closest("details")).not.toHaveAttribute("open");
    await userEvent.click(screen.getByText("口座別の現金・推定改善を確認"));
    expect(screen.getByText("25,000円")).toBeVisible();
    expect(screen.getByText("-200円")).toHaveClass("text-negative");
  });

  it("separates zero filing tax from cash withheld in the cash details", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...today, proposal: {
      ...proposal, estimatedTaxEffect: "0", estimatedTaxCashWithholding: "2000",
      estimatedCashAfter: { bucket: "98000" },
    } })));
    render(<MemoryRouter><TodayPage /></MemoryRouter>);
    const details = await screen.findByText("口座別の現金・推定改善を確認");
    expect(details.closest("details")).not.toHaveAttribute("open");
    await userEvent.click(details);
    expect(within(details.closest("details")!).getByText("2,000円")).toBeVisible();
    expect(within(screen.getByText("推定税影響").parentElement!).getByText("0円"))
      .toBeInTheDocument();
  });

  it("does not display a zero return before the first Paper observation", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ observations: 0, proposal_return: 0 })));
    render(<MemoryRouter><ValidationPage /></MemoryRouter>);
    await screen.findByText("Paperの観測はまだありません");
    expect(screen.queryByText("0.00%")).not.toBeInTheDocument();
  });

  it.each([{}, { bucket: " " }, { bucket: "invalid" }])("does not turn unknown cash into a zero balance: %j", async (estimatedCashAfter) => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...today, proposal: { ...proposal, estimatedCashAfter } })));
    render(<MemoryRouter><TodayPage /></MemoryRouter>);
    const label = await screen.findByText("取引後の推定現金（合計）");
    expect(label.parentElement?.querySelector("strong")?.textContent).toBe("—");
  });

  it("offers settings when no actual portfolio is registered", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ portfolio: null, holdings: [], runtimeMode: "LIVE" })));
    render(<MemoryRouter><HomePage /></MemoryRouter>);
    await screen.findByText("表示できる資産台帳がありません");
    expect(screen.getByRole("link", { name: "登録・口座の設定を確認" })).toHaveAttribute("href", "/settings");
    expect(screen.queryByText("0円")).not.toBeInTheDocument();
  });

  it("distinguishes no search matches and switches ranking tabs with the keyboard", async () => {
    const fetchMock = vi.fn(async () => jsonResponse([{ ranking_id: "rank-1", symbol: "9432", company_name: "NTT", rank: 1, total_universe: 3000, candidate_status: "候補", portfolio_action: null }]));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><RankingPage /></MemoryRouter>);
    await screen.findByText("NTT");
    await userEvent.type(screen.getByRole("searchbox"), "NOT_FOUND");
    expect(screen.getByText("検索に一致する銘柄がありません")).toBeInTheDocument();
    expect(screen.queryByText("このランキングはまだありません")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "総合" }));
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "5日" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "5日" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/ranking?rankType=5d&limit=50", expect.anything()));
  });

  it("organizes settings by tabs and keeps operational detail collapsed", async () => {
    vi.stubGlobal("Notification", undefined);
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ runtimeMode: "LIVE", runtime: { remoteAccess: "LOCALHOST_ONLY", orderSubmission: "OUT_OF_SCOPE" }, data: { jQuantsApiKeyConfigured: true } })));
    render(<MemoryRouter><SettingsPage /></MemoryRouter>);
    await screen.findByRole("tab", { name: "口座・資金" });
    expect(screen.getByRole("link", { name: "資金" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "モデル" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "AI・データ" }));
    expect(screen.getByRole("link", { name: "モデル" })).toBeVisible();
    expect(screen.getByText("運用状態の詳細").closest("details")).not.toHaveAttribute("open");
    await userEvent.click(screen.getByRole("tab", { name: "通知" }));
    expect(screen.getByRole("button", { name: "この端末の通知権限を確認" })).toBeVisible();
  });

  it("renders five fixed navigation items", () => {
    render(<MemoryRouter><AppShell /></MemoryRouter>);
    const nav = screen.getByRole("navigation", { name: "メインナビゲーション" });
    expect(nav.querySelectorAll("a")).toHaveLength(5);
    for (const label of ["ホーム", "今日", "ランキング", "検証", "設定"]) {
      expect(within(nav).getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("shows SELL before BUY, folds HOLD, and excludes SKIP from Today", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(today)));
    render(<MemoryRouter><TodayPage /></MemoryRouter>);
    await screen.findByText("売却会社");
    const content = document.body.textContent || "";
    expect(content.indexOf("売却会社")).toBeLessThan(content.indexOf("購入会社"));
    expect(screen.getByText("HOLD 1件を確認")).toBeInTheDocument();
    expect(screen.queryByText("見送会社")).not.toBeInTheDocument();
    expect(screen.getByText("保存しても証券会社への注文は行われません")).toBeInTheDocument();
  });

  it("recalculates 100-share decisions and saves only to the manual-record API", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/today") return jsonResponse(today);
      if (url.endsWith("/review")) {
        return jsonResponse({
          proposal_id: "proposal-1",
          selected_targets: { "sell-line": 0, "buy-line": 100, "hold-line": 100, "skip-line": 0 },
          estimated_cash_after: { bucket: "100000" },
          estimated_buy_value: "100000",
          estimated_sell_value: "100000",
          estimated_transaction_cost: "200",
          estimated_tax_effect: "0",
          resulting_positions: 2,
          constraint_violations: [],
          is_order_instruction: false,
        });
      }
      if (url.endsWith("/decision") && init?.method !== "POST") return jsonResponse(null);
      if (url.endsWith("/decisions")) return jsonResponse({ version: 1 });
      throw new Error(`unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: () => "fixed-id" });
    render(<MemoryRouter><DecisionReviewPage /></MemoryRouter>);
    const selector = await screen.findByLabelText("購入会社の目標株数");
    expect(selector).toHaveDisplayValue("AI提案 100株");
    expect((await screen.findAllByText("100,000円", {}, { timeout: 2000 })).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "判断を保存" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/decisions"))).toBe(true));
    const saveCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/decisions"));
    expect(saveCall?.[1]?.headers).toMatchObject({ "X-Stock-AI-Intent": "manual-record" });
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("order"))).toBe(false);
  });

  it("records editable actual fill fields and can apply them to the next portfolio", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/today") return jsonResponse(today);
      if (url.endsWith("/decision")) return jsonResponse({
        decision_id: "decision-1",
        version: 1,
        lines: proposal.lines.map((line) => ({
          proposal_line_id: line.lineId,
          selected_target_shares: line.recommendedShares,
        })),
      });
      if (url.includes("/executions") || url === "/api/v1/portfolio/apply-executions") {
        return jsonResponse({ ok: true });
      }
      throw new Error(`unexpected URL ${url} ${init?.method || "GET"}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: () => "fixed-id" });
    render(<MemoryRouter><ExecutionPage /></MemoryRouter>);
    const company = await screen.findByText("購入会社");
    const card = company.closest("section");
    expect(card).not.toBeNull();
    const cardView = within(card as HTMLElement);
    await userEvent.selectOptions(cardView.getByLabelText("実行状態"), "partially_filled");
    await userEvent.clear(cardView.getByLabelText("約定株数"));
    await userEvent.type(cardView.getByLabelText("約定株数"), "100");
    await userEvent.clear(cardView.getByLabelText("源泉徴収税額"));
    await userEvent.type(cardView.getByLabelText("源泉徴収税額"), "50");
    await userEvent.click(cardView.getByRole("button", { name: "この結果を記録" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/executions"))).toBe(true));
    const executionCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/executions"));
    const executionBody = JSON.parse(String(executionCall?.[1]?.body)) as Record<string, unknown>;
    expect(executionBody).toMatchObject({ filledShares: 100, taxWithheld: "50", side: "BUY" });
    await userEvent.selectOptions(cardView.getByLabelText("実行状態"), "cancelled");
    await userEvent.clear(cardView.getByLabelText("約定株数"));
    await userEvent.type(cardView.getByLabelText("約定株数"), "0");
    await userEvent.click(cardView.getByRole("button", { name: "この結果を記録" }));
    await waitFor(() => expect(
      fetchMock.mock.calls.filter(([url]) => String(url).includes("/executions")),
    ).toHaveLength(2));
    const cancellationCall = fetchMock.mock.calls.filter(
      ([url]) => String(url).includes("/executions"),
    ).at(-1);
    const cancellationBody = JSON.parse(String(cancellationCall?.[1]?.body)) as Record<string, unknown>;
    expect(cancellationBody).toMatchObject({
      status: "cancelled",
      filledShares: 0,
      averageFillPrice: null,
      actualCommission: "0",
      actualOtherCost: "0",
      taxWithheld: "0",
    });
    await userEvent.click(screen.getByRole("button", { name: "記録済み約定を実保有へ反映" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/v1/portfolio/apply-executions")).toBe(true));
  });

  it("keeps execution inputs after validation errors and corrects the same form", async () => {
    let attempts = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/today") return jsonResponse(today);
      if (url.endsWith("/decision")) return jsonResponse({ decision_id: "decision-1", version: 1,
        lines: proposal.lines.map(line => ({ proposal_line_id: line.lineId, selected_target_shares: line.recommendedShares })) });
      if (url.includes("/executions")) return ++attempts === 1
        ? new Response(JSON.stringify({ detail: "約定単価を確認してください" }), { status: 422,
          headers: { "Content-Type": "application/json" } }) : jsonResponse({ ok: true });
      throw new Error(`unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: () => "fixed-id" });
    render(<MemoryRouter><ExecutionPage /></MemoryRouter>);
    const card = within((await screen.findByText("購入会社")).closest("section")!);
    await userEvent.clear(card.getByLabelText("平均約定単価"));
    await userEvent.type(card.getByLabelText("平均約定単価"), "1234");
    await userEvent.click(card.getByRole("button", { name: "この結果を記録" }));
    await screen.findByText("約定単価を確認してください");
    expect(card.getByLabelText("平均約定単価")).toBeInTheDocument();
    expect(card.getByLabelText("平均約定単価")).toHaveValue("1234");
    await userEvent.clear(card.getByLabelText("平均約定単価"));
    await userEvent.type(card.getByLabelText("平均約定単価"), "1235");
    await userEvent.click(card.getByRole("button", { name: "この結果を記録" }));
    await screen.findByText("購入会社の実行結果を記録しました。");
    expect(attempts).toBe(2);
  });

  it("blocks concurrent execution writes and retries a lost acknowledgment with the same identity", async () => {
    let rejectFirst!: (error: Error) => void;
    const bodies: Record<string, unknown>[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/today") return jsonResponse(today);
      if (url.endsWith("/decision")) return jsonResponse({ decision_id: "decision-1", version: 1,
        lines: proposal.lines.map(line => ({ proposal_line_id: line.lineId, selected_target_shares: line.recommendedShares })) });
      if (url.includes("/executions")) {
        bodies.push(JSON.parse(String(init?.body)));
        if (bodies.length === 1) return new Promise<Response>((_, reject) => { rejectFirst = reject; });
        return jsonResponse({ ok: true });
      }
      throw new Error(`unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const uuid = vi.fn(() => "one-record"); vi.stubGlobal("crypto", { randomUUID: uuid });
    render(<MemoryRouter><ExecutionPage /></MemoryRouter>);
    const card = within((await screen.findByText("購入会社")).closest("section")!);
    const button = card.getByRole("button", { name: "この結果を記録" });
    await userEvent.click(button);
    expect(button).toBeDisabled();
    expect(card.getByLabelText("平均約定単価")).toBeDisabled();
    expect(screen.getByRole("button", { name: "記録済み約定を実保有へ反映" })).toBeDisabled();
    await userEvent.dblClick(button);
    expect(bodies).toHaveLength(1);
    await act(async () => { rejectFirst(new Error("保存応答を受け取れませんでした")); });
    await screen.findByText("保存応答を受け取れませんでした");
    expect(button).toBeEnabled();
    await userEvent.click(button);
    await screen.findByText("購入会社の実行結果を記録しました。");
    expect(bodies).toHaveLength(2);
    expect(bodies[1]).toEqual(bodies[0]);
    expect(uuid).toHaveBeenCalledTimes(1);
    expect(card.getByRole("button", { name: "記録済み" })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/orders"))).toBe(false);
  });

  it("renders the formal capital and model settings routes without Notifications API", async () => {
    vi.stubGlobal("Notification", undefined);
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      runtimeMode: "FIXTURE",
      runtime: { remoteAccess: "LOCALHOST_ONLY", orderSubmission: "OUT_OF_SCOPE" },
      data: { jQuantsApiKeyConfigured: false, credentialValueExposed: false },
      capital: {
        availableCash: "100000",
        reservedCash: "10000",
        asOf: proposal.asOf,
        minimumCashRatio: null,
        dailyProposalLimit: null,
      },
      accounts: [],
      decisionPolicies: {
        decisionEngineVersion: "engine-v1",
        costPolicyId: "cost",
        costPolicyVersion: "1",
        taxPolicyId: "tax",
        taxPolicyVersion: "1",
        roundLotShares: 100,
        maximumPositions: null,
        maximumSymbolWeight: null,
        maximumSectorWeight: null,
        maximumTurnoverRatio: null,
        maximumTradeAdvRatio: null,
        minimumImprovementYen: null,
        uncertaintyBufferYen: null,
      },
      notifications: { inApp: "AVAILABLE", webPush: "BLOCKED_BY_CONFIGURATION" },
      decision: {
        freezeTime: "11:30 JST",
        recommendedTradeTime: "12:30 JST 後場寄り",
        method: "Daily Portfolio Decision Engine",
      },
      model: {
        morningChampion: "BLOCKED_BY_DATA_CAPABILITY",
        trainedAt: null,
        trainingDataEnd: null,
        validationStatus: "BLOCKED_BY_DATA_CAPABILITY",
        automaticPromotion: false,
      },
    })));
    const capitalView = render(
      <MemoryRouter initialEntries={["/settings/capital"]}>
        <Routes><Route path="/settings/:section" element={<SettingsPage />} /></Routes>
      </MemoryRouter>,
    );
    await screen.findByText("運用対象資金");
    capitalView.unmount();
    render(
      <MemoryRouter initialEntries={["/settings/model"]}>
        <Routes><Route path="/settings/:section" element={<SettingsPage />} /></Routes>
      </MemoryRouter>,
    );
    await screen.findByText("検証状態");
    expect(screen.queryByText("不明な設定項目です")).not.toBeInTheDocument();
  });

  it("switches same-symbol account buckets without mixing prices or shares", async () => {
    const detail = {
      symbol: "A",
      positions: [
        { symbol: "A", account_bucket_id: "taxable", shares: 200, average_acquisition_price: "900", market_price: "1000" },
        { symbol: "A", account_bucket_id: "nisa", shares: 100, average_acquisition_price: "800", market_price: "1000" },
      ],
      proposalLines: [
        { ...proposal.lines[0], lineId: "tax-line", symbol: "A", accountBucketId: "taxable", currentShares: 200, recommendedShares: 100, shareDifference: -100 },
        { ...proposal.lines[2], lineId: "nisa-line", symbol: "A", accountBucketId: "nisa", currentShares: 100, recommendedShares: 100 },
      ],
      proposal,
    };
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(detail)));
    render(<MemoryRouter initialEntries={["/stocks/A"]}><StockDetailPage /></MemoryRouter>);
    await screen.findByText("実保有合計");
    expect(screen.getByText("300株")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "nisa" }));
    expect(screen.getByText("実保有 / nisa")).toBeInTheDocument();
    expect(screen.getAllByText("100株").length).toBeGreaterThan(0);
    expect(screen.getByText("800円")).toBeInTheDocument();
  });
});

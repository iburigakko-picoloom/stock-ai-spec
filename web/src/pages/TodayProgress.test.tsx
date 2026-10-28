import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { useApiData } from "../hooks";
import { StockAI } from "../mobile/native";
import { TodayPage } from "./TodayPage";

vi.mock("../hooks", () => ({ useApiData: vi.fn() }));
vi.mock("../mobile/native", () => ({ isAndroid: () => true, StockAI: {
  dailyStatus: vi.fn(), analysisStatus: vi.fn(), startDaily: vi.fn(), stopDaily: vi.fn(), requestDailyNotifications: vi.fn(),
} }));

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(StockAI.dailyStatus).mockResolvedValue({ enabled:true, state:"retry", notificationsEnabled:true, retryAt:"2026-10-28T03:30:00Z" });
  vi.mocked(StockAI.analysisStatus).mockResolvedValue({ state:"blocked", blockingReasons:["NO_USABLE_FORECAST"] });
  vi.mocked(useApiData).mockReturnValue({ data:null, error:null, loading:true, savedAt:null, reload:vi.fn() });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

test("details display progress and saved failure while the proposal read is still pending", async () => {
  render(<MemoryRouter initialEntries={["/today/details"]}><TodayPage /></MemoryRouter>);
  expect(screen.getByText("今日の状態を確認しています")).toBeVisible();
  expect(await screen.findByText(/詳しい原因は記録されていません/)).toBeVisible();
  expect(await screen.findByText(/予測に必要な株価履歴が不足/)).toBeVisible();
  expect(screen.getByText(/再試行予定/)).toBeVisible();
  expect(screen.getByRole("link", {name:"処理状況・実行記録 ›"})).toBeVisible();
});

test("long waiting is explained without cancelling a later result", async () => {
  vi.useFakeTimers();
  const view=render(<MemoryRouter initialEntries={["/today/details"]}><TodayPage /></MemoryRouter>);
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
  expect(screen.getByText(/提案の確認に時間がかかっています/)).toBeVisible();
  vi.mocked(useApiData).mockReturnValue({data:{businessDate:"2026-10-28",pipelineState:"PRE_MARKET",isStale:false,blockingReason:null,runtimeMode:"RESEARCH",proposal:null},error:null,loading:false,savedAt:null,reload:vi.fn()});
  view.rerender(<MemoryRouter initialEntries={["/today/details"]}><TodayPage /></MemoryRouter>);
  expect(screen.queryByText(/提案の確認に時間がかかっています/)).not.toBeInTheDocument();
  expect(screen.getByRole("heading",{name:"提案の状況"})).toBeVisible();
});

test("a proposal read failure keeps progress visible and exposes retry", async () => {
  const reload=vi.fn();
  vi.mocked(useApiData).mockReturnValue({data:null,error:"取得失敗",loading:false,savedAt:null,reload});
  render(<MemoryRouter initialEntries={["/today/details"]}><TodayPage /></MemoryRouter>);
  expect(screen.getByText("取得失敗")).toBeVisible();
  expect(await screen.findByText(/予測に必要な株価履歴が不足/)).toBeVisible();
  screen.getByRole("button",{name:"提案をもう一度確認"}).click();
  expect(reload).toHaveBeenCalledOnce();
});

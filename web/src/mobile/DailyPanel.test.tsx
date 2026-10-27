import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { DailyPanel, DailyControls } from "./DailyPanel";
import { StockAI } from "./native";

vi.mock("./native", () => ({ isAndroid: () => true, StockAI: {
  dailyStatus: vi.fn(), startDaily: vi.fn(), stopDaily: vi.fn(), requestDailyNotifications: vi.fn(),
  analysisStatus: vi.fn(),
} }));
const idle = { enabled: false, state: "idle", notificationsEnabled: false };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(StockAI.analysisStatus).mockResolvedValue({ state: "idle" });
  vi.mocked(StockAI.dailyStatus).mockResolvedValue(idle);
  vi.mocked(StockAI.requestDailyNotifications).mockResolvedValue({ granted: false });
  vi.mocked(StockAI.startDaily).mockResolvedValue({ ...idle, enabled: true, state: "queued" });
});
afterEach(cleanup);

test("one foreground return causes one daily status read", async () => {
  let finish!: (value: typeof idle) => void;
  vi.mocked(StockAI.dailyStatus).mockResolvedValueOnce(idle)
    .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  render(<DailyPanel />);
  await screen.findByText("未開始");
  act(() => { document.dispatchEvent(new Event("visibilitychange")); window.dispatchEvent(new Event("focus")); });
  await waitFor(() => expect(StockAI.dailyStatus).toHaveBeenCalledTimes(2));
  await act(async () => finish({ ...idle, enabled: true, state: "history" }));
  expect(StockAI.dailyStatus).toHaveBeenCalledTimes(2);
  expect(screen.getByText("履歴を取得しています")).toBeVisible();
});

test.each([["history", 0], ["forecast_saved", 2], ["deciding", 2], ["numerical_saved", 3], ["research_running", 3]] as const)("%s reports completed stages rather than elapsed-time percent", (state, done) => {
  render(<DailyControls status={{ ...idle, enabled: true, state }} busy={false} message="" onChange={vi.fn()} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", String(done));
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuetext", `${done}/3工程完了。残り時間の割合ではありません。`);
});

test.each(["retry", "compute_wait", "paused", "inputs", "consultation_ready", "closed", "waiting_cutoff"])("%s never implies active computation or completed numerical results", state => {
  render(<DailyControls status={{ ...idle, enabled: true, state }} busy={false} message="" onChange={vi.fn()} />);
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  expect(screen.queryByText(/画面を閉じても続けます/)).not.toBeInTheDocument();
});

test.each([
  ["forecast_saved", "原予測を保存済み・株数判定待ち"],
  ["consultation_ready", "研究用の原予測を保存済み・ChatGPTへの相談準備完了"],
  ["deciding", "株数を計算しています"],
  ["history_wait", "Androidの取得待ち・アプリで保存状態を確認してください"],
  ["compute_wait", "Androidの計算待ち・アプリで保存状態を確認してください"],
])("%s keeps partial progress separate from completion", async (state, label) => {
  vi.mocked(StockAI.dailyStatus).mockResolvedValue({ ...idle, enabled: true, state });
  render(<DailyPanel />);
  expect(await screen.findByText(label)).toBeVisible();
  expect(screen.queryByText("数値判定・ChatGPT調査を保存しました")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "自動処理を停止" })).toBeEnabled();
});

test("denying notification permission still starts computation once and separates research state", async () => {
  render(<DailyPanel />);
  const start = await screen.findByRole("button", { name: "開始" });
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  await waitFor(() => expect(StockAI.startDaily).toHaveBeenCalledTimes(1));
  expect(StockAI.requestDailyNotifications).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(start).toBeDisabled());
  expect(screen.getByText("通知はオフです。計算結果はアプリ内に保存します。")).toBeVisible();
  await act(async () => {
    vi.mocked(StockAI.dailyStatus).mockResolvedValue({ ...idle, enabled: true, state: "numerical_saved" });
    window.dispatchEvent(new Event("focus"));
  });
  expect(await screen.findByText("数値判定を保存済み・ChatGPT調査は別途確認")).toBeVisible();
});

test("stop waits for native acknowledgment and keeps a resume action", async () => {
  vi.mocked(StockAI.dailyStatus).mockResolvedValue({ ...idle, enabled: true, state: "history" });
  vi.mocked(StockAI.stopDaily).mockResolvedValue({ ...idle, state: "paused" });
  render(<DailyPanel />);
  const stop = await screen.findByRole("button", { name: "自動処理を停止" });
  await waitFor(() => expect(stop).toBeEnabled()); fireEvent.click(stop);
  expect(await screen.findByRole("button", { name: "続きから再開" })).toBeEnabled();
  expect(stop).toBeDisabled();
});

test("an older status read cannot overwrite an acknowledged stop", async () => {
  let finishOldRead!: (value: typeof idle) => void;
  const running = { ...idle, enabled: true, state: "history" };
  vi.mocked(StockAI.dailyStatus).mockResolvedValueOnce(running)
    .mockImplementationOnce(() => new Promise(resolve => { finishOldRead = resolve; }));
  vi.mocked(StockAI.stopDaily).mockResolvedValue({ ...idle, state: "paused" });
  render(<DailyPanel />);
  const stop = await screen.findByRole("button", { name: "自動処理を停止" });
  await waitFor(() => expect(stop).toBeEnabled());
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  await waitFor(() => expect(StockAI.dailyStatus).toHaveBeenCalledTimes(2));
  fireEvent.click(stop);
  await screen.findByRole("button", { name: "続きから再開" });
  await act(async () => { finishOldRead(running); });
  expect(screen.getByRole("button", { name: "続きから再開" })).toBeEnabled();
  expect(stop).toBeDisabled();
});

 test("calculating shows the saved percentage instead of a coarse stage bar", async () => {
  vi.mocked(StockAI.analysisStatus).mockResolvedValue({ state: "running", phase: "features", percent: 43 });
  render(<DailyControls status={{ ...idle, enabled: true, state: "calculating" }} busy={false} message="" onChange={vi.fn()} />);
  expect(await screen.findByText(/43%/)).toBeVisible();
  expect(screen.getByRole("progressbar")).toHaveAttribute("max", "100");
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "43");
});


test("slow daily status reads do not queue repeated polling and focus coalesces", async () => {
  vi.useFakeTimers();
  let finish!: (value: typeof idle) => void;
  vi.mocked(StockAI.dailyStatus).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValue({ ...idle, enabled: true, state: "history" });
  const view = render(<DailyPanel />);
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); window.dispatchEvent(new Event("focus")); window.dispatchEvent(new Event("focus")); });
  await act(async () => { await vi.advanceTimersByTimeAsync(16); });
  expect(StockAI.dailyStatus).toHaveBeenCalledTimes(1);
  await act(async () => { finish(idle); });
  expect(StockAI.dailyStatus).toHaveBeenCalledTimes(2);
  expect(screen.getByText("履歴を取得しています")).toBeVisible();
  view.unmount(); vi.useRealTimers();
});


test("backgrounding pauses daily status polling until the app is visible", async () => {
  vi.useFakeTimers();
  let visibility: DocumentVisibilityState = "visible";
  const visible = vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
  const view = render(<DailyPanel />);
  await act(async () => {});
  expect(StockAI.dailyStatus).toHaveBeenCalledTimes(1);
  visibility = "hidden";
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await vi.advanceTimersByTimeAsync(60_000); });
  expect(StockAI.dailyStatus).toHaveBeenCalledTimes(1);
  visibility = "visible";
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await vi.advanceTimersByTimeAsync(16); });
  expect(StockAI.dailyStatus).toHaveBeenCalledTimes(2);
  view.unmount(); visible.mockRestore(); vi.useRealTimers();
});

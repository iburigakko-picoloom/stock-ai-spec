import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { DailyPanel } from "./DailyPanel";
import { StockAI } from "./native";

vi.mock("./native", () => ({ isAndroid: () => true, StockAI: {
  dailyStatus: vi.fn(), startDaily: vi.fn(), stopDaily: vi.fn(), requestDailyNotifications: vi.fn(),
} }));
const idle = { enabled: false, state: "idle", notificationsEnabled: false };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(StockAI.dailyStatus).mockResolvedValue(idle);
  vi.mocked(StockAI.requestDailyNotifications).mockResolvedValue({ granted: false });
  vi.mocked(StockAI.startDaily).mockResolvedValue({ ...idle, enabled: true, state: "queued" });
});
afterEach(cleanup);

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
  fireEvent.click(stop);
  await screen.findByRole("button", { name: "続きから再開" });
  await act(async () => { finishOldRead(running); });
  expect(screen.getByRole("button", { name: "続きから再開" })).toBeEnabled();
  expect(stop).toBeDisabled();
});

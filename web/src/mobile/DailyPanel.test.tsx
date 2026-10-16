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

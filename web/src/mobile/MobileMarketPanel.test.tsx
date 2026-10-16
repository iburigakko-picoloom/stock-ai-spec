import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiGet } from "../api";
import { acquireRange } from "./market";
import { MobileMarketPanel } from "./MobileMarketPanel";

vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("./market", async importOriginal => ({ ...await importOriginal<typeof import("./market")>(), acquireRange: vi.fn() }));
afterEach(cleanup);
const plan = { first_day: "2026-01-05", last_day: "2026-01-06" };
const status = { latest_data_date: null, completed_dates: [] };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/plan") ? plan : status);
});
test("saved range is restored and stopping remains reachable while other settings are busy", async () => {
  let finish!: () => void;
  vi.mocked(acquireRange).mockImplementation(async (_range, _progress, stopped) => {
    await new Promise<void>(resolve => { finish = resolve; });
    return { stopped: stopped(), status };
  });
  const onBusy = vi.fn();
  const { rerender } = render(<MobileMarketPanel configured disabled={false} onBusy={onBusy} />);
  const start = screen.getByRole("button", { name: "履歴の取得を開始・再開" });
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  rerender(<MobileMarketPanel configured disabled onBusy={onBusy} />);
  expect(screen.getByRole("button", { name: "この日付の取得後に停止" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "この日付の取得後に停止" }));
  finish();
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("取得を停止しました"));
  expect(acquireRange).toHaveBeenCalledWith(plan, expect.any(Function), expect.any(Function), "pending");
});
test("range and correction controls are collapsed with missing account setup", async () => {
  render(<MobileMarketPanel configured={false} disabled={false} onBusy={vi.fn()} />);
  await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(3));
  expect(screen.getByRole("button", { name: "履歴の取得を開始・再開" })).toBeDisabled();
  expect(screen.getByText("取得範囲・訂正データ・計算の確認").closest("details")).not.toHaveAttribute("open");
  expect(screen.getByText(/画面を開いて取得します/)).toBeVisible();
});

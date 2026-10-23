import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiGet, apiPost } from "../api";
import { acquireRange } from "./market";
import { MobileMarketPanel } from "./MobileMarketPanel";

vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("./market", async importOriginal => ({ ...await importOriginal<typeof import("./market")>(), acquireRange: vi.fn() }));
afterEach(cleanup);
const plan = { first_day: "2026-01-05", last_day: "2026-01-06" };
const status = { latest_data_date: null, completed_dates: [] };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/plan") ? plan : path.endsWith("/universe-policy") ? { mode: "legacy300", experimental: false } : status);
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
  await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(4));
  expect(screen.getByRole("button", { name: "履歴の取得を開始・再開" })).toBeDisabled();
  expect(screen.getByText("取得範囲・訂正データ・計算の確認").closest("details")).not.toHaveAttribute("open");
  expect(screen.getByText(/画面を開いて取得します/)).toBeVisible();
});

test("universe policy is opt in and a failed save keeps the last saved choice", async () => {
  render(<MobileMarketPanel configured disabled={false} onBusy={vi.fn()} />);
  const choice = screen.getByLabelText("予測対象");
  fireEvent.click(screen.getByText("取得範囲・訂正データ・計算の確認"));
  await waitFor(() => expect(choice).toBeEnabled());
  expect(choice).toHaveValue("legacy300");
  vi.mocked(apiPost).mockResolvedValueOnce({ mode: "topix500-preview", experimental: true });
  fireEvent.change(choice, { target: { value: "topix500-preview" } });
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("次に作成する数値予測"));
  expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/market/universe-policy", { mode: "topix500-preview" });
  expect(screen.getByText(/研究用で、実機確認中/)).toBeVisible();
  vi.mocked(apiPost).mockRejectedValueOnce(new Error("保存できません"));
  fireEvent.change(choice, { target: { value: "legacy300" } });
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("保存できません"));
  expect(choice).toHaveValue("topix500-preview");
});


test("background settings is explicit and does not start a page-owned download", async () => {
  const open = vi.fn();
  render(<MobileMarketPanel configured disabled={false} onBusy={vi.fn()} onBackground={open} />);
  fireEvent.click(screen.getByRole("button", { name: "バックグラウンド取得の設定へ" }));
  expect(open).toHaveBeenCalledTimes(1);
  expect(acquireRange).not.toHaveBeenCalled();
  await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(4));
});

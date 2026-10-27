import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiGet, apiPost } from "../api";
import { acquireRange } from "./market";
import { MobileMarketPanel } from "./MobileMarketPanel";
import { Activity } from "react";

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
  const start = screen.getByRole("button", { name: "履歴を取得" });
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  rerender(<MobileMarketPanel configured disabled onBusy={onBusy} />);
  expect(screen.getByRole("button", { name: "この日付の取得後に停止" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "この日付の取得後に停止" }));
  finish();
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("取得を停止しました"));
  expect(acquireRange).toHaveBeenCalledWith(plan, expect.any(Function), expect.any(Function), "pending");
});
test("range and correction controls are visible with missing account setup", async () => {
  render(<MobileMarketPanel configured={false} disabled={false} onBusy={vi.fn()} />);
  await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(4));
  expect(screen.getByRole("button", { name: "履歴を取得" })).toBeDisabled();
  expect(screen.getByText("対象銘柄・特徴量").closest("section")).toBeVisible();
  expect(screen.getByLabelText("取得開始日")).toBeVisible();
  expect(screen.getByLabelText("訂正を確認する日付")).toBeVisible();
});

test("universe policy is opt in and a failed save keeps the last saved choice", async () => {
  render(<MobileMarketPanel configured disabled={false} onBusy={vi.fn()} />);
  const choice = screen.getByLabelText("予測対象");
  fireEvent.click(screen.getByText("対象銘柄・特徴量"));
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

test("market status appears before slower plan and membership while writes remain gated", async () => {
  let finishPlan!: (value: unknown) => void;
  let finishMember!: (value: unknown) => void;
  vi.mocked(apiGet).mockImplementation(path => path.endsWith("/plan") ? new Promise(resolve => {finishPlan=resolve;})
    : path.endsWith("/membership") ? new Promise(resolve => {finishMember=resolve;})
    : Promise.resolve(path.endsWith("/universe-policy") ? {mode:"legacy300",experimental:false} : {...status,latest_data_date:"2026-01-05"}));
  render(<MobileMarketPanel configured disabled={false} onBusy={vi.fn()} />);
  expect(await screen.findByText("2026-01-05")).toBeVisible();
  expect(screen.getByLabelText("取得開始日")).toBeDisabled();
  expect(screen.getByLabelText("取得開始日")).toHaveValue("");
  expect(screen.getByRole("button",{name:"履歴を取得"})).toBeDisabled();
  expect(screen.getByRole("button",{name:"候補と全保有の対象を確認"})).toBeDisabled();
  await act(async () => finishPlan(plan));
  expect(screen.getByLabelText("取得開始日")).toHaveValue("2026-01-05");
  expect(screen.getByRole("button",{name:"履歴を取得"})).toBeDisabled();
  await act(async () => finishMember({latest_received_at:null,eligible_received_at:null}));
  await waitFor(()=>expect(screen.getByRole("button",{name:"履歴を取得"})).toBeEnabled());
});

test("a failed membership read preserves separately loaded market status but prevents acquisition", async () => {
  vi.mocked(apiGet).mockImplementation(async path => {
    if(path.endsWith("/membership"))throw new Error("failure");
    return path.endsWith("/plan") ? plan : path.endsWith("/universe-policy") ? {mode:"legacy300"} : {...status,latest_data_date:"2026-01-05"};
  });
  render(<MobileMarketPanel configured disabled={false} onBusy={vi.fn()} />);
  expect(await screen.findByText("2026-01-05")).toBeVisible();
  expect(await screen.findByRole("status")).toHaveTextContent("確認できません");
  expect(screen.getByRole("button",{name:"履歴を取得"})).toBeDisabled();
});

test("reopening verifies data again without overwriting the unsaved date range", async () => {
  const content=(visible:boolean)=><Activity mode={visible ? "visible" : "hidden"}><MobileMarketPanel configured disabled={false} onBusy={vi.fn()} /></Activity>;
  const view=render(content(true));
  await waitFor(()=>expect(screen.getByRole("button",{name:"履歴を取得"})).toBeEnabled());
  fireEvent.change(screen.getByLabelText("取得開始日"),{target:{value:"2025-12-01"}});
  view.rerender(content(false));
  const pending: Record<string,(value:unknown)=>void> = {};
  vi.mocked(apiGet).mockImplementation(path=>new Promise(resolve=>{pending[path]=resolve;}));
  view.rerender(content(true));
  await waitFor(()=>expect(Object.keys(pending)).toHaveLength(4));
  expect(screen.getByLabelText("取得開始日")).toHaveValue("2025-12-01");
  expect(screen.getByLabelText("取得開始日")).toBeDisabled();
  expect(screen.getByRole("button",{name:"履歴を取得"})).toBeDisabled();
  await act(async()=>{
    pending["/api/v1/mobile/market"](status);
    pending["/api/v1/mobile/market/plan"](plan);
    pending["/api/v1/mobile/market/membership"]({});
    pending["/api/v1/mobile/market/universe-policy"]({mode:"legacy300"});
  });
  await waitFor(()=>expect(screen.getByRole("button",{name:"履歴を取得"})).toBeEnabled());
  expect(screen.getByLabelText("取得開始日")).toHaveValue("2025-12-01");
});

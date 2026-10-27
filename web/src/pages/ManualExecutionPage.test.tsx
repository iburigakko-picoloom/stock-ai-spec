import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { ExecutionPage } from "./ExecutionPage";
vi.mock("../api",()=>({apiGet:vi.fn(),apiPost:vi.fn()}));
vi.mock("../mobile/native",()=>({isAndroid:()=>false,StockAI:{}}));
afterEach(cleanup);
beforeEach(()=>{
  vi.resetAllMocks();
  vi.mocked(apiGet).mockImplementation(async path=>path==="/api/v1/execution-context?includeManual=1" ? {proposal:null,decision:null} : {
    portfolioId:"real-ledger",asOf:"2026-10-01T12:00:00+09:00",accountLabels:{bucket:"特定口座"},holdings:[]});
});
test("missing judgment opens actual trade input and preserves ID and fields across a failed save",async()=>{
  render(<MemoryRouter initialEntries={["/today/executions"]}><ExecutionPage/></MemoryRouter>);
  const symbol=await screen.findByLabelText("銘柄コード");
  expect(screen.queryByText("実行待ちの保存済み判断がありません")).not.toBeInTheDocument();
  fireEvent.change(symbol,{target:{value:"7203"}});
  fireEvent.change(screen.getByLabelText("約定株数"),{target:{value:"100"}});
  fireEvent.change(screen.getByLabelText("平均約定単価"),{target:{value:"1234"}});
  vi.mocked(apiPost).mockRejectedValueOnce(Error("保存応答を取得できません"));
  fireEvent.click(screen.getByRole("button",{name:"取引を記録"}));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("平均約定単価")).toHaveValue("1234");
  vi.mocked(apiPost).mockResolvedValue({applied:true});
  fireEvent.click(screen.getByRole("button",{name:"取引を記録"}));
  await screen.findByText("取引を記録し、約定した株数と金額だけを残高へ反映しました。");
  expect(apiPost).toHaveBeenCalledTimes(2);
  expect(vi.mocked(apiPost).mock.calls[0]).toEqual(vi.mocked(apiPost).mock.calls[1]);
  expect(vi.mocked(apiPost).mock.calls[1][0]).toBe("/api/v1/executions/manual");
  expect(screen.getByRole("button",{name:"記録済み"})).toBeDisabled();
});
test("direct manual entry skips proposal reads and uses stock-detail symbol",async()=>{
 render(<MemoryRouter initialEntries={["/today/executions?manual=1&symbol=7203"]}><ExecutionPage/></MemoryRouter>);
 expect(await screen.findByLabelText("銘柄コード")).toHaveValue("7203");
 await waitFor(()=>expect(apiGet).toHaveBeenCalledTimes(1));
 expect(apiGet).toHaveBeenCalledWith("/api/v1/execution-entry-context");
});
test("missing assets offers registration instead of asking for an AI judgment",async()=>{
 vi.mocked(apiGet).mockResolvedValue({portfolioId:null,accountLabels:{},holdings:[]});
 render(<MemoryRouter initialEntries={["/today/executions?manual=1"]}><ExecutionPage/></MemoryRouter>);
 expect(await screen.findByRole("link",{name:"初回資産登録"})).toHaveAttribute("href","/holdings");
 expect(apiPost).not.toHaveBeenCalled();
});


test("trade fields accept input while account verification is pending and save waits for it", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiGet).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  render(<MemoryRouter initialEntries={["/today/executions?manual=1"]}><ExecutionPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("銘柄コード"), { target: { value: "7203" } });
  fireEvent.change(screen.getByLabelText("約定株数"), { target: { value: "100" } });
  fireEvent.change(screen.getByLabelText("平均約定単価"), { target: { value: "1234" } });
  expect(screen.getByRole("button", { name: "取引を記録" })).toBeDisabled();
  expect(screen.getByLabelText("口座")).toBeDisabled();
  expect(apiPost).not.toHaveBeenCalled();
  await act(async () => { finish({ portfolioId:"ledger", asOf:"2026-10-01T12:00:00+09:00", accountLabels:{ bucket:"特定口座" }, holdings:[] }); });
  expect(screen.getByLabelText("銘柄コード")).toHaveValue("7203");
  expect(screen.getByLabelText("約定株数")).toHaveValue(100);
  expect(screen.getByLabelText("平均約定単価")).toHaveValue("1234");
  expect(screen.getByRole("button", { name: "取引を記録" })).toBeEnabled();
});

test("failed account verification retains typed fields and cannot save", async () => {
  let fail!: (reason: Error) => void;
  vi.mocked(apiGet).mockReturnValue(new Promise((_resolve, reject) => { fail = reject; }));
  render(<MemoryRouter initialEntries={["/today/executions?manual=1"]}><ExecutionPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("銘柄コード"), { target: { value: "7203" } });
  await act(async () => { fail(new Error("確認できません")); });
  expect(screen.getByLabelText("銘柄コード")).toHaveValue("7203");
  expect(screen.getByRole("button", { name: "取引を記録" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "再読み込み" })).toBeVisible();
  expect(apiPost).not.toHaveBeenCalled();
});


test("a pending judgment read offers direct manual trade entry for the same stock", async () => {
  vi.mocked(apiGet).mockImplementation(path => path === "/api/v1/execution-context?includeManual=1" ? new Promise(() => {}) : Promise.resolve({
    portfolioId:"ledger", asOf:null, accountLabels:{ bucket:"特定口座" }, holdings:[],
  }));
  render(<MemoryRouter initialEntries={["/today/executions?symbol=7203"]}><ExecutionPage /></MemoryRouter>);
  expect(screen.getByText("実行結果入力を準備しています")).toBeVisible();
  const manual = screen.getByRole("link", { name:"判断を使わず取引を入力" });
  expect(manual).toHaveAttribute("href", "/today/executions?manual=1&symbol=7203");
  fireEvent.click(manual);
  expect(await screen.findByLabelText("銘柄コード")).toHaveValue("7203");
  await waitFor(() => expect(screen.getByRole("button", { name:"取引を記録" })).toBeEnabled());
  expect(apiPost).not.toHaveBeenCalled();
});

test("failed judgment read still offers manual entry", async () => {
  vi.mocked(apiGet).mockRejectedValue(new Error("判断の読取失敗"));
  render(<MemoryRouter initialEntries={["/today/executions?symbol=7203"]}><ExecutionPage /></MemoryRouter>);
  expect(await screen.findByText("入力を準備できません")).toBeVisible();
  expect(screen.getByRole("link", { name:"判断を使わず取引を入力" })).toHaveAttribute("href", "/today/executions?manual=1&symbol=7203");
});


test("missing judgment reuses the verified manual context without a second read", async () => {
  const manualContext={portfolioId:"ledger",asOf:"2026-10-01T12:00:00+09:00",accountLabels:{bucket:"特定口座"},holdings:[]};
  vi.mocked(apiGet).mockResolvedValue({proposal:null,decision:null,accountLabels:{},manualContext});
  render(<MemoryRouter initialEntries={["/today/executions"]}><ExecutionPage /></MemoryRouter>);
  expect(await screen.findByLabelText("口座")).toHaveValue("bucket");
  expect(screen.getByRole("button",{name:"取引を記録"})).toBeEnabled();
  expect(apiGet).toHaveBeenCalledExactlyOnceWith("/api/v1/execution-context?includeManual=1");
  expect(apiPost).not.toHaveBeenCalled();
});


test("a second trade refreshes the ledger after reusing the first context", async () => {
  const first={portfolioId:"ledger-1",asOf:null,accountLabels:{bucket:"特定口座"},holdings:[]};
  const next={...first,portfolioId:"ledger-2",holdings:[{symbol:"7203",accountBucketId:"bucket",shares:100}]};
  vi.mocked(apiGet).mockResolvedValueOnce({proposal:null,decision:null,accountLabels:{},manualContext:first}).mockResolvedValueOnce(next);
  vi.mocked(apiPost).mockResolvedValue({applied:true});
  render(<MemoryRouter initialEntries={["/today/executions"]}><ExecutionPage /></MemoryRouter>);
  fireEvent.change(await screen.findByLabelText("銘柄コード"),{target:{value:"7203"}});
  fireEvent.change(screen.getByLabelText("約定株数"),{target:{value:"100"}});
  fireEvent.change(screen.getByLabelText("平均約定単価"),{target:{value:"1000"}});
  fireEvent.click(screen.getByRole("button",{name:"取引を記録"}));
  fireEvent.click(await screen.findByRole("button",{name:"別の取引を入力"}));
  await waitFor(()=>expect(apiGet).toHaveBeenCalledWith("/api/v1/execution-entry-context"));
  await waitFor(()=>expect(screen.getByRole("button",{name:"取引を記録"})).toBeEnabled());
  expect(apiGet).toHaveBeenCalledTimes(2);
  expect(apiPost).toHaveBeenCalledTimes(1);
});

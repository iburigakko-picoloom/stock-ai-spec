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
  vi.mocked(apiGet).mockImplementation(async path=>path==="/api/v1/execution-context" ? {proposal:null,decision:null} : {
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

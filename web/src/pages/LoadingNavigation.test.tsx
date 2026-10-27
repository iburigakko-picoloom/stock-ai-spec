import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { useApiData } from "../hooks";
import { HomePage } from "./HomePage";
import { AssetManagementPage } from "./AssetManagementPage";
import { HistoryPage } from "./HistoryPage";
import { StockDetailPage } from "./StockDetailPage";

vi.mock("../hooks", () => ({useApiData:vi.fn()}));
vi.mock("../mobile/native", () => ({isAndroid:()=>true,StockAI:{}}));
vi.mock("../mobile/DailyPanel", () => ({DailyStatusLink:()=>null}));
vi.mock("../StockMemo", () => ({StockMemo:()=> <p>銘柄メモ</p>}));
afterEach(() => {cleanup();vi.resetAllMocks();});
const result=(data:unknown,loading:boolean,error:string|null=null)=>({data,loading,error,savedAt:null,reload:vi.fn()});

test("home keeps navigation available while the ledger is slow or unavailable",()=>{
  vi.mocked(useApiData).mockReturnValue(result(null,true));
  const view=render(<MemoryRouter><HomePage /></MemoryRouter>);
  expect(screen.getByText("実資産を読み込んでいます")).toBeVisible();
  expect(screen.getByRole("link",{name:/取引を記録/})).toHaveAttribute("href","/today/executions");
  expect(screen.getByRole("link",{name:/資産を管理/})).toHaveAttribute("href","/assets");
  expect(screen.queryByText("保有株はありません。")).not.toBeInTheDocument();
  vi.mocked(useApiData).mockReturnValue(result(null,false,"再確認が必要"));
  view.rerender(<MemoryRouter><HomePage /></MemoryRouter>);
  expect(screen.getByText("再確認が必要")).toBeVisible();
  expect(screen.getByRole("link",{name:/取引履歴/})).toBeVisible();
});

test("assets never claims empty holdings while the ledger is unconfirmed",()=>{
  vi.mocked(useApiData).mockReturnValue(result(null,true));
  const view=render(<MemoryRouter><AssetManagementPage /></MemoryRouter>);
  expect(screen.getByText("保有情報を確認しています。")).toBeVisible();
  expect(screen.queryByText("保存済みの保有株はありません。")).not.toBeInTheDocument();
  vi.mocked(useApiData).mockReturnValue(result(null,false,"failed"));
  view.rerender(<MemoryRouter><AssetManagementPage /></MemoryRouter>);
  expect(screen.getByText("保有情報を確認できません。")).toBeVisible();
  expect(screen.queryByText("保存済みの保有株はありません。")).not.toBeInTheDocument();
});

test("trade history remains visible while refreshing and disappears on verification failure",()=>{
  const records=[{execution_id:"saved",executed_at:"2026-10-26T09:00:00Z",symbol:"7203",account_bucket_id:"bucket",side:"BUY",status:"filled",ordered_shares:100,filled_shares:100,average_fill_price:"1000",actual_commission:"0",actual_other_cost:"0",tax_withheld:"0"}];
  vi.mocked(useApiData).mockReturnValue(result({records,appliedIds:["saved"]},true));
  const view=render(<MemoryRouter initialEntries={["/transactions"]}><HistoryPage /></MemoryRouter>);
  expect(screen.getByText("7203 / bucket")).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("前回の履歴を表示中");
  vi.mocked(useApiData).mockReturnValue(result(null,false,"整合性エラー"));
  view.rerender(<MemoryRouter initialEntries={["/transactions"]}><HistoryPage /></MemoryRouter>);
  expect(screen.getByText("整合性エラー")).toBeVisible();
  expect(screen.queryByText("7203 / bucket")).not.toBeInTheDocument();
});

test("balance history stays visible while a fresh read is pending",()=>{
  const ledger=[{portfolio_id:"old",as_of:"2026-10-26T09:00:00Z",positions:[],cash:[{account_bucket_id:"口座A",available_cash:"1000",reserved_cash:"0"}],applied_execution_ids:[]}];
  vi.mocked(useApiData).mockReturnValue(result(ledger,true));
  render(<MemoryRouter initialEntries={["/assets/history"]}><HistoryPage /></MemoryRouter>);
  expect(screen.getByText("口座A 現金")).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("前回の履歴を表示中");
});

test("stock detail keeps its trade entry and memo available while the forecast is loading",()=>{
  vi.mocked(useApiData).mockReturnValue(result(null,true));
  render(<MemoryRouter initialEntries={["/stocks/7203"]}><Routes><Route path="/stocks/:symbol" element={<StockDetailPage />} /></Routes></MemoryRouter>);
  expect(screen.getByText("銘柄情報を読み込んでいます")).toBeVisible();
  expect(screen.getByRole("link",{name:"この銘柄の取引を記録"})).toHaveAttribute("href","/today/executions?symbol=7203");
  expect(screen.getByText("銘柄メモ")).toBeVisible();
});

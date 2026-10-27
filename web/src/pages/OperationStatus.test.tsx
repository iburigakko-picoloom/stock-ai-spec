import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { useApiData } from "../hooks";
import { DataOperationsPage } from "./DataOperationsPage";

vi.mock("../hooks",()=>({useApiData:vi.fn()}));
vi.mock("../mobile/DailyPanel",()=>({DailyPanel:()=>null}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const result=(data:unknown,loading:boolean,error:string|null=null)=>({data,loading,error,savedAt:null,reload:vi.fn()});
const page=()=> <MemoryRouter initialEntries={["/settings/logs"]}><DataOperationsPage /></MemoryRouter>;

test("status and jobs distinguish refresh, failure and a verified empty result",()=>{
  let status=result({pipelineState:"BLOCKED",blockingReason:"株価不足",businessDate:"2026-10-26"},true);
  let jobs=result([{run_id:"run",started_at:"2026-10-26T09:00:00Z",business_date:"2026-10-26",stage:"history",status:"BLOCKED",reason_code:"MISSING"}],true);
  vi.mocked(useApiData).mockImplementation(path=>path==="/api/v1/status" ? status : jobs);
  const view=render(page());
  expect(screen.getByText("前回の状態を表示中・更新を確認しています。")).toBeVisible();
  expect(screen.getByText("前回の記録を表示中・更新を確認しています。")).toBeVisible();
  expect(screen.getAllByText("株価不足").length).toBeGreaterThan(0);
  expect(screen.getByText("MISSING")).toBeVisible();
  status=result(null,true);jobs=result(null,true);view.rerender(page());
  expect(screen.getByText("停止理由を確認しています。")).toBeVisible();
  expect(screen.getByText("実行記録を確認しています。")).toBeVisible();
  expect(screen.queryByText("保存した停止理由はありません。")).not.toBeInTheDocument();
  expect(screen.queryByText("保存した実行記録はまだありません。")).not.toBeInTheDocument();
  status=result(null,false,"failed");jobs=result(null,false,"failed");view.rerender(page());
  expect(screen.getByText("停止理由を確認できません。")).toBeVisible();
  expect(screen.getByText("実行記録を取得できません。")).toBeVisible();
  expect(screen.queryByText("保存した実行記録はまだありません。")).not.toBeInTheDocument();
  status=result({pipelineState:"IDLE",blockingReason:null,businessDate:"2026-10-26"},false);jobs=result([],false);view.rerender(page());
  expect(screen.getByText("保存した停止理由はありません。")).toBeVisible();
  expect(screen.getByText("保存した実行記録はまだありません。")).toBeVisible();
});

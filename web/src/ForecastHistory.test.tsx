import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ForecastHistory } from "./ForecastHistory";
import { apiGet } from "./api";

vi.mock("./api",()=>({apiGet:vi.fn()}));
vi.mock("./mobile/native",()=>({isAndroid:()=>true,StockAI:{}}));
const history={symbol:"7203",firstDate:"2026-01-01",lastDate:"2026-03-01",forecasts:[
  {runId:"a",kind:"daily",date:"2026-02-02",generatedAt:"2026-02-02T02:30:00Z",return5d:.02,return20d:-.05},
  {runId:"b",kind:"reference",date:"2026-02-02",generatedAt:"2026-02-02T03:30:00Z",return5d:null,return20d:0},
]};
beforeEach(()=>{vi.resetAllMocks();vi.mocked(apiGet).mockResolvedValue(history);});
afterEach(cleanup);

test("shows both periods and separate same-day forecasts without a second action",async()=>{
  const view=render(<ForecastHistory symbol="7203" />);
  const graph=await screen.findByRole("img",{name:"5日と20日の保存予測の推移"});
  expect(graph).toBeVisible();
  expect(apiGet).toHaveBeenCalledWith("/api/v1/mobile/stocks/7203/forecast-history?days=90");
  expect(screen.getByText("5日 未提供 / 20日 0.00%")).toBeVisible();
  fireEvent.click(view.container.querySelectorAll(".forecast-bars-group")[0]);
  expect(screen.getByText("5日 +2.00% / 20日 -5.00%")).toBeVisible();
  fireEvent.change(screen.getByLabelText("数値を見る日"),{target:{value:"reference:b"}});
  expect(screen.getByText("5日 未提供 / 20日 0.00%")).toBeVisible();
  expect(view.container.querySelectorAll("svg rect")).toHaveLength(3);
  expect(screen.queryByRole("button",{name:"5日"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"1か月"}));
  await waitFor(()=>expect(apiGet).toHaveBeenCalledWith("/api/v1/mobile/stocks/7203/forecast-history?days=30"));
});

test("empty and failed histories are explicit and retryable",async()=>{
  vi.mocked(apiGet).mockRejectedValueOnce(new Error("保存内容を確認できません"));
  const view=render(<ForecastHistory symbol="7203" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("保存内容を確認できません");
  vi.mocked(apiGet).mockResolvedValue({...history,forecasts:[]});
  fireEvent.click(screen.getByRole("button",{name:"再読み込み"}));
  expect(await screen.findByText("この期間の保存予測はありません。")).toBeVisible();
  expect(view.queryByRole("img")).not.toBeInTheDocument();
});

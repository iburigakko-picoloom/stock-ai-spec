import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { StockChart } from "./StockChart";
import { apiGet } from "./api";

vi.mock("./api",()=>({apiGet:vi.fn()}));
vi.mock("./mobile/native",()=>({isAndroid:()=>true,StockAI:{}}));

const data={symbol:"7203",firstDate:"2026-02-01",lastDate:"2026-03-01",observedAt:"2026-03-02T00:00:00Z",
  calendar:{"2026-02-02":true,"2026-02-03":true},prices:[{date:"2026-02-02",close:100,volume:1000},{date:"2026-02-03",close:110,volume:500}],
  forecasts:[{runId:"a",kind:"daily",priceDate:"2026-02-02",generatedAt:"2026-02-03T02:30:00Z",horizons:[
    {horizon:5,expectedReturn:.02,return:.03,status:"available",entryDate:"2026-02-03",exitDate:"2026-02-10"},
    {horizon:20,expectedReturn:.05,return:null,status:"pending",entryDate:null,exitDate:null},
  ]}],
};
beforeEach(()=>{vi.resetAllMocks();vi.mocked(apiGet).mockResolvedValue(data);});
afterEach(cleanup);

test("loads only on request and separates actual returns from saved predictions",async()=>{
  render(<StockChart symbol="7203" />);
  expect(apiGet).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"グラフを表示"}));
  expect(await screen.findByRole("img",{name:"保存済み終値と出来高の推移"})).toBeVisible();
  expect(apiGet).toHaveBeenCalledWith("/api/v1/mobile/stocks/7203/chart?days=90");
  expect(screen.getByText(/予測 2.00% \/ 実績 3.00%/)).toBeVisible();
  expect(screen.getByText(/実績期間 2026-02-03〜2026-02-10/)).toBeVisible();
  fireEvent.click(screen.getByRole("button",{name:"20日"}));
  expect(screen.getByText(/予測 5.00% \/ 実績 —（結果待ち）/)).toBeVisible();
  fireEvent.click(screen.getByRole("button",{name:"1か月"}));
  await waitFor(()=>expect(apiGet).toHaveBeenCalledWith("/api/v1/mobile/stocks/7203/chart?days=30"));
});

test("a failed read is visible and can be retried without inventing data",async()=>{
  vi.mocked(apiGet).mockRejectedValueOnce(new Error("保存内容を確認できません"));
  render(<StockChart symbol="7203" />);
  fireEvent.click(screen.getByRole("button",{name:"グラフを表示"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("保存内容を確認できません");
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"再読み込み"}));
  expect(await screen.findByRole("img",{name:"保存済み終値と出来高の推移"})).toBeVisible();
});

test("older saved predictions with an unknown price date remain visible without a fabricated point",async()=>{
  vi.mocked(apiGet).mockResolvedValue({...data,prices:[],forecasts:[{...data.forecasts[0],kind:"archive",priceDate:null,horizons:data.forecasts[0].horizons.map(item=>({...item,return:null,status:"price_date_missing"}))}]});
  render(<StockChart symbol="7203" />);
  fireEvent.click(screen.getByRole("button",{name:"グラフを表示"}));
  expect(await screen.findByText("基準の株価日が未確認")).toBeVisible();
  expect(screen.getByText(/予測 2.00%/)).toBeVisible();
  expect(screen.queryByRole("img",{name:"5営業日予測と実績の比較"})).not.toBeInTheDocument();
});

test("does not connect prices across an unobserved trading day",async()=>{
  vi.mocked(apiGet).mockResolvedValue({...data,calendar:{"2026-02-03":true},prices:[data.prices[0],{...data.prices[1],date:"2026-02-04"}]});
  const view=render(<StockChart symbol="7203" />);
  fireEvent.click(screen.getByRole("button",{name:"グラフを表示"}));
  await screen.findByRole("img",{name:"保存済み終値と出来高の推移"});
  expect(view.container.querySelectorAll('svg[aria-label="保存済み終値と出来高の推移"] line[stroke="#2859a6"]')).toHaveLength(0);
});

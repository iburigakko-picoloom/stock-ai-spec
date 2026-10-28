import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { StockExplanation } from "./StockExplanation";
import { apiGet } from "./api";

vi.mock("./api",()=>({apiGet:vi.fn()}));
vi.mock("./mobile/native",()=>({isAndroid:()=>true,StockAI:{}}));
const snapshotId="a".repeat(64);
const response={symbol:"7203",snapshotId,asOf:"2026-02-03T11:30:00+09:00",method:"one_feature_training_median_replacement_v1",models:[
  {horizon:5,role:"return",available:true,prediction:.01,originalRank:null,
    positive:[{feature:"price.return_5d",difference:.003,rankChange:null}],negative:[{feature:"fundamental.per",difference:-.001,rankChange:null}]},
  {horizon:20,role:"return",available:false},
  {horizon:20,role:"ranking",available:true,prediction:1.2,originalRank:3,
    positive:[{feature:"volume.ratio_20d",difference:.42,rankChange:2}],negative:[]},
]};
beforeEach(()=>{vi.resetAllMocks();vi.mocked(apiGet).mockResolvedValue(response);});
afterEach(cleanup);

test("requests the exact saved snapshot on demand and separates return from ranking units",async()=>{
  render(<StockExplanation symbol="7203" snapshotId={snapshotId}/>);
  expect(apiGet).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"予測の要因を見る"}));
  expect(await screen.findByText("5日の騰落率")).toBeVisible();
  expect(apiGet).toHaveBeenCalledWith(`/api/v1/mobile/stocks/7203/explanation?snapshot=${snapshotId}`);
  expect(screen.getByText("+0.3000パーセントポイント")).toBeVisible();
  expect(screen.getByText("-0.1000パーセントポイント")).toBeVisible();
  fireEvent.click(screen.getByRole("button",{name:"20日・ランキング"}));
  expect(screen.getByText("20日平均に対する出来高")).toBeVisible();
  expect(screen.getByText("+0.4200スコア / 順位2位上")).toBeVisible();
  fireEvent.click(screen.getByRole("button",{name:"20日・値予測"}));
  expect(screen.getByText("このモデルの要因は確認できません。")).toBeVisible();
});

test("does not show a fabricated result after an input mismatch",async()=>{
  vi.mocked(apiGet).mockRejectedValueOnce(new Error("保存時の入力を再現できません"));
  render(<StockExplanation symbol="7203" snapshotId={snapshotId}/>);
  fireEvent.click(screen.getByRole("button",{name:"予測の要因を見る"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("再現できません");
  expect(screen.queryByText("5日の騰落率")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"再読み込み"}));
  await waitFor(()=>expect(screen.getByText("5日の騰落率")).toBeVisible());
});

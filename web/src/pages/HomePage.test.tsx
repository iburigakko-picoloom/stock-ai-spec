import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { apiGet } from "../api";
import { useApiData } from "../hooks";
import { isAndroid } from "../mobile/native";
import type { HoldingView, HomeResponse } from "../types";
import { HomePage } from "./HomePage";

vi.mock("../api",()=>({apiGet:vi.fn()}));
vi.mock("../hooks",()=>({useApiData:vi.fn()}));
vi.mock("../mobile/native",()=>({isAndroid:vi.fn()}));
vi.mock("../mobile/DailyPanel",()=>({DailyStatusLink:()=>null}));
afterEach(()=>{cleanup();vi.resetAllMocks();});

const holding=(overrides:Partial<HoldingView>={}):HoldingView=>({
  symbol:"7203",companyName:"トヨタ",accountBucketId:"tax",shares:200,
  averageAcquisitionPrice:"900",currentPrice:"1000",marketValue:"200000",
  unrealizedPnlAmount:"20000",latestAction:null,recommendedShares:null,proposalId:null,...overrides,
});
const home=(holdings:HoldingView[],portfolioId="ledger-1"):HomeResponse=>({
  portfolioId,holdings,accountLabels:{tax:"特定口座",nisa:"NISA"},runtimeMode:"TEST",
  portfolio:{asOf:"2026-10-27T09:00:00Z",totalAssets:"300000",cashValue:"0",equityValue:"300000",holdingsCount:holdings.length},blockingReason:null,
});
function show(data:HomeResponse){
  vi.mocked(useApiData).mockReturnValue({data,loading:false,error:null,savedAt:null,reload:vi.fn()});
  return render(<MemoryRouter><HomePage /></MemoryRouter>);
}
function metric(article:HTMLElement,label:string){
  return within(article).getByText(label).parentElement!;
}

test("same-symbol accounts show weighted acquisition, saved price and unrealized gain",()=>{
  vi.mocked(isAndroid).mockReturnValue(false);
  show(home([holding(),holding({accountBucketId:"nisa",shares:100,averageAcquisitionPrice:"800",marketValue:"100000"})]));
  const article=screen.getByRole("link",{name:/トヨタ/}).closest("article")!;
  expect(within(article).getByText("7203")).toBeVisible();
  expect(within(article).getByText("300株")).toBeVisible();
  expect(metric(article,"平均取得単価")).toHaveTextContent("¥866.67");
  expect(metric(article,"現在値")).toHaveTextContent("¥1,000");
  expect(metric(article,"現在値")).toHaveTextContent("保存値");
  expect(metric(article,"評価損益")).toHaveTextContent("+¥40,000");
  expect(metric(article,"損益率")).toHaveTextContent("+15.38%");
  expect(within(article).getByText(/NISA · 100株/)).toBeVisible();
  expect(screen.getByText(/取得済み終値または保存株価/)).toBeVisible();
});

test("loss, unavailable acquisition cost and zero-cost percentage are not misrepresented",()=>{
  vi.mocked(isAndroid).mockReturnValue(false);
  show(home([
    holding({symbol:"1111",companyName:"損失会社",shares:100,averageAcquisitionPrice:"1000",currentPrice:"900"}),
    holding({symbol:"2222",companyName:"未確認会社",shares:10,averageAcquisitionPrice:"",currentPrice:"1000"}),
    holding({symbol:"3333",companyName:"無償取得会社",shares:10,averageAcquisitionPrice:"0",currentPrice:"100"}),
    holding({symbol:"4444",companyName:"株価未確認会社",shares:10,averageAcquisitionPrice:"100",currentPrice:""}),
  ]));
  const loss=screen.getByRole("link",{name:/損失会社/}).closest("article")!;
  expect(metric(loss,"評価損益")).toHaveTextContent("−¥10,000");
  expect(metric(loss,"損益率")).toHaveTextContent("−10.00%");
  const missing=screen.getByRole("link",{name:/^未確認会社/}).closest("article")!;
  expect(metric(missing,"平均取得単価")).toHaveTextContent("未確認");
  expect(metric(missing,"現在値")).toHaveTextContent("¥1,000");
  expect(metric(missing,"評価損益")).toHaveTextContent("未確認");
  expect(within(missing).getByText("10株")).toBeVisible();
  const free=screen.getByRole("link",{name:/無償取得会社/}).closest("article")!;
  expect(metric(free,"評価損益")).toHaveTextContent("+¥1,000");
  expect(metric(free,"損益率")).toHaveTextContent("未確認");
  const missingPrice=screen.getByRole("link",{name:/株価未確認会社/}).closest("article")!;
  expect(metric(missingPrice,"平均取得単価")).toHaveTextContent("¥100");
  expect(metric(missingPrice,"現在値")).toHaveTextContent("未確認");
  expect(metric(missingPrice,"評価損益")).toHaveTextContent("未確認");
});

test("different saved prices remain distinguishable by account",()=>{
  vi.mocked(isAndroid).mockReturnValue(false);
  show(home([holding({shares:100}),holding({accountBucketId:"nisa",shares:100,currentPrice:"1100"})]));
  const article=screen.getByRole("link",{name:/トヨタ/}).closest("article")!;
  expect(metric(article,"現在値")).toHaveTextContent("口座ごとに異なる");
  expect(metric(article,"評価損益")).toHaveTextContent("+¥30,000");
  expect(within(article).getByText(/保存株価 ¥1,100/)).toBeVisible();
});

test("names are loaded after balances and stale responses cannot relabel another ledger",async()=>{
  vi.mocked(isAndroid).mockReturnValue(true);
  let finishFirst!:(value:unknown)=>void, finishSecond!:(value:unknown)=>void;
  vi.mocked(apiGet).mockReturnValueOnce(new Promise(resolve=>{finishFirst=resolve;}))
    .mockReturnValueOnce(new Promise(resolve=>{finishSecond=resolve;}));
  const first=home([holding({companyName:"7203"})],"ledger-1");
  const view=show(first);
  expect(screen.getByRole("link",{name:/銘柄名未確認/})).toBeVisible();
  expect(screen.getByText("+¥20,000")).toBeVisible();
  await waitFor(()=>expect(apiGet).toHaveBeenCalledTimes(1));
  vi.mocked(useApiData).mockReturnValue({data:home([holding({companyName:"7203"})],"ledger-2"),loading:false,error:null,savedAt:null,reload:vi.fn()});
  view.rerender(<MemoryRouter><HomePage /></MemoryRouter>);
  await act(async()=>finishFirst({portfolioId:"ledger-1",names:{"7203":"古い名前"}}));
  expect(screen.queryByText(/古い名前/)).not.toBeInTheDocument();
  await waitFor(()=>expect(apiGet).toHaveBeenCalledTimes(2));
  await act(async()=>finishSecond({portfolioId:"ledger-2",names:{"7203":"トヨタ自動車"},prices:{"7203":"1100.5"},priceDate:"2026-10-27"}));
  const article=screen.getByRole("link",{name:/トヨタ自動車/}).closest("article")!;
  expect(metric(article,"現在値")).toHaveTextContent("¥1,100.5");
  expect(metric(article,"現在値")).toHaveTextContent("2026-10-27 終値");
  expect(metric(article,"評価損益")).toHaveTextContent("+¥40,100");
});

test("an older market close never replaces the saved ledger price",async()=>{
  vi.mocked(isAndroid).mockReturnValue(true);
  vi.mocked(apiGet).mockResolvedValue({portfolioId:"ledger-1",names:{"7203":"トヨタ自動車"},prices:{"7203":"1"},priceDate:"2026-01-05"});
  show(home([holding({companyName:"7203"})]));
  const article=(await screen.findByRole("link",{name:/トヨタ自動車/})).closest("article")!;
  expect(metric(article,"現在値")).toHaveTextContent("¥1,000");
  expect(metric(article,"現在値")).toHaveTextContent("保存値");
  expect(metric(article,"評価損益")).toHaveTextContent("+¥20,000");
});

test("a known initial price date allows its same-day close even when ledger time is later",async()=>{
  vi.mocked(isAndroid).mockReturnValue(true);
  vi.mocked(apiGet).mockResolvedValue({portfolioId:"ledger-1",names:{},prices:{"7203":"1100"},priceDate:"2026-10-26"});
  const data=home([holding()]);
  data.initialLedger={confirmedAt:"2026-10-27T09:00:00Z",referencePriceDate:"2026-10-26"};
  show(data);
  await waitFor(()=>expect(metric(screen.getByRole("link",{name:/トヨタ/}).closest("article")!,"現在値")).toHaveTextContent("2026-10-26 終値"));
  expect(screen.getByText("+¥40,000")).toBeVisible();
});

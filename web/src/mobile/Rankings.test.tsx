import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiGet, apiPost } from "../api";
import { useApiData } from "../hooks";
import { MemoryRouter } from "react-router-dom";
import { Rankings } from "./Rankings";

vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("../hooks", () => ({ useApiData: vi.fn() }));
vi.mock("./ReferenceAnalysis", () => ({ ReferenceAnalysis: () => <button>ランキングを更新</button> }));
const reload = vi.fn();
const base = { id: "snapshot-a", generatedAt: "2026-10-23T12:00:00+09:00", priceDate: "2026-10-22", rows: [
  { symbol: "1000", modelRank: 1, score: 1, expectedReturn: .04 },
  { symbol: "2000", modelRank: 2, score: 0, expectedReturn: .01 },
], total: 2, answer: null, holdingSymbols: ["1000"], metrics: { "1000": { return5d: .04, return20d: .04, rank20d: 1 }, "2000": { return5d: .01, return20d: .01, rank20d: 0 } } };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(useApiData).mockReturnValue({ data: base, loading: false, error: null, savedAt: null, reload });
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

test("shows and searches the full prediction population while retaining the consultation subset",()=>{
  const full=[...base.rows.map(row=>({...row,companyName:`企業${row.symbol}`})),
    {symbol:"3000",companyName:"対象外ではない企業",modelRank:3,score:-1,expectedReturn:-.01}];
  vi.mocked(useApiData).mockReturnValue({data:{...base,displayRows:full,total:3},loading:false,error:null,savedAt:null,reload});
  render(<MemoryRouter><Rankings /></MemoryRouter>);
  expect(screen.getByText("3 / 3銘柄")).toBeVisible();
  fireEvent.change(screen.getByRole("searchbox"),{target:{value:"対象外ではない企業"}});
  expect(screen.getByText("対象外ではない企業")).toBeVisible();
  expect(screen.getByText("1 / 3銘柄")).toBeVisible();
});

test("saved ranking archive remains readable without import or adoption actions", () => {
  vi.mocked(useApiData).mockReturnValue({ data: { ...base, answer: { order: [
    { symbol: "2000", reason: "相談で優先" }, { symbol: "1000", reason: "比較後の順位" },
  ] } }, loading: false, error: null, savedAt: null, reload });
  render(<MemoryRouter><Rankings /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "20日・ランキング" }));
  expect(screen.getByText(/2026-10-22 終値/)).toBeVisible();
  expect(screen.queryByRole("tab", { name: "保存済みChatGPT" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "過去の相談記録" }));
  fireEvent.click(screen.getByRole("tab", { name: "保存済みChatGPT" }));
  expect(screen.getByText(/ChatGPTの回答を反映した順位/)).toBeVisible();
  expect(screen.getByText("相談で優先")).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: "モデル" }));
  expect(screen.queryByText("相談で優先")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "ランキングを更新" })).toBeEnabled();
});

test("archive retains old findings but cannot submit, validate or adopt a response", () => {
  vi.mocked(useApiData).mockReturnValue({data:{...base,savedInput:{id:"old",rankingId:base.id,prompt:"以前の相談",canCopy:false},research:{researchId:"saved",order:[],savedAt:"2026-10-24"}},loading:false,error:null,savedAt:null,reload});
  render(<MemoryRouter><Rankings /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button",{name:"20日・ランキング"}));
  fireEvent.click(screen.getByRole("button",{name:"過去の相談記録"}));
  expect(screen.getByLabelText("ChatGPTへの相談文")).toHaveValue("以前の相談");
  expect(screen.getByRole("button",{name:"相談文をコピー"})).toBeDisabled();
  expect(screen.getByText("保存した調査結果")).toBeVisible();
  expect(screen.queryByLabelText("回答JSON")).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"調査結果を保存"})).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"最新の条件で確認して反映"})).not.toBeInTheDocument();
  expect(apiPost).not.toHaveBeenCalled();
});

test("reopened input is available but changed ranking prevents stale clipboard export", async () => {
  vi.mocked(useApiData).mockReturnValue({ data: { ...base, savedInput: { id: base.id, prompt: "保存済み相談", expiresAt: "2026-10-27",responseMode:"chatgpt-readable-report-v1" } }, loading: false, error: null, savedAt: null, reload });
  vi.mocked(apiGet).mockResolvedValue({ ...base, id: "changed" });
  render(<MemoryRouter><Rankings /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "20日・ランキング" }));
  fireEvent.click(screen.getByRole("button", { name: "ChatGPTと相談" }));
  expect(screen.getByLabelText("ChatGPTへの相談文")).toHaveValue("保存済み相談");
  fireEvent.click(screen.getByRole("button", { name: "相談文をコピー" }));
  expect(await screen.findByRole("status")).toHaveTextContent("更新されています");
});

test("new ranking consultation copies the readable report prompt without importing an answer",async()=>{
  const exported={id:"report-input",rankingId:base.id,prompt:"本文と表で分析する相談文",expiresAt:"2026-10-27",canCopy:true,responseMode:"chatgpt-readable-report-v1"};
  const clipboard=vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator",{clipboard:{writeText:clipboard}});
  vi.mocked(apiPost).mockResolvedValue(exported);
  vi.mocked(apiGet).mockResolvedValue({...base,savedInput:exported});
  render(<MemoryRouter><Rankings /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button",{name:"20日・ランキング"}));
  fireEvent.click(screen.getByRole("button",{name:"ChatGPTと相談"}));
  for(const checkbox of screen.getAllByRole("checkbox"))fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button",{name:"相談文を作る"}));
  expect(await screen.findByLabelText("ChatGPTへの相談文")).toHaveValue(exported.prompt);
  fireEvent.click(screen.getByRole("button",{name:"相談文をコピー"}));
  await waitFor(()=>expect(clipboard).toHaveBeenCalledExactlyOnceWith(exported.prompt));
  expect(screen.getByRole("link",{name:"ChatGPTを開く"})).toHaveAttribute("href","https://chatgpt.com/");
  expect(screen.queryByLabelText("回答JSON")).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"調査結果を保存"})).not.toBeInTheDocument();
  expect(apiPost).toHaveBeenCalledExactlyOnceWith("/api/v1/mobile/ranking/20d/export",expect.anything());
  vi.unstubAllGlobals();
});

 test("search keeps the actual rank instead of renumbering filtered rows", () => {
  render(<MemoryRouter><Rankings /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "20日・ランキング" }));
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "2000" } });
  expect(screen.getByLabelText("2位")).toBeVisible();
  expect(screen.queryByText("1000")).not.toBeInTheDocument();
});

test("three model tabs separate rank scores from returns and preserve search ranks", () => {
  vi.mocked(useApiData).mockReturnValue({ data: { ...base, rows: [
    { symbol: "1000", modelRank: 1, score: 9, expectedReturn: -.01 },
    { symbol: "2000", modelRank: 2, score: 2, expectedReturn: .05 },
    { symbol: "3000", modelRank: 3, score: 1, expectedReturn: null },
  ] }, loading: false, error: null, savedAt: null, reload });
  render(<MemoryRouter><Rankings /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "20日・ランキング" }));
  for (const name of ["20日・ランキング", "20日・値予測", "5日・値予測"]) expect(screen.getByRole("button", { name })).toBeVisible();
  for (const name of ["20日・値予測", "5日・値予測"]) {
    fireEvent.click(screen.getByRole("button", { name }));
    expect(screen.getByText(/日の予測リターンが高い順/)).toBeVisible();
    expect(screen.getByText("2000").closest(".ranking-table-row")?.querySelector(".ranking-position")).toHaveAttribute("aria-label", "1位");
    expect(screen.getByText("1000").closest(".ranking-table-row")?.querySelector(".ranking-position")).toHaveAttribute("aria-label", "2位");
    expect(screen.getByText("3000").closest(".ranking-table-row")?.querySelector(".ranking-position")).toHaveAttribute("aria-label", "—");
    expect(screen.queryByRole("button", { name: "ChatGPTと相談" })).not.toBeInTheDocument();
  }
  fireEvent.click(screen.getByRole("button", { name: "20日・ランキング" }));
  expect(screen.getByText("1000").closest(".ranking-table-row")?.querySelector(".ranking-position")).toHaveAttribute("aria-label", "1位");
  expect(screen.getByRole("button", { name: "ChatGPTと相談" })).toBeEnabled();
});


test("holding and search filters keep model ranks and a refreshed result changes their order", () => {
  const view = render(<MemoryRouter><Rankings /></MemoryRouter>);
  fireEvent.click(screen.getByRole("checkbox", { name:"保有銘柄のみ" }));
  expect(screen.getByText("1000").closest(".ranking-table-row")?.querySelector(".ranking-position")).toHaveAttribute("aria-label", "1位");
  expect(screen.queryByText("2000")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name:"保有銘柄のみ" }));
  fireEvent.change(screen.getByRole("searchbox"), { target:{ value:"2000" } });
  expect(screen.getByText("2000").closest(".ranking-table-row")?.querySelector(".ranking-position")).toHaveAttribute("aria-label", "2位");
  vi.mocked(useApiData).mockReturnValue({data:{...base,rows:[
    {...base.rows[0],expectedReturn:.01}, {...base.rows[1],expectedReturn:.05},
  ]},loading:false,error:null,savedAt:null,reload});
  view.rerender(<MemoryRouter><Rankings /></MemoryRouter>);
  expect(screen.getByText("2000").closest(".ranking-table-row")?.querySelector(".ranking-position")).toHaveAttribute("aria-label", "1位");
});

test("loads missing company names without changing ranks and supports name search", async () => {
  vi.mocked(useApiData).mockReturnValue({data:{...base,snapshotId:"snapshot-a"},loading:false,error:null,savedAt:null,reload});
  vi.mocked(apiGet).mockResolvedValue({snapshotId:"snapshot-a",names:{"1000":"合成企業甲","2000":"合成企業乙"}});
  render(<MemoryRouter><Rankings /></MemoryRouter>);
  expect(await screen.findByText("合成企業乙")).toBeVisible();
  expect(screen.getByText("合成企業乙").closest(".ranking-table-row")).toHaveTextContent("2000");
  fireEvent.change(screen.getByRole("searchbox"),{target:{value:"合成企業乙"}});
  expect(screen.getByLabelText("2位")).toBeVisible();
  expect(screen.queryByText("合成企業甲")).not.toBeInTheDocument();
  expect(apiGet).toHaveBeenCalledWith("/api/v1/mobile/ranking/5d/names");
});

test("ignores names from a different forecast snapshot", async () => {
  vi.mocked(useApiData).mockReturnValue({data:{...base,snapshotId:"new"},loading:false,error:null,savedAt:null,reload});
  vi.mocked(apiGet).mockResolvedValue({snapshotId:"old",names:{"1000":"古い銘柄名"}});
  render(<MemoryRouter><Rankings /></MemoryRouter>);
  await waitFor(()=>expect(apiGet).toHaveBeenCalled());
  expect(screen.queryByText("古い銘柄名")).not.toBeInTheDocument();
  expect(screen.getByText("1000")).toBeVisible();
  expect(await screen.findByText("一部の銘柄名を確認できませんでした。銘柄コードを表示しています。")).toBeVisible();
});

test("does not start a name lookup after leaving before the first paint", async () => {
  vi.useFakeTimers();
  let next=0;const frames=new Map<number,FrameRequestCallback>();
  const request=vi.spyOn(window,"requestAnimationFrame").mockImplementation(callback=>{frames.set(++next,callback);return next;});
  const cancel=vi.spyOn(window,"cancelAnimationFrame").mockImplementation(id=>{frames.delete(id);});
  try {
    vi.mocked(useApiData).mockReturnValue({data:{...base,snapshotId:"snapshot-a"},loading:false,error:null,savedAt:null,reload});
    vi.mocked(apiGet).mockResolvedValue({snapshotId:"snapshot-a",names:{}});
    const view=render(<MemoryRouter><Rankings /></MemoryRouter>);
    expect(screen.getByText("1000")).toBeVisible();
    expect(apiGet).not.toHaveBeenCalled();
    view.unmount();
    await act(async()=>{await vi.advanceTimersByTimeAsync(200);});
    expect(frames.size).toBe(0);
    expect(apiGet).not.toHaveBeenCalled();
  } finally { request.mockRestore();cancel.mockRestore();vi.useRealTimers(); }
});

test.each(["frames", "timer"])("starts one name lookup after %s and never duplicates it", async trigger => {
  vi.useFakeTimers();
  let next=0;const frames=new Map<number,FrameRequestCallback>();
  const request=vi.spyOn(window,"requestAnimationFrame").mockImplementation(callback=>{frames.set(++next,callback);return next;});
  const cancel=vi.spyOn(window,"cancelAnimationFrame").mockImplementation(id=>{frames.delete(id);});
  const tick=()=>act(()=>{const [id,callback]=frames.entries().next().value!;frames.delete(id);callback(0);});
  try {
    vi.mocked(useApiData).mockReturnValue({data:{...base,snapshotId:"snapshot-a"},loading:false,error:null,savedAt:null,reload});
    vi.mocked(apiGet).mockResolvedValue({snapshotId:"snapshot-a",names:{"1000":"合成企業甲"}});
    const view=render(<MemoryRouter><Rankings /></MemoryRouter>);
    expect(apiGet).not.toHaveBeenCalled();
    if(trigger==="frames") { tick();tick(); } else await act(async()=>{await vi.advanceTimersByTimeAsync(120);});
    await act(async()=>{await Promise.resolve();await vi.advanceTimersByTimeAsync(200);});
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(screen.getByText("合成企業甲")).toBeVisible();
    view.unmount();
  } finally { request.mockRestore();cancel.mockRestore();vi.useRealTimers(); }
});

test("defers a pending name lookup while the app is hidden", async () => {
  vi.useFakeTimers();
  let state:DocumentVisibilityState="visible";
  const visibility=vi.spyOn(document,"visibilityState","get").mockImplementation(()=>state);
  const request=vi.spyOn(window,"requestAnimationFrame").mockImplementation(()=>1);
  const cancel=vi.spyOn(window,"cancelAnimationFrame").mockImplementation(()=>{});
  try {
    vi.mocked(useApiData).mockReturnValue({data:{...base,snapshotId:"snapshot-a"},loading:false,error:null,savedAt:null,reload});
    vi.mocked(apiGet).mockResolvedValue({snapshotId:"snapshot-a",names:{"1000":"合成企業甲"}});
    const view=render(<MemoryRouter><Rankings /></MemoryRouter>);
    state="hidden";act(()=>document.dispatchEvent(new Event("visibilitychange")));
    await act(async()=>{await vi.advanceTimersByTimeAsync(500);});
    expect(apiGet).not.toHaveBeenCalled();
    state="visible";act(()=>document.dispatchEvent(new Event("visibilitychange")));
    await act(async()=>{await vi.advanceTimersByTimeAsync(120);});
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(screen.getByText("合成企業甲")).toBeVisible();
    view.unmount();
  } finally { visibility.mockRestore();request.mockRestore();cancel.mockRestore();vi.useRealTimers(); }
});

test("shows only top 20 but searches all analyzed stocks and preserves their rank", () => {
  const rows=Array.from({length:150},(_,index)=>({symbol:String(1000+index),modelRank:index+1,score:150-index,expectedReturn:(150-index)/10000}));
  vi.mocked(useApiData).mockReturnValue({data:{...base,rows,total:rows.length,holdingSymbols:["1149"]},loading:false,error:null,savedAt:null,reload});
  const view=render(<MemoryRouter><Rankings /></MemoryRouter>);
  expect(view.container.querySelectorAll(".ranking-table-row")).toHaveLength(20);
  expect(screen.getByText("上位20件 · 20 / 150銘柄")).toBeVisible();
  expect(screen.queryByText("1149")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox"),{target:{value:"1149"}});
  expect(screen.getByText("1 / 150銘柄")).toBeVisible();
  expect(screen.getByLabelText("150位")).toBeVisible();
  fireEvent.change(screen.getByRole("searchbox"),{target:{value:""}});
  expect(view.container.querySelectorAll(".ranking-table-row")).toHaveLength(20);
  expect(screen.queryByLabelText("150位")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox",{name:"保有銘柄のみ"}));
  expect(screen.getByText("1 / 150銘柄")).toBeVisible();
  expect(screen.getByLabelText("150位")).toBeVisible();
  view.unmount();
});

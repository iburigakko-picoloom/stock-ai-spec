import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { apiGet, apiPost } from "./api";
import { useApiData } from "./hooks";
import { StockMemo } from "./StockMemo";
import { StockDetailPage } from "./pages/StockDetailPage";

vi.mock("./api",()=>({apiGet:vi.fn(),apiPost:vi.fn()}));
vi.mock("./hooks",()=>({useApiData:vi.fn()}));
const base={symbol:"7203",text:"保存したメモ",revision:"a".repeat(64),updatedAt:"2026-10-26T09:00:00Z"};
beforeEach(()=>{vi.resetAllMocks();vi.mocked(apiGet).mockResolvedValue(base);});
afterEach(cleanup);

test("saves the exact private text with its revision and displays the result in place",async()=>{
  const saved={...base,text:" 次の決算を確認\n為替リスク 📝\n",revision:"b".repeat(64)};
  vi.mocked(apiPost).mockResolvedValue(saved);
  render(<StockMemo symbol="7203" />);
  const field=await screen.findByRole("textbox",{name:"メモ"});
  await waitFor(()=>expect(field).toHaveValue(base.text));
  fireEvent.change(field,{target:{value:saved.text}});
  fireEvent.click(screen.getByRole("button",{name:"メモを保存"}));
  expect(await screen.findByText("メモを保存しました。")).toBeVisible();
  expect(apiPost).toHaveBeenCalledExactlyOnceWith("/api/v1/stocks/7203/note",{text:saved.text,expectedRevision:base.revision});
  expect(field).toHaveValue(saved.text);
  expect(screen.getByRole("button",{name:"メモを保存"})).toBeDisabled();
});

test("a rejected concurrent save preserves the draft and requires an explicit choice",async()=>{
  const other={...base,text:"別画面のメモ",revision:"b".repeat(64)};
  vi.mocked(apiGet).mockResolvedValueOnce(base).mockResolvedValueOnce(other);
  vi.mocked(apiPost).mockRejectedValueOnce(new Error("メモが別の画面で更新されています"));
  render(<StockMemo symbol="7203" />);
  const field=await screen.findByRole("textbox",{name:"メモ"});
  await waitFor(()=>expect(field).toHaveValue(base.text));
  fireEvent.change(field,{target:{value:"残したい下書き"}});
  fireEvent.click(screen.getByRole("button",{name:"メモを保存"}));
  expect(await screen.findByText(other.text)).toBeVisible();
  expect(field).toHaveValue("残したい下書き");
  vi.mocked(apiPost).mockResolvedValueOnce({...other,text:"残したい下書き",revision:"c".repeat(64)});
  fireEvent.click(screen.getByRole("button",{name:"自分の入力を残して編集を続ける"}));
  fireEvent.click(screen.getByRole("button",{name:"メモを保存"}));
  await waitFor(()=>expect(apiPost).toHaveBeenLastCalledWith("/api/v1/stocks/7203/note",{text:"残したい下書き",expectedRevision:other.revision}));
});

test("failure and retry keep the original revision and exact draft",async()=>{
  vi.mocked(apiPost).mockRejectedValueOnce(new Error("応答を確認できません"));
  render(<StockMemo symbol="7203" />);
  const field=await screen.findByRole("textbox",{name:"メモ"});
  await waitFor(()=>expect(field).toHaveValue(base.text));
  fireEvent.change(field,{target:{value:"通信後も残す"}});
  fireEvent.click(screen.getByRole("button",{name:"メモを保存"}));
  await screen.findByRole("alert");
  expect(field).toHaveValue("通信後も残す");
  vi.mocked(apiPost).mockResolvedValueOnce({...base,text:"通信後も残す",revision:"b".repeat(64)});
  await waitFor(()=>expect(screen.getByRole("button",{name:"メモを保存"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"メモを保存"}));
  await screen.findByText("メモを保存しました。");
  expect(vi.mocked(apiPost).mock.calls[0]).toEqual(vi.mocked(apiPost).mock.calls[1]);
});

test("read failure can be retried without a new page or a placeholder note",async()=>{
  vi.mocked(apiGet).mockRejectedValueOnce(new Error("読込失敗")).mockResolvedValueOnce(base);
  render(<StockMemo symbol="7203" />);
  fireEvent.click(await screen.findByRole("button",{name:"メモを再読込"}));
  await waitFor(()=>expect(screen.getByRole("textbox",{name:"メモ"})).toHaveValue(base.text));
  expect(apiPost).not.toHaveBeenCalled();
});

test("financial detail refresh does not unmount or overwrite a note draft",async()=>{
  const detail={symbol:"7203",positions:[],proposalLines:[],forecast:null,chatgptResearch:[],researchRuns:[],proposal:null};
  vi.mocked(useApiData).mockReturnValue({data:detail,error:null,loading:false,savedAt:null,reload:vi.fn()});
  const page=<MemoryRouter initialEntries={["/stocks/7203"]}><Routes><Route path="/stocks/:symbol" element={<StockDetailPage />} /></Routes></MemoryRouter>;
  const view=render(page);
  const field=await screen.findByRole("textbox",{name:"メモ"});
  await waitFor(()=>expect(field).toHaveValue(base.text));
  fireEvent.change(field,{target:{value:"編集中のメモ"}});
  vi.mocked(useApiData).mockReturnValue({data:null,error:"金融情報の読込失敗",loading:false,savedAt:null,reload:vi.fn()});
  view.rerender(page);
  expect(screen.getByRole("textbox",{name:"メモ"})).toHaveValue("編集中のメモ");
  expect(apiGet).toHaveBeenCalledTimes(1);
});

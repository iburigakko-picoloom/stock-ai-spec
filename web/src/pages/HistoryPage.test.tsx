import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { useApiData } from "../hooks";
import { HistoryPage } from "./HistoryPage";

vi.mock("../hooks", () => ({useApiData:vi.fn()}));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

test("trade history distinguishes applied, unapplied and unfilled records in both list and detail",()=>{
  const row={executed_at:"2026-10-26T09:00:00Z",symbol:"7203",account_bucket_id:"bucket",side:"BUY",status:"filled",ordered_shares:100,filled_shares:100,average_fill_price:"1000",actual_commission:"0",actual_other_cost:"0",tax_withheld:"0"};
  const records=[{...row,execution_id:"applied"},{...row,execution_id:"pending"},{...row,execution_id:"unfilled",filled_shares:0,status:"cancelled"}];
  vi.mocked(useApiData).mockReturnValue({data:{records,appliedIds:["applied"]},loading:false,error:null,savedAt:null,reload:vi.fn()});
  render(<MemoryRouter initialEntries={["/transactions"]}><HistoryPage /></MemoryRouter>);
  expect(screen.getByText("残高へ反映済み")).toBeVisible();
  expect(screen.getByText("残高へ未反映")).toBeVisible();
  expect(screen.getByText("残高の変更なし")).toBeVisible();
  const rows=screen.getAllByRole("row");
  fireEvent.click(within(rows[3]).getByRole("button",{name:"記録を確認"}));
  expect(screen.getByText("反映済み",{selector:"dd"})).toBeVisible();
  fireEvent.click(within(rows[2]).getByRole("button",{name:"記録を確認"}));
  expect(screen.getByText("未反映",{selector:"dd"})).toBeVisible();
});

test("balance history compares each symbol and account with the previous snapshot",async()=>{
  const position=(symbol:string, account_bucket_id:string, shares:number)=>({symbol,account_bucket_id,shares,average_acquisition_price:"1000"});
  const base={as_of:"2026-10-26T09:00:00Z",cash:[],applied_execution_ids:[]};
  const data=[
    {...base,portfolio_id:"new",positions:[position("7203","A",200),position("7203","B",100),position("9984","A",50)]},
    {...base,portfolio_id:"old",positions:[position("7203","A",100),position("7203","B",0)]},
  ];
  vi.mocked(useApiData).mockReturnValue({data,loading:false,error:null,savedAt:null,reload:vi.fn()});
  const view=render(<MemoryRouter initialEntries={["/assets/history"]}><HistoryPage /></MemoryRouter>);
  expect(screen.getByText(/7203 \/ A 100 → 200株/)).toBeVisible();
  expect(screen.getByText(/7203 \/ B 0 → 100株/)).toBeVisible();
  expect(screen.getByText(/9984 \/ A — → 50株/)).toBeVisible();
  expect(await screen.findByText("初回残高")).toBeVisible();
  const updated=[data[0],{...data[1],positions:[position("7203","A",150)]}];
  vi.mocked(useApiData).mockReturnValue({data:updated,loading:true,error:null,savedAt:null,reload:vi.fn()});
  view.rerender(<MemoryRouter initialEntries={["/assets/history"]}><HistoryPage /></MemoryRouter>);
  expect(screen.getByText(/7203 \/ A 150 → 200株/)).toBeVisible();
  expect(screen.getByText(/7203 \/ B — → 100株/)).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("前回の履歴を表示中");
});

test("balance history paints the newest record first and automatically renders the rest",()=>{
  const base={as_of:"2026-10-26T09:00:00Z",positions:[],cash:[],applied_execution_ids:[]};
  const data=[{...base,portfolio_id:"new",correctionRecord:{date:"最新",reason:"",kind:"deposit"}},
    {...base,portfolio_id:"middle",correctionRecord:{date:"中間",reason:"",kind:"deposit"}},
    {...base,portfolio_id:"old",correctionRecord:{date:"最初",reason:"",kind:"deposit"}}];
  let next=0; const frames=new Map<number,FrameRequestCallback>();
  const request=vi.spyOn(window,"requestAnimationFrame").mockImplementation(callback=>{frames.set(++next,callback);return next;});
  const cancel=vi.spyOn(window,"cancelAnimationFrame").mockImplementation(id=>{frames.delete(id);});
  const tick=()=>act(()=>{const [id,callback]=frames.entries().next().value!;frames.delete(id);callback(0);});
  vi.mocked(useApiData).mockReturnValue({data,loading:false,error:null,savedAt:null,reload:vi.fn()});
  const view=render(<MemoryRouter initialEntries={["/assets/history"]}><HistoryPage /></MemoryRouter>);
  expect(screen.getByText("最新")).toBeVisible();
  expect(screen.queryByText("中間")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("残りの履歴を表示しています");
  tick(); tick();
  expect(screen.getByText("中間")).toBeVisible();
  expect(screen.queryByText("最初")).not.toBeInTheDocument();
  tick(); tick();
  expect(screen.getByText("最初")).toBeVisible();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  view.unmount(); request.mockRestore(); cancel.mockRestore();
});

test("balance history cancels pending display work when the read fails",()=>{
  const base={as_of:"2026-10-26T09:00:00Z",positions:[],cash:[],applied_execution_ids:[]};
  const data=[{...base,portfolio_id:"one"},{...base,portfolio_id:"two"}];
  const frames=new Map<number,FrameRequestCallback>();let next=0;
  const request=vi.spyOn(window,"requestAnimationFrame").mockImplementation(callback=>{frames.set(++next,callback);return next;});
  const cancel=vi.spyOn(window,"cancelAnimationFrame").mockImplementation(id=>{frames.delete(id);});
  vi.mocked(useApiData).mockReturnValue({data,loading:false,error:null,savedAt:null,reload:vi.fn()});
  const view=render(<MemoryRouter initialEntries={["/assets/history"]}><HistoryPage /></MemoryRouter>);
  expect(frames.size).toBe(1);
  vi.mocked(useApiData).mockReturnValue({data:null,loading:false,error:"読み取り失敗",savedAt:null,reload:vi.fn()});
  view.rerender(<MemoryRouter initialEntries={["/assets/history"]}><HistoryPage /></MemoryRouter>);
  expect(screen.getByText("読み取り失敗")).toBeVisible();
  expect(screen.queryByText("残りの履歴を表示しています…")).not.toBeInTheDocument();
  expect(frames.size).toBe(0);
  view.unmount();request.mockRestore();cancel.mockRestore();
});

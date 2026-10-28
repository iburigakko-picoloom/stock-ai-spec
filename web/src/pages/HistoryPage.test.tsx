import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { useApiData } from "../hooks";
import { HistoryPage } from "./HistoryPage";

vi.mock("../hooks", () => ({useApiData:vi.fn()}));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

test("trade history distinguishes applied, unapplied and unfilled records in both list and detail",async()=>{
  const row={executed_at:"2026-10-26T09:00:00Z",symbol:"7203",account_bucket_id:"bucket",side:"BUY",status:"filled",ordered_shares:100,filled_shares:100,average_fill_price:"1000",actual_commission:"0",actual_other_cost:"0",tax_withheld:"0"};
  const records=[{...row,execution_id:"applied"},{...row,execution_id:"pending"},{...row,execution_id:"unfilled",filled_shares:0,status:"cancelled"}];
  vi.mocked(useApiData).mockReturnValue({data:{records,appliedIds:["applied"]},loading:false,error:null,savedAt:null,reload:vi.fn()});
  render(<MemoryRouter initialEntries={["/transactions"]}><HistoryPage /></MemoryRouter>);
  expect(await screen.findByText("残高へ反映済み")).toBeVisible();
  expect(screen.getByText("残高へ未反映")).toBeVisible();
  expect(screen.getByText("残高の変更なし")).toBeVisible();
  const rows=screen.getAllByRole("row");
  fireEvent.click(within(rows[3]).getByRole("button",{name:"記録を確認"}));
  expect(screen.getByText("反映済み",{selector:"dd"})).toBeVisible();
  fireEvent.click(within(rows[2]).getByRole("button",{name:"記録を確認"}));
  expect(screen.getByText("未反映",{selector:"dd"})).toBeVisible();
});

test("trade history shows a selected older record while the list fills in order",()=>{
  const row={executed_at:"2026-10-26T09:00:00Z",account_bucket_id:"bucket",side:"BUY",status:"filled",ordered_shares:100,filled_shares:100,average_fill_price:"1000",actual_commission:"0",actual_other_cost:"0",tax_withheld:"0"};
  const records=[{...row,execution_id:"old",symbol:"7203"},{...row,execution_id:"middle",symbol:"8306"},{...row,execution_id:"new",symbol:"9984"}];
  let next=0;const frames=new Map<number,FrameRequestCallback>();
  const request=vi.spyOn(window,"requestAnimationFrame").mockImplementation(callback=>{frames.set(++next,callback);return next;});
  const cancel=vi.spyOn(window,"cancelAnimationFrame").mockImplementation(id=>{frames.delete(id);});
  const tick=()=>act(()=>{const [id,callback]=frames.entries().next().value!;frames.delete(id);callback(0);});
  vi.mocked(useApiData).mockReturnValue({data:{records,appliedIds:["old"]},loading:false,error:null,savedAt:null,reload:vi.fn()});
  const view=render(<MemoryRouter initialEntries={["/transactions?record=old"]}><HistoryPage /></MemoryRouter>);
  expect(screen.getByRole("heading",{name:"7203 · 購入"})).toBeVisible();
  expect(screen.getByText("9984 / bucket")).toBeVisible();
  expect(screen.queryByText("8306 / bucket")).not.toBeInTheDocument();
  expect(screen.getByText("残りの取引履歴を表示しています…")).toBeVisible();
  tick();tick();expect(screen.getByText("8306 / bucket")).toBeVisible();
  tick();tick();expect(screen.getByText("7203 / bucket")).toBeVisible();
  expect(screen.queryByText("残りの取引履歴を表示しています…")).not.toBeInTheDocument();
  expect(within(screen.getByText("7203 / bucket").closest("tr")!).getByRole("button")).toHaveAttribute("aria-pressed","true");
  fireEvent.click(within(screen.getByText("8306 / bucket").closest("tr")!).getByRole("button"));
  expect(screen.getByRole("heading",{name:"8306 · 購入"})).toBeVisible();
  view.unmount();request.mockRestore();cancel.mockRestore();
});

test("a missing selected trade never substitutes a different record after refreshing",()=>{
  const row={executed_at:"2026-10-26T09:00:00Z",account_bucket_id:"bucket",side:"BUY",status:"filled",ordered_shares:100,filled_shares:100,average_fill_price:"1000",actual_commission:"0",actual_other_cost:"0",tax_withheld:"0"};
  vi.mocked(useApiData).mockReturnValue({data:{records:[{...row,execution_id:"old",symbol:"7203"}],appliedIds:["old"]},loading:true,error:null,savedAt:"2026-01-01T00:00:00Z",reload:vi.fn()});
  const view=render(<MemoryRouter initialEntries={["/transactions?record=old"]}><HistoryPage /></MemoryRouter>);
  expect(screen.getByRole("heading",{name:"7203 · 購入"})).toBeVisible();
  vi.mocked(useApiData).mockReturnValue({data:{records:[{...row,execution_id:"new",symbol:"9984"}],appliedIds:["new"]},loading:false,error:null,savedAt:null,reload:vi.fn()});
  view.rerender(<MemoryRouter initialEntries={["/transactions?record=old"]}><HistoryPage /></MemoryRouter>);
  expect(screen.getByText("選択した取引記録は見つかりません")).toBeVisible();
  expect(screen.queryByRole("heading",{name:"9984 · 購入"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"記録を確認"}));
  expect(screen.getByRole("heading",{name:"9984 · 購入"})).toBeVisible();
});

test("refreshed trade data updates the selected row, details, and applied status",()=>{
  const row={execution_id:"saved",executed_at:"2026-10-26T09:00:00Z",symbol:"7203",account_bucket_id:"bucket",side:"BUY",status:"filled",ordered_shares:100,filled_shares:100,average_fill_price:"1000",actual_commission:"0",actual_other_cost:"0",tax_withheld:"0"};
  const result=(record:typeof row,appliedIds:string[])=>({data:{records:[record],appliedIds},loading:false,error:null,savedAt:null,reload:vi.fn()});
  vi.mocked(useApiData).mockReturnValue(result(row,[]));
  const view=render(<MemoryRouter initialEntries={["/transactions?record=saved"]}><HistoryPage /></MemoryRouter>);
  expect(screen.getByText("残高へ未反映")).toBeVisible();
  vi.mocked(useApiData).mockReturnValue(result({...row,symbol:"8306",filled_shares:50,average_fill_price:"2000",actual_other_cost:"50"},["saved"]));
  view.rerender(<MemoryRouter initialEntries={["/transactions?record=saved"]}><HistoryPage /></MemoryRouter>);
  expect(screen.getByText("8306 / bucket")).toBeVisible();
  expect(screen.getByText("50株 × ¥2,000")).toBeVisible();
  expect(screen.getByText("残高へ反映済み")).toBeVisible();
  expect(screen.getByRole("heading",{name:"8306 · 購入"})).toBeVisible();
  expect(screen.getByText("¥50",{selector:"dd"})).toBeVisible();
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

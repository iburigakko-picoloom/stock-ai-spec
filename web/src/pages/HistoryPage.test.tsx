import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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

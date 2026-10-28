import { MemoryRouter } from "react-router-dom";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiGet, apiPost } from "../api";
import { CurrentAccountPanel } from "./CurrentAccountPanel";

vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());
const ledger = { portfolio_id: "current", as_of: "2026-10-24T00:00:00Z",
  account_buckets: [{ bucket_id: "a", account_type: "nisa", withholding_mode: "not_applicable" }], positions: [],
  cash: [{ account_bucket_id: "a", available_cash: "1040000", reserved_cash: "440000" }],
  tax_states: [{ account_bucket_id: "a", nisa_annual_capacity_user_input: "4000000", nisa_lifetime_capacity_user_input: "12000000" }],
};
const current = { ledger, profile: { revision_id: "profile", saved_at: "2026-10-24T00:00:00Z", portfolio: { accounts: [{ id: "a", available_cash_yen: "0" }] } }, settings: { revision_id: "settings", settings: { cash_basis: "deployable_after_reserved" } } };

test("cash editor uses current ledger and exposes unmatched input without silently changing it", async () => {
  vi.mocked(apiGet).mockResolvedValue(current);
  vi.mocked(apiPost).mockImplementation(async (_path, body) => ({ before: ledger, after: ledger, request: body }));
  render(<MemoryRouter><CurrentAccountPanel mode="cash" /></MemoryRouter>);
  expect(await screen.findByLabelText("現金残高（円）")).toHaveValue("1040000");
  expect(screen.getByLabelText("買付余力（円）")).toHaveValue("600000");
  expect(screen.getByText(/以前の買付余力：¥0/)).toBeVisible();
  expect(apiPost).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("現金残高（円）"), { target: { value: "440000" } });
  fireEvent.change(screen.getByLabelText("買付余力（円）"), { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "変更内容を確認" }));
  await screen.findByRole("button", { name: "この内容で現在残高を更新" });
  expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/personal/current/preview", expect.objectContaining({ changes: [{ account_bucket_id: "a", total: "440000", buying_power: "0" }] }));
  fireEvent.change(screen.getByLabelText("現金残高（円）"), { target: { value: "450000" } });
  expect(screen.queryByRole("button", { name: "この内容で現在残高を更新" })).not.toBeInTheDocument();
});

test("holdings are added and removed without mutating saved assets before confirmation", async () => {
  vi.mocked(apiGet).mockResolvedValue(current);
  render(<MemoryRouter><CurrentAccountPanel mode="holdings" /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "保有株を追加" }));
  fireEvent.change(screen.getByLabelText("銘柄コード"), { target: { value: "7203" } });
  fireEvent.change(screen.getByLabelText("口座区分"), { target: { value: "new:specified" } });
  expect(screen.getByLabelText("口座区分")).toHaveValue("new:specified");
  fireEvent.click(screen.getByRole("button", { name: "この保有を削除" }));
  expect(screen.queryByLabelText("銘柄コード")).not.toBeInTheDocument();
  expect(apiPost).not.toHaveBeenCalled();
});

test("historical four-million NISA entry remains visible with a correction warning", async () => {
  vi.mocked(apiGet).mockResolvedValue(current);
  render(<MemoryRouter><CurrentAccountPanel mode="nisa" /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("上限を超えています"));
  expect(screen.getByLabelText("今年の残枠（円）")).toHaveValue("4000000");
  expect(screen.getByText(/年間240万円/)).toBeVisible();
  expect(apiPost).not.toHaveBeenCalled();
});

test("deposit preview preserves reserved cash exactly and includes the dated reason", async()=>{
  vi.mocked(apiGet).mockResolvedValue(current);
  vi.mocked(apiPost).mockImplementation(async(_path,body)=>({before:ledger,after:ledger,request:body}));
  render(<MemoryRouter><CurrentAccountPanel mode="cash" /></MemoryRouter>);
  fireEvent.change(await screen.findByLabelText("種別"),{target:{value:"deposit"}});
  fireEvent.change(screen.getByLabelText("金額（円）"),{target:{value:"0.1"}});
  fireEvent.change(screen.getByLabelText("日付"),{target:{value:"2026-10-26"}});
  fireEvent.change(screen.getByLabelText("理由"),{target:{value:"SBI入金照合"}});
  fireEvent.click(screen.getByRole("button",{name:"変更内容を確認"}));
  await screen.findByRole("button",{name:"この内容で現在残高を更新"});
  expect(apiPost).toHaveBeenCalledExactlyOnceWith("/api/v1/mobile/personal/current/preview",expect.objectContaining({changes:[{account_bucket_id:"a",total:"1040000.1",buying_power:"600000.1"}],record:{date:"2026-10-26",reason:"SBI入金照合",kind:"deposit"}}));
});

test("an invalid cash draft remains editable and cannot save the previous valid amount",async()=>{
  vi.mocked(apiGet).mockResolvedValue(current);
  render(<MemoryRouter><CurrentAccountPanel mode="cash" /></MemoryRouter>);
  const input=await screen.findByLabelText("現金残高（円）");
  fireEvent.change(input,{target:{value:""}});
  expect(input).toHaveValue("");
  expect(screen.getByRole("button",{name:"変更内容を確認"})).toBeDisabled();
  fireEvent.change(input,{target:{value:"1040000.2"}});
  expect(screen.getByRole("button",{name:"変更内容を確認"})).toBeEnabled();
  expect(apiPost).not.toHaveBeenCalled();
});

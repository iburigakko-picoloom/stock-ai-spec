import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { apiPost } from "../api";
import { DataOperationsPage } from "./DataOperationsPage";

vi.mock("../api", async importOriginal => ({ ...await importOriginal<object>(), apiPost: vi.fn() }));
vi.mock("../hooks", () => ({ useApiData: () => ({ loading: false, data: null, error: null }) }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const value = { preview_id: "p", imported_as_of: "2026-01-01", differences: [], cash_differences: [] };
function open() {
  render(<MemoryRouter><DataOperationsPage /></MemoryRouter>);
  fireEvent.click(screen.getByText("口座状態CSV"));
  fireEvent.change(screen.getByLabelText("CSV内容"), { target: { value: "first" } });
}
test("editing CSV invalidates a pending preview response", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiPost).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  open(); fireEvent.click(screen.getByText("書き込まずに差分を確認"));
  fireEvent.change(screen.getByLabelText("CSV内容"), { target: { value: "second" } });
  await act(async () => finish(value));
  expect(screen.queryByText("保有差分preview")).not.toBeInTheDocument();
  expect(screen.getByLabelText("CSV内容")).toHaveValue("second");
});
test("uncertain confirmation retries the same ID and body, without duplicate clicks", async () => {
  vi.mocked(apiPost).mockResolvedValueOnce(value);
  open(); fireEvent.click(screen.getByText("書き込まずに差分を確認"));
  await screen.findByText("保有差分preview");
  fireEvent.click(screen.getByRole("checkbox"));
  let fail!: (reason: Error) => void;
  vi.mocked(apiPost).mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
  const save = screen.getByText("差分確認済みで反映");
  fireEvent.click(save); fireEvent.click(save);
  expect(apiPost).toHaveBeenCalledTimes(2);
  await act(async () => fail(new Error("disconnected")));
  vi.mocked(apiPost).mockResolvedValueOnce({});
  fireEvent.click(save);
  await screen.findByText("確認した口座状態を保存しました。");
  expect(vi.mocked(apiPost).mock.calls[2]).toEqual(vi.mocked(apiPost).mock.calls[1]);
});

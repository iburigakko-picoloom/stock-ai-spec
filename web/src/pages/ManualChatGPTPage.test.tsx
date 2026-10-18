import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ManualChatGPTPage } from "./ManualChatGPTPage";
import { apiGet, apiPost } from "../api";

vi.mock("../mobile/native", () => ({ isAndroid: () => true }));
vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
function show() { render(<MemoryRouter><ManualChatGPTPage /></MemoryRouter>); }

test("missing model or inputs stays blocked without export controls", async () => {
  vi.mocked(apiGet).mockResolvedValue({ ready: false, reason: "原予測が未採用です", selected_input: null, answers: [] });
  show();
  expect(await screen.findByText("原予測が未採用です")).toBeVisible();
  expect(screen.queryByRole("button", { name: "プロンプトを作成" })).toBeNull();
  expect(apiPost).not.toHaveBeenCalled();
});

test("explicit conditions precede copy and a rejected answer stays editable", async () => {
  vi.mocked(apiGet).mockResolvedValue({ ready: true, reason: null, selected_input: null, answers: [] });
  vi.mocked(apiPost).mockResolvedValueOnce({ input_record_id: "input", input_snapshot_id: "snapshot", expires_at: "2026-10-18T12:00:00+09:00", prompt: "合成入力" });
  show();
  const prepare = await screen.findByRole("button", { name: "プロンプトを作成" });
  expect(prepare).toBeDisabled();
  for (const check of screen.getAllByRole("checkbox")) fireEvent.click(check);
  fireEvent.click(prepare);
  expect(await screen.findByRole("textbox", { name: "ChatGPTへ渡す入力" })).toHaveValue("合成入力");
  expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/chatgpt-manual/export", expect.objectContaining({ training_disabled: true, data_entitlement_confirmed: true }));
  vi.mocked(apiPost).mockRejectedValueOnce(new Error("LOT_SIZE: 売買差分が単元に一致しません"));
  const answer = screen.getByRole("textbox", { name: "ChatGPTの回答JSON" });
  fireEvent.change(answer, { target: { value: '{"target_shares":1}' } });
  fireEvent.click(screen.getByRole("button", { name: "回答を検証して保存" }));
  expect(await screen.findByText("LOT_SIZE: 売買差分が単元に一致しません")).toBeVisible();
  expect(answer).toHaveValue('{"target_shares":1}');
  await waitFor(() => expect(screen.getByRole("button", { name: "回答を検証して保存" })).toBeEnabled());
  expect(apiPost).not.toHaveBeenCalledWith(expect.stringMatching(/executions|decisions|apply/), expect.anything());
});

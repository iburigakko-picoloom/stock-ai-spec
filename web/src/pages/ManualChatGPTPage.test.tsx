import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ManualChatGPTPage } from "./ManualChatGPTPage";
import { apiGet, apiPost } from "../api";

vi.mock("../mobile/native", () => ({ isAndroid: () => true, StockAI: {} }));
vi.mock("../hooks", () => ({ useApiData: () => ({ data: null, loading: false, error: null }) }));
vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.unstubAllGlobals(); });
function show() { render(<MemoryRouter><ManualChatGPTPage /></MemoryRouter>); }

test("saved research stays visible in history before a proposal has been reviewed",async()=>{
  vi.mocked(apiGet).mockResolvedValue({ready:false,reason:"期限切れ",selected_input:null,answers:[],research:[{record_id:"saved",saved_at:"2026-10-26T09:00:00Z",original_json:"保存した回答原本"}]});
  render(<MemoryRouter initialEntries={["/today/chatgpt/history"]}><ManualChatGPTPage /></MemoryRouter>);
  expect(await screen.findByText("保存した回答原本")).toBeVisible();
  expect(screen.queryByText("保存した相談はまだありません")).not.toBeInTheDocument();
  expect(apiPost).not.toHaveBeenCalled();
});

test("missing model or inputs stays blocked without export controls", async () => {
  vi.mocked(apiGet).mockResolvedValue({ ready: false, reason: "原予測が未採用です", selected_input: null, answers: [] });
  show();
  expect(await screen.findByText("原予測が未採用です")).toBeVisible();
  expect(screen.getByRole("button", { name: "作成・コピー" })).toBeDisabled();
  expect(apiPost).not.toHaveBeenCalled();
});

test("explicit conditions precede copy and a rejected answer stays editable", async () => {
  vi.mocked(apiGet).mockResolvedValue({ ready: true, reason: null, selected_input: null, answers: [] });
  vi.mocked(apiPost).mockResolvedValueOnce({ input_record_id: "input", input_snapshot_id: "snapshot", expires_at: "2026-10-18T12:00:00+09:00", prompt: "合成入力" });
  show();
  const prepare = await screen.findByRole("button", { name: "作成・コピー" });
  expect(prepare).toBeDisabled();
  for (const check of screen.getAllByRole("checkbox")) fireEvent.click(check);
  fireEvent.click(prepare);
  expect(await screen.findByRole("textbox", { name: "ChatGPTへ渡す入力" })).toHaveValue("合成入力");
  expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/chatgpt-manual/export", expect.objectContaining({ training_disabled: true, data_entitlement_confirmed: true }));
  vi.mocked(apiPost).mockRejectedValueOnce(new Error("LOT_SIZE: 売買差分が単元に一致しません"));
  const answer = screen.getByRole("textbox", { name: "ChatGPTの回答JSON" });
  fireEvent.change(answer, { target: { value: '{"target_shares":1}' } });
  fireEvent.click(screen.getByRole("button", { name: "検証・保存" }));
  expect(await screen.findByText("LOT_SIZE: 売買差分が単元に一致しません")).toBeVisible();
  expect(answer).toHaveValue('{"target_shares":1}');
  await waitFor(() => expect(screen.getByRole("button", { name: "検証・保存" })).toBeEnabled());
  expect(apiPost).not.toHaveBeenCalledWith(expect.stringMatching(/executions|decisions|apply/), expect.anything());
});

const savedInput = { input_record_id: "saved-input", input_snapshot_id: "snapshot", expires_at: "2026-10-18T12:00:00+09:00", prompt: "保存済みの合成プロンプト" };
function resumedStatus() { return { ready: true, reason: null, selected_input: savedInput.input_record_id, saved_input: savedInput, answers: [] }; }

test("a recreated page resumes the exact saved input without a new permission or export", async () => {
  vi.mocked(apiGet).mockResolvedValue(resumedStatus());
  show();
  expect(await screen.findByRole("textbox", { name: "ChatGPTへ渡す入力" })).toHaveValue(savedInput.prompt);
  expect(screen.getByRole("button", { name: "作成・コピー" })).toBeDisabled();
  for (const checkbox of screen.getAllByRole("checkbox")) expect(checkbox).not.toBeChecked();
  const answer = screen.getByRole("textbox", { name: "ChatGPTの回答JSON" });
  fireEvent.change(answer, { target: { value: "{}" } });
  vi.mocked(apiPost).mockRejectedValueOnce(new Error("合成の拒否"));
  fireEvent.click(screen.getByRole("button", { name: "検証・保存" }));
  expect(await screen.findByText("合成の拒否")).toBeVisible();
  expect(apiPost).toHaveBeenCalledTimes(1);
  expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/chatgpt-manual/research", { input_record_id: savedInput.input_record_id, answer_json: "{}" });
});

test("a long consultation can be saved after its comparison expires and reviewed separately", async () => {
  vi.mocked(apiGet).mockResolvedValue({ ready: false, reason: "照合期限切れ", selected_input: "original", answers: [] });
  vi.mocked(apiPost).mockResolvedValueOnce({ research_record_id: "saved" }).mockRejectedValueOnce(new Error("予測が更新されています"));
  show();
  const field = await screen.findByRole("textbox", { name: "ChatGPTの回答JSON" });
  fireEvent.change(field, { target: { value: "回答原本" } });
  fireEvent.click(screen.getByRole("button", { name: "検証・保存" }));
  expect(await screen.findByText("調査結果を保存しました。最新の条件で検算できます。")).toBeVisible();
  expect(apiPost).toHaveBeenCalledExactlyOnceWith("/api/v1/mobile/chatgpt-manual/research", { input_record_id: "original", answer_json: "回答原本" });
  fireEvent.click(screen.getByRole("button", { name: "最新の条件で検算" }));
  expect(await screen.findByText(/調査結果は保存済みです。予測が更新/)).toBeVisible();
  expect(field).toHaveValue("回答原本");
});

test("copy waits for current local permission and input checks and serializes controls", async () => {
  const clipboard = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText: clipboard } });
  let finish!: (value: unknown) => void;
  vi.mocked(apiGet).mockResolvedValueOnce(resumedStatus()).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  show();
  fireEvent.click(await screen.findByRole("button", { name: "プロンプトをコピー" }));
  expect(clipboard).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "プロンプトをコピー" })).toBeDisabled();
  finish(resumedStatus());
  expect(await screen.findByText("プロンプトをコピーしました。")).toBeVisible();
  expect(clipboard).toHaveBeenCalledExactlyOnceWith(savedInput.prompt);
  expect(apiPost).not.toHaveBeenCalled();
});

test.each(["expired", "changed", "snapshot", "unavailable"])("copy rejects %s context before writing the clipboard and keeps the draft", async change => {
  const clipboard = vi.fn();
  vi.stubGlobal("navigator", { clipboard: { writeText: clipboard } });
  vi.mocked(apiGet).mockResolvedValueOnce(resumedStatus());
  if (change === "unavailable") vi.mocked(apiGet).mockRejectedValueOnce(new Error("offline core"));
  else vi.mocked(apiGet).mockResolvedValueOnce(change === "expired"
    ? { ...resumedStatus(), saved_input: null, saved_input_reason: "送信許可が期限切れです" }
    : change === "snapshot" ? { ...resumedStatus(), ready: false, reason: "保有が更新されています", saved_input: null }
    : { ...resumedStatus(), saved_input: { ...savedInput, input_record_id: "different" } });
  show();
  const answer = await screen.findByRole("textbox", { name: "ChatGPTの回答JSON" });
  fireEvent.change(answer, { target: { value: "保存したい回答" } });
  fireEvent.click(screen.getByRole("button", { name: "プロンプトをコピー" }));
  expect(await screen.findByText("処理を完了できません")).toBeVisible();
  expect(clipboard).not.toHaveBeenCalled();
  expect(answer).toHaveValue("保存したい回答");
  expect(apiPost).not.toHaveBeenCalled();
});

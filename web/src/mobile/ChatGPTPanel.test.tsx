import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ChatGPTPanel } from "./ChatGPTPanel";
import { ChatGPT, type ChatGPTStatus } from "./chatgpt";

vi.mock("./chatgpt", () => ({ ChatGPT: { getStatus: vi.fn(), signIn: vi.fn(), cancelSignIn: vi.fn(), signOut: vi.fn(), listModels: vi.fn(), saveSelection: vi.fn(), probe: vi.fn() } }));
afterEach(cleanup);
const disconnected: ChatGPTStatus = { connected: false, planEnabled: false, accountLabel: null, state: "disconnected", selection: { model: "", effort: "medium" }, models: [], apiFallback: false };
const connected: ChatGPTStatus = { ...disconnected, connected: true, planEnabled: true, accountLabel: "Synthetic account", state: "connected", models: [{ slug: "synthetic-model", displayName: "Synthetic model" }] };
beforeEach(() => { vi.resetAllMocks(); vi.mocked(ChatGPT.getStatus).mockResolvedValue(disconnected); });

test("login loads the actual account models and saving is required before a probe", async () => {
  vi.mocked(ChatGPT.signIn).mockResolvedValue(connected);
  vi.mocked(ChatGPT.listModels).mockResolvedValue(connected);
  vi.mocked(ChatGPT.saveSelection).mockResolvedValue({ ...connected, selection: { model: "synthetic-model", effort: "high" } });
  render(<ChatGPTPanel />);
  const login = await screen.findByRole("button", { name: "Continue with ChatGPT" });
  await waitFor(() => expect(login).toBeEnabled()); fireEvent.click(login);
  const choose = await screen.findByRole("combobox", { name: "調査モデル" });
  fireEvent.change(choose, { target: { value: "synthetic-model" } });
  fireEvent.change(screen.getByRole("combobox", { name: "考える深さ" }), { target: { value: "high" } });
  expect(screen.getByRole("button", { name: "検索付きで接続を確認" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "調査設定を保存" }));
  await screen.findByText("調査モデルと考える深さを保存しました。");
  expect(ChatGPT.saveSelection).toHaveBeenCalledWith({ model: "synthetic-model", effort: "high" });
  expect(screen.getByRole("button", { name: "検索付きで接続を確認" })).toBeEnabled();
});

test("denied plan permission never triggers models or paid inference", async () => {
  vi.mocked(ChatGPT.signIn).mockResolvedValue({ ...connected, planEnabled: false });
  render(<ChatGPTPanel />);
  const button = await screen.findByRole("button", { name: "Continue with ChatGPT" });
  await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button);
  await screen.findByText("ログインできました。調査にはChatGPTの利用枠を使う許可が必要です。");
  expect(ChatGPT.listModels).not.toHaveBeenCalled(); expect(ChatGPT.probe).not.toHaveBeenCalled();
});

test("interrupted probe is not displayed as completed and preserves selected settings", async () => {
  vi.mocked(ChatGPT.getStatus).mockResolvedValue({ ...connected, selection: { model: "synthetic-model", effort: "medium" } });
  vi.mocked(ChatGPT.probe).mockRejectedValue(new Error("RESPONSE_INTERRUPTED"));
  render(<ChatGPTPanel />);
  const button = await screen.findByRole("button", { name: "検索付きで接続を確認" });
  fireEvent.click(button); await screen.findByText("RESPONSE_INTERRUPTED");
  expect(screen.queryByText("接続確認の結果")).not.toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "調査モデル" })).toHaveValue("synthetic-model");
});

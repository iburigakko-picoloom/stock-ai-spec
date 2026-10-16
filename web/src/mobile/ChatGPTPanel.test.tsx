import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ChatGPTPanel } from "./ChatGPTPanel";
import { ChatGPT, type ChatGPTStatus } from "./chatgpt";

vi.mock("./chatgpt", async importOriginal => ({ ...await importOriginal<typeof import("./chatgpt")>(), ChatGPT: { getStatus: vi.fn(), signIn: vi.fn(), cancelSignIn: vi.fn(), signOut: vi.fn(), listModels: vi.fn(), saveSelection: vi.fn(), probe: vi.fn() } }));
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

test("an expired saved session offers reauthorization and keeps its selected model", async () => {
  const selected = { ...connected, selection: { model: "synthetic-model", effort: "high" as const } };
  vi.mocked(ChatGPT.getStatus).mockResolvedValue({ ...selected, connected: false, planEnabled: false, reauthorizationRequired: true });
  vi.mocked(ChatGPT.signIn).mockResolvedValue(selected);
  vi.mocked(ChatGPT.listModels).mockResolvedValue(selected);
  render(<ChatGPTPanel />);
  await screen.findByText("ログインの更新が必要です");
  expect(ChatGPT.signIn).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Continue with ChatGPT" }));
  await screen.findByText("連携しました。調査に使うモデルと考える深さを確認してください。");
  expect(screen.getByRole("combobox", { name: "調査モデル" })).toHaveValue("synthetic-model");
  expect(screen.getByRole("combobox", { name: "考える深さ" })).toHaveValue("high");
});

test("a connected account can explicitly reauthorize and cancel without erasing prior settings", async () => {
  vi.mocked(ChatGPT.getStatus).mockResolvedValue({ ...connected, selection: { model: "synthetic-model", effort: "medium" } });
  let rejectLogin!: (error: Error) => void;
  vi.mocked(ChatGPT.signIn).mockReturnValue(new Promise((_, reject) => { rejectLogin = reject; }));
  vi.mocked(ChatGPT.cancelSignIn).mockImplementation(async () => { rejectLogin(new Error("AUTHORIZATION_CANCELLED_OR_EXPIRED")); });
  render(<ChatGPTPanel />);
  await screen.findByText(/利用枠の連携済み/);
  fireEvent.click(screen.getByText("連携について"));
  fireEvent.click(screen.getByRole("button", { name: "ログインし直す" }));
  fireEvent.click(await screen.findByRole("button", { name: "ログインを中止" }));
  await screen.findByText("AUTHORIZATION_CANCELLED_OR_EXPIRED");
  expect(ChatGPT.cancelSignIn).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("combobox", { name: "調査モデル" })).toHaveValue("synthetic-model");
  expect(ChatGPT.signOut).not.toHaveBeenCalled();
});

test("terminal refresh failure updates connection state without exposing raw provider messages", async () => {
  const selected = { ...connected, selection: { model: "synthetic-model", effort: "medium" as const } };
  vi.mocked(ChatGPT.getStatus).mockResolvedValueOnce(selected).mockResolvedValue({ ...selected, connected: false, planEnabled: false, reauthorizationRequired: true });
  vi.mocked(ChatGPT.probe).mockRejectedValue(Object.assign(new Error("provider-private-diagnostic"), { code: "invalid_grant" }));
  render(<ChatGPTPanel />);
  fireEvent.click(await screen.findByRole("button", { name: "検索付きで接続を確認" }));
  await screen.findByText("ChatGPTへのログインを更新してください。調査結果とモデル設定は保存されています。");
  expect(screen.queryByText("provider-private-diagnostic")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Continue with ChatGPT" })).toBeEnabled();
});

for (const confirmed of [false, true]) {
  test(`logout accurately reports remote revocation confirmed=${confirmed}`, async () => {
    vi.mocked(ChatGPT.getStatus).mockResolvedValue(connected);
    vi.mocked(ChatGPT.signOut).mockResolvedValue({ ...disconnected, accountLabel: connected.accountLabel, revocationConfirmed: confirmed });
    render(<ChatGPTPanel />);
    await screen.findByText(/利用枠の連携済み/);
    fireEvent.click(screen.getByText("連携について"));
    const disconnect = screen.getByRole("button", { name: "確認して連携解除" });
    expect(disconnect).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "この端末のChatGPT連携を解除する" }));
    fireEvent.click(disconnect);
    await screen.findByText(confirmed ? "ChatGPTのセッションを失効し、この端末の資格情報を削除しました。"
      : "この端末の資格情報を削除しました。OpenAI側の失効は確認できていません。ChatGPTの設定でアプリの接続を確認してください。");
    expect(ChatGPT.signOut).toHaveBeenCalledTimes(1);
    expect(ChatGPT.probe).not.toHaveBeenCalled();
  });
}

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MobileBackupPanel } from "./MobileBackupPanel";
import { StockAI } from "./native";
import { restoreMobileBackup } from "./runtime";

vi.mock("./native", () => ({ StockAI: { exportBackup: vi.fn(), importBackup: vi.fn(), discardBackup: vi.fn() } }));
vi.mock("./runtime", () => ({ restoreMobileBackup: vi.fn() }));
afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(StockAI.discardBackup).mockResolvedValue(undefined);
  vi.mocked(StockAI.importBackup).mockResolvedValue({ token: "synthetic-preview-token", characters: 96_781_956 });
});
function panel(disabled = false) {
  const onBusy = vi.fn();
  const rendered = render(<MobileBackupPanel disabled={disabled} onBusy={onBusy} />);
  fireEvent.change(screen.getByLabelText("バックアップのパスワード（12文字以上）"), { target: { value: "synthetic-long-password" } });
  return { ...rendered, onBusy };
}
async function choose() {
  fireEvent.click(screen.getByRole("button", { name: "復元ファイルを選ぶ" }));
  await screen.findByRole("button", { name: "このバックアップから復元" });
}

test("export requires a password and waits for native completion", async () => {
  let finish!: () => void;
  vi.mocked(StockAI.exportBackup).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const { onBusy } = panel();
  fireEvent.click(screen.getByRole("button", { name: "バックアップを書き出す" }));
  expect(StockAI.exportBackup).toHaveBeenCalledWith({ password: "synthetic-long-password" });
  expect(screen.getByRole("button", { name: "復元ファイルを選ぶ" })).toBeDisabled();
  expect(screen.queryByText(/バックアップを保存しました/)).not.toBeInTheDocument();
  finish();
  await screen.findByText(/バックアップを保存しました/);
  expect(onBusy.mock.calls).toEqual([[true], [false]]);
});

test("authenticated metadata does not restore until explicit confirmation", async () => {
  vi.mocked(restoreMobileBackup).mockResolvedValue(undefined);
  panel(); await choose();
  const restore = screen.getByRole("button", { name: "このバックアップから復元" });
  expect(restore).toBeDisabled(); expect(restoreMobileBackup).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(restore);
  await waitFor(() => expect(restoreMobileBackup).toHaveBeenCalledWith("synthetic-preview-token"));
  await waitFor(() => expect(screen.queryByRole("checkbox")).not.toBeInTheDocument());
  expect(screen.queryByText("synthetic-preview-token")).not.toBeInTheDocument();
});

test("cancel and unmount discard only the selected preview", async () => {
  const { unmount } = panel(); await choose();
  fireEvent.click(screen.getByRole("button", { name: "復元を取り消す" }));
  await waitFor(() => expect(StockAI.discardBackup).toHaveBeenCalledWith({ token: "synthetic-preview-token" }));
  expect(restoreMobileBackup).not.toHaveBeenCalled();
  await choose(); unmount();
  await waitFor(() => expect(StockAI.discardBackup).toHaveBeenCalledTimes(2));
});

test("failed selection never exposes confirmation or raw native errors", async () => {
  vi.mocked(StockAI.importBackup).mockRejectedValue(new Error("synthetic-private-detail"));
  panel(); fireEvent.click(screen.getByRole("button", { name: "復元ファイルを選ぶ" }));
  await screen.findByText(/処理の結果を確認できませんでした/);
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.queryByText(/synthetic-private-detail/)).not.toBeInTheDocument();
  expect(restoreMobileBackup).not.toHaveBeenCalled();
});

test("failed restore discards the consumed preview and requires a fresh selection", async () => {
  vi.mocked(restoreMobileBackup).mockRejectedValue(new Error("synthetic-conflict"));
  panel(); await choose(); fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "このバックアップから復元" }));
  await screen.findByText(/処理の結果を確認できませんでした/);
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  await waitFor(() => expect(StockAI.discardBackup).toHaveBeenCalledWith({ token: "synthetic-preview-token" }));
});

test("another device operation keeps backup controls disabled", () => {
  panel(true);
  expect(screen.getByRole("button", { name: "バックアップを書き出す" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "復元ファイルを選ぶ" })).toBeDisabled();
});

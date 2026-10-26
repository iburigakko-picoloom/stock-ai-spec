import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MobileUpdateNotice } from "./MobileDevicePanel";
import { isAndroid, StockAI, type ReleaseInfo } from "./native";

vi.mock("./native", () => ({ isAndroid: vi.fn(), StockAI: { checkUpdate: vi.fn(), installUpdate: vi.fn() } }));
const release: ReleaseInfo = { available: true, versionName: "0.1.27-candidate", versionCode: 10027,
  notes: "試験用の変更内容。公開版や採用状態を示すものではありません。", sha256: "a".repeat(64), url: "https://example.invalid/StockAI.apk", size: 123 };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(isAndroid).mockReturnValue(true);
  vi.mocked(StockAI.checkUpdate).mockResolvedValue(release);
  vi.mocked(StockAI.installUpdate).mockResolvedValue({ needsPermission: false });
});
afterEach(cleanup);

test("a new release shows a short notice, shows notes and never starts installation on its own", async () => {
  render(<MobileUpdateNotice />);
  expect(await screen.findByText("新しいバージョンがあります")).toBeVisible();
  expect(screen.getByText(release.versionName)).toBeVisible();
  expect(screen.getByText(release.notes)).toBeVisible();
  expect(StockAI.installUpdate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("変更内容を見る"));
  expect(screen.getByText(release.notes)).toBeVisible();
});

test("the current version does not show an update banner", async () => {
  vi.mocked(StockAI.checkUpdate).mockResolvedValue({ ...release, available: false });
  const { container } = render(<MobileUpdateNotice />);
  await waitFor(() => expect(StockAI.checkUpdate).toHaveBeenCalledOnce());
  expect(container).toBeEmptyDOMElement();
});

test("an offline release check leaves normal local use alone", async () => {
  vi.mocked(StockAI.checkUpdate).mockRejectedValue(new Error("offline"));
  const { container } = render(<MobileUpdateNotice />);
  await act(async () => {});
  expect(container).toBeEmptyDOMElement();
  expect(StockAI.installUpdate).not.toHaveBeenCalled();
});

test("the web version never calls the Android updater", () => {
  vi.mocked(isAndroid).mockReturnValue(false);
  const { container } = render(<MobileUpdateNotice />);
  expect(container).toBeEmptyDOMElement();
  expect(StockAI.checkUpdate).not.toHaveBeenCalled();
});

test("installation waits for native acknowledgment, prevents repeated taps and passes the detected version", async () => {
  let finish!: (value: { needsPermission: boolean }) => void;
  vi.mocked(StockAI.installUpdate).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  render(<MobileUpdateNotice />);
  const button = await screen.findByRole("button", { name: /^更新$/ });
  fireEvent.click(button); fireEvent.click(button);
  expect(button).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("APKを確認しています…");
  expect(StockAI.installUpdate).toHaveBeenCalledExactlyOnceWith({ versionCode: release.versionCode });
  await act(async () => { finish({ needsPermission: false }); });
  expect(screen.getByRole("status")).toHaveTextContent("Androidの確認画面でインストールしてください。");
  expect(button).toBeEnabled();
});

test("a permission request tells the owner to allow and retry without claiming the update finished", async () => {
  vi.mocked(StockAI.installUpdate).mockResolvedValue({ needsPermission: true });
  render(<MobileUpdateNotice />);
  fireEvent.click(await screen.findByRole("button", { name: /^更新$/ }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Androidの設定で更新を許可してから、もう一度更新ボタンを押してください。"));
  expect(screen.queryByText("更新が完了しました")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^更新$/ })).toBeEnabled();
});

test("download failure retains the notice and allows one explicit retry", async () => {
  vi.mocked(StockAI.installUpdate).mockRejectedValueOnce(new Error("download failed"));
  render(<MobileUpdateNotice />);
  const button = await screen.findByRole("button", { name: /^更新$/ });
  fireEvent.click(button);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("更新を取得できませんでした。現在のアプリを引き続き使用できます。"));
  expect(screen.getByText("新しいバージョンがあります")).toBeVisible();
  fireEvent.click(button);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Androidの確認画面でインストールしてください。"));
  expect(StockAI.installUpdate).toHaveBeenCalledTimes(2);
});

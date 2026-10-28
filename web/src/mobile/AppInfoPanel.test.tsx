import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { AppInfoPanel } from "./AppInfoPanel";
import { StockAI } from "./native";

vi.mock("./native", () => ({ StockAI: {appInfo:vi.fn(),checkUpdate:vi.fn(),installUpdate:vi.fn(),selectUpdate:vi.fn()} }));
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(StockAI.appInfo).mockResolvedValue({applicationId:"jp.stockai.app",versionName:"test",versionCode:1});
});
afterEach(cleanup);

test("the owner can select a private Drive file and then confirm installation in Android", async () => {
  vi.mocked(StockAI.selectUpdate).mockResolvedValue({needsPermission:false});
  render(<AppInfoPanel />);
  fireEvent.click(screen.getByRole("button",{name:"Driveなどから更新ファイルを選ぶ"}));
  await waitFor(()=>expect(screen.getByRole("status")).toHaveTextContent("Androidの確認画面でインストール"));
  expect(StockAI.selectUpdate).toHaveBeenCalledOnce();
});

test.each([
  [{needsPermission:true}, "Androidの設定で更新を許可"],
  [{needsPermission:false,cancelled:true}, "選択を取り消しました"],
] as const)("permission and cancellation are not reported as installation", async (result, text) => {
  vi.mocked(StockAI.selectUpdate).mockResolvedValue(result);
  render(<AppInfoPanel />);
  fireEvent.click(screen.getByRole("button",{name:"Driveなどから更新ファイルを選ぶ"}));
  await waitFor(()=>expect(screen.getByRole("status")).toHaveTextContent(text));
});

test("an invalid or older APK leaves the installed app in place", async () => {
  vi.mocked(StockAI.selectUpdate).mockRejectedValue(new Error("UPDATE_FILE_INVALID"));
  render(<AppInfoPanel />);
  fireEvent.click(screen.getByRole("button",{name:"Driveなどから更新ファイルを選ぶ"}));
  await waitFor(()=>expect(screen.getByRole("status")).toHaveTextContent("選んだAPKを確認できません"));
  expect(screen.getByRole("button",{name:"Driveなどから更新ファイルを選ぶ"})).toBeEnabled();
});

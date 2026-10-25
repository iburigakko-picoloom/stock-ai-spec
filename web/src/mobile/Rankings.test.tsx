import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiGet, apiPost } from "../api";
import { useApiData } from "../hooks";
import { Rankings } from "./Rankings";

vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("../hooks", () => ({ useApiData: vi.fn() }));
vi.mock("./ReferenceAnalysis", () => ({ ReferenceAnalysis: () => <button>ランキングを更新</button> }));
const reload = vi.fn();
const base = { id: "snapshot-a", generatedAt: "2026-10-23T12:00:00+09:00", priceDate: "2026-10-22", rows: [
  { symbol: "1000", modelRank: 1, score: 1, expectedReturn: .04 },
  { symbol: "2000", modelRank: 2, score: 0, expectedReturn: .01 },
], total: 2, answer: null };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(useApiData).mockReturnValue({ data: base, loading: false, error: null, savedAt: null, reload });
});
afterEach(cleanup);

test("saved rankings show the date, can update any time, and distinguish ChatGPT from model", () => {
  vi.mocked(useApiData).mockReturnValue({ data: { ...base, answer: { order: [
    { symbol: "2000", reason: "相談で優先" }, { symbol: "1000", reason: "比較後の順位" },
  ] } }, loading: false, error: null, savedAt: null, reload });
  render(<Rankings />);
  expect(screen.getByText(/株価 2026-10-22/)).toBeVisible();
  expect(screen.getByText(/ChatGPTの回答を反映した順位/)).toBeVisible();
  expect(screen.getByText("相談で優先")).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: "モデル" }));
  expect(screen.queryByText("相談で優先")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "ランキングを更新" })).toBeEnabled();
});

test("consultation exports only after confirmation and imports to its exact ranking", async () => {
  vi.mocked(apiPost).mockResolvedValueOnce({ id: base.id, prompt: "相談する銘柄", expiresAt: "2026-10-27" }).mockResolvedValueOnce({});
  render(<Rankings />);
  fireEvent.click(screen.getByRole("button", { name: "ChatGPTと相談" }));
  expect(screen.getByRole("button", { name: "相談文を作る" })).toBeDisabled();
  for (const input of screen.getAllByRole("checkbox")) fireEvent.click(input);
  fireEvent.click(screen.getByRole("button", { name: "相談文を作る" }));
  expect(await screen.findByLabelText("ChatGPTへの相談文")).toHaveValue("相談する銘柄");
  fireEvent.change(screen.getByLabelText("回答JSON"), { target: { value: '{"id":"snapshot-a"}' } });
  fireEvent.click(screen.getByRole("button", { name: "回答をランキングに反映" }));
  await waitFor(() => expect(apiPost).toHaveBeenLastCalledWith("/api/v1/mobile/ranking/20d/answer", { id: base.id, answer: '{"id":"snapshot-a"}' }));
  await waitFor(() => expect(reload).toHaveBeenCalled());
});

test("reopened input is available but changed ranking prevents stale clipboard export", async () => {
  vi.mocked(useApiData).mockReturnValue({ data: { ...base, savedInput: { id: base.id, prompt: "保存済み相談", expiresAt: "2026-10-27" } }, loading: false, error: null, savedAt: null, reload });
  vi.mocked(apiGet).mockResolvedValue({ ...base, id: "changed" });
  render(<Rankings />);
  fireEvent.click(screen.getByRole("button", { name: "ChatGPTと相談" }));
  expect(screen.getByLabelText("ChatGPTへの相談文")).toHaveValue("保存済み相談");
  fireEvent.click(screen.getByRole("button", { name: "相談文をコピー" }));
  expect(await screen.findByRole("status")).toHaveTextContent("更新されています");
});

 test("search keeps the actual rank instead of renumbering filtered rows", () => {
  render(<Rankings />);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "2000" } });
  expect(screen.getByText("2位")).toBeVisible();
  expect(screen.queryByText("1000")).not.toBeInTheDocument();
});

 test("restores all four tabs and marks unavailable rankings without fetching them", () => {
  render(<Rankings />);
  for (const name of ["総合", "5日", "20日", "前場"]) expect(screen.getByRole("tab", { name })).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: "総合" }));
  expect(screen.getByText("総合ランキングは未導入です")).toBeVisible();
  expect(screen.queryByRole("button", { name: "ChatGPTと相談" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "前場" }));
  expect(screen.getByText("前場ランキングは未導入です")).toBeVisible();
  expect(vi.mocked(useApiData).mock.calls.every(([path]) => path.endsWith("/20d"))).toBe(true);
  fireEvent.click(screen.getByRole("tab", { name: "5日" }));
  expect(screen.getByText(/5日の予測リターン（補助情報）/)).toBeVisible();
  expect(screen.queryByText("1位")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "ChatGPTと相談" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "20日" }));
  expect(screen.getByText("1位")).toBeVisible();
  expect(screen.getByRole("button", { name: "ChatGPTと相談" })).toBeEnabled();
});

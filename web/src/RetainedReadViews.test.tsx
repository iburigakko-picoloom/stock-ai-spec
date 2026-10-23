import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { apiGet } from "./api";
import { useApiData } from "./hooks";
import { RetainedReadViews } from "./RetainedReadViews";

vi.mock("./api", () => ({ apiGet: vi.fn() }));
vi.mock("./mobile/native", () => ({ isAndroid: () => true }));
function TestPage({ path }: { path: string }) {
  const { data, loading, error } = useApiData<{ text: string }>(path);
  return <section aria-label={path}>
    {error ? <p>取得失敗</p> : <p>{data?.text ?? "初回読込"}</p>}
    <button disabled={loading || !!error || !data}>確定 {path}</button>
  </section>;
}
vi.mock("./pages/HomePage", () => ({ HomePage: () => <TestPage path="home" /> }));
vi.mock("./pages/TodayPage", () => ({ TodayPage: () => <TestPage path="today" /> }));
vi.mock("./pages/RankingPage", () => ({ RankingPage: () => <TestPage path="ranking" /> }));
vi.mock("./pages/ValidationPage", () => ({ ValidationPage: () => <TestPage path="validation" /> }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

test("Android tab return keeps previous display but waits for fresh data before confirmation", async () => {
  const user = userEvent.setup();
  vi.mocked(apiGet).mockImplementation(async path => ({ text: `${path} 保存済み` }));
  render(<MemoryRouter><Link to="/">ホーム</Link><Link to="/ranking">順位</Link><Link to="/settings">設定</Link>
    <Routes><Route element={<RetainedReadViews />}>
      <Route index element={<p>unused</p>} /><Route path="ranking" element={<p>unused</p>} />
      <Route path="settings" element={<p>設定内容</p>} />
    </Route></Routes>
  </MemoryRouter>);
  await screen.findByText("home 保存済み");
  expect(apiGet).toHaveBeenCalledTimes(1); // Hidden tabs never fetch.
  await user.click(screen.getByRole("link", { name: "順位" }));
  await screen.findByText("ranking 保存済み");
  expect(apiGet).toHaveBeenCalledTimes(2);
  await user.click(screen.getByRole("link", { name: "設定" }));
  await screen.findByText("設定内容");
  act(() => window.dispatchEvent(new Event("focus")));
  expect(apiGet).toHaveBeenCalledTimes(2); // Hidden effects/timers are stopped.
  let finish!: (value: { text: string }) => void;
  vi.mocked(apiGet).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await user.click(screen.getByRole("link", { name: "ホーム" }));
  expect(screen.getByText("home 保存済み")).toBeVisible();
  expect(within(screen.getByRole("region", { name: "home" })).queryByText("初回読込")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "確定 home" })).toBeDisabled();
  await act(async () => finish({ text: "新しい資産" }));
  expect(screen.getByText("新しい資産")).toBeVisible();
  expect(screen.getByRole("button", { name: "確定 home" })).toBeEnabled();
  vi.mocked(apiGet).mockRejectedValue(new Error("integrity failure"));
  act(() => window.dispatchEvent(new Event("focus")));
  await waitFor(() => expect(screen.getByText("取得失敗")).toBeVisible());
  expect(screen.queryByText("新しい資産")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "確定 home" })).toBeDisabled();
});

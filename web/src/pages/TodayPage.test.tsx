import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { useApiData } from "../hooks";
import { TodayPage } from "./TodayPage";
import type { TodayResponse } from "../types";

vi.mock("../hooks", () => ({ useApiData: vi.fn() }));
vi.mock("../mobile/DailyPanel", () => ({ DailyPanel: () => null }));
afterEach(cleanup);
const data: TodayResponse = {
  businessDate: "2026-10-22", pipelineState: "PRE_MARKET", isStale: true,
  blockingReason: "ALPHA_CUTOFF_OPEN", runtimeMode: "RESEARCH", proposal: null,
  savedAnalysis: { snapshotId: "old", asOf: "2026-10-21T11:30:00+09:00",
    generatedAt: "2026-10-21T11:40:00+09:00", dataAsOf: "2026-10-21T11:00:00+09:00",
    modelVersion: "research-v1", readOnly: true, holdingSymbols: ["1234"],
    predictions: [{ symbol: "1234", expected_return_5d: null, expected_return_20d: .02, rank_score_20d: .8 }] },
};
function response(value: TodayResponse, loading = false) {
  vi.mocked(useApiData).mockReturnValue({ data: value, loading, error: null, reload: vi.fn() });
}
test("previous saved analysis stays read-only through refresh and switches with new archive", () => {
  response(data);
  const view = render(<MemoryRouter><TodayPage /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "2026/10/21の分析" })).toBeVisible();
  expect(screen.getByText("今日の予測は11:30以降に更新します。")).toBeVisible();
  expect(screen.getByText("1234（保有）")).toBeVisible();
  expect(screen.getByText("—")).toBeVisible();
  expect(screen.queryByRole("link", { name: /判断を確認/ })).not.toBeInTheDocument();
  response(data, true);
  view.rerender(<MemoryRouter><TodayPage /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "2026/10/21の分析" })).toBeVisible();
  expect(screen.getByText("更新状況を確認中…")).toBeVisible();
  response({ ...data, savedAnalysis: { ...data.savedAnalysis!, snapshotId: "new", asOf: "2026-10-22T11:30:00+09:00" } });
  view.rerender(<MemoryRouter><TodayPage /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "2026/10/22の分析" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "2026/10/21の分析" })).not.toBeInTheDocument();
});
test("no saved result shows preparation instead of a fictional previous analysis", () => {
  response({ ...data, savedAnalysis: null });
  render(<MemoryRouter><TodayPage /></MemoryRouter>);
  expect(screen.getByText("初回の分析を準備中")).toBeVisible();
  expect(screen.queryByRole("region", { name: "保存済み分析" })).not.toBeInTheDocument();
  expect(screen.queryByText("ALPHA_CUTOFF_OPEN")).not.toBeInTheDocument();
});

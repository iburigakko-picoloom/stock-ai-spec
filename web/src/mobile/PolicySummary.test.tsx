import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AllocationReadout, MinimumCashField, PolicyDataProvider, PolicySummary, RiskPolicyFields } from "./PolicySummary";
import { useApiData } from "../hooks";
import { isAndroid } from "./native";
vi.mock("../hooks", () => ({useApiData:vi.fn()}));
vi.mock("./native", () => ({isAndroid:vi.fn()}));
afterEach(() => {cleanup();vi.resetAllMocks();});
test.each([true,false])("allocation uses the correct ledger source on Android=%s", android => {
  vi.mocked(isAndroid).mockReturnValue(android);
  vi.mocked(useApiData).mockReturnValue({data:{portfolio:{equityValue:"1234",cashValue:"5678"}},error:null,loading:false,savedAt:null,reload:vi.fn()});
  render(<AllocationReadout />);
  expect(useApiData).toHaveBeenCalledWith(android ? "/api/v1/home/ledger" : "/api/v1/home");
  expect(screen.getByText("¥1,234")).toBeVisible();
  expect(screen.getByText("¥5,678")).toBeVisible();
});

test("allocation labels historical balances and reports failed verification",()=>{
  vi.mocked(isAndroid).mockReturnValue(true);
  vi.mocked(useApiData).mockReturnValue({data:{portfolio:{equityValue:"1234",cashValue:"5678"}},error:null,loading:true,savedAt:"2026-01-01T00:00:00Z",reload:vi.fn()});
  const view=render(<AllocationReadout />);
  expect(screen.getByRole("status")).toHaveTextContent("保存済み表示・閲覧用");
  expect(screen.getByText("¥1,234")).toBeVisible();
  vi.mocked(useApiData).mockReturnValue({data:null,error:"整合性エラー",loading:false,savedAt:null,reload:vi.fn()});
  view.rerender(<AllocationReadout />);
  expect(screen.getByRole("alert")).toHaveTextContent("資産残高を確認できません。");
  expect(screen.queryByText("¥1,234")).not.toBeInTheDocument();
});


test("conditions share one settings read across all three policy sections", () => {
  vi.mocked(useApiData).mockReturnValue({ data: {
    capital: { minimumCashRatio: "0.2" },
    decisionPolicies: { maximumPositions: 8, maximumSymbolWeight: "0.15", roundLotShares: 100, minimumImprovementYen: "300" },
  }, error: null, loading: false, savedAt: null, reload: vi.fn() });
  render(<PolicyDataProvider><MinimumCashField /><RiskPolicyFields /><PolicySummary /></PolicyDataProvider>);
  expect(useApiData).toHaveBeenCalledTimes(1);
  expect(useApiData).toHaveBeenCalledWith("/api/v1/settings");
  expect(screen.getByLabelText("最低現金（総資産比・%）")).toHaveValue("20");
  expect(screen.getByLabelText("最大保有銘柄数")).toHaveValue("8");
  expect(screen.getByLabelText("売買単位")).toHaveValue("100株");
});

test("shared policy errors remain visible without inventing settings", () => {
  vi.mocked(useApiData).mockReturnValue({ data: null, error: "failed", loading: false, savedAt: null, reload: vi.fn() });
  render(<PolicyDataProvider><MinimumCashField /><RiskPolicyFields /><PolicySummary /></PolicyDataProvider>);
  expect(screen.getByRole("alert")).toHaveTextContent("計算条件を取得できません");
  expect(screen.getByLabelText("最低現金（総資産比・%）")).toHaveValue("未設定");
});

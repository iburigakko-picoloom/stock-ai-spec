import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { useApiData } from "../hooks";
import { ProposalReadiness, proposalBlockLabel } from "./ProposalReadiness";

vi.mock("../hooks", () => ({ useApiData: vi.fn() }));
vi.mock("./native", () => ({ isAndroid: () => true }));
afterEach(cleanup);
const ready = { portfolio_revision_id: "saved", input_gaps: ["available_cash_yen"],
  initial_ledger: { blocking_reasons: ["held_prices_missing"] },
  comparison: { ledger_portfolio_id: null, blocking_reasons: [{ code: "FORECAST_MISSING" }] } };
function show(data: unknown, loading = false, error: string | null = null) {
  vi.mocked(useApiData).mockReturnValue({ data, loading, error, savedAt: null, reload: vi.fn() });
  render(<MemoryRouter><ProposalReadiness /></MemoryRouter>);
}
test("names unfinished items concisely while keeping one next action", () => {
  show(ready);
  expect(screen.getByText("口座・保有は登録済みです。")).toBeVisible();
  expect(screen.getByText("各口座の現金が未完了です。")).toBeVisible();
  expect(screen.queryByText(/採用・一致確認/)).not.toBeInTheDocument();
  expect(screen.getByLabelText("未完了の項目")).toHaveTextContent("未完了：現金残高・保有株の価格・残高の確定・最新予測");
  expect(screen.getAllByRole("link")).toHaveLength(1);
  expect(screen.getByRole("link")).toHaveAttribute("href", "/settings?edit=accounts");
  expect(document.querySelector("details")).toBeNull();
});
test("holdings gaps lead directly to the holdings editor, not account settings", () => {
  show({ ...ready, input_gaps: ["holdings_status"] });
  expect(screen.getByRole("link")).toHaveAttribute("href", "/holdings");
});
test("loading never presents previous gaps as current missing registration", () => {
  show(ready, true);
  expect(screen.queryByText("各口座の現金が未完了です。")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("未完了の項目")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("最新の状態を読み込んでいます");
});
test("failed readiness does not imply lost registration", () => {
  show(null, false, "failed");
  expect(screen.getByRole("alert")).toHaveTextContent("登録が消えたわけではありません");
  expect(screen.queryByLabelText("未完了の項目")).not.toBeInTheDocument();
});
test("missing prices route to market before asking to confirm balances", () => {
  show({ ...ready, input_gaps: [] });
  expect(screen.getByRole("link")).toHaveAttribute("href", "/settings?edit=market");
  expect(screen.getByText("残高の確定に必要な保有株の価格を確認できません。")).toBeVisible();
});
test("saved complete inputs without ledger explain the separate confirmation step", () => {
  show({ ...ready, input_gaps: [], initial_ledger: { blocking_reasons: [] } });
  expect(screen.getByText("入力は保存されていますが、残高の確定がまだです。")).toBeVisible();
  expect(screen.getByRole("link", { name: "残高を確認・確定する" })).toHaveAttribute("href", "/settings?edit=accounts");
});
test("confirmed ledger shows missing forecast without repeating setup or raw diagnostics", () => {
  show({ ...ready, input_gaps: [], comparison: { ledger_portfolio_id: "ledger", blocking_reasons: [{ code: "FORECAST_MISSING" }] } });
  expect(screen.getByText("提案に使える最新予測がまだありません。")).toBeVisible();
  expect(screen.queryByText(/FORECAST_MISSING/)).not.toBeInTheDocument();
  expect(screen.getByRole("link")).toHaveAttribute("href", "/settings?edit=model");
  expect(screen.getByLabelText("未完了の項目")).toHaveTextContent("未完了：最新予測");
  expect(proposalBlockLabel("NUMERICAL_FORECAST_INCOMPLETE")).toContain("数値予測がまだ完成していません");
});

test("deduplicates repeated missing fields and omits generic settings when specifics exist", () => {
  show({ ...ready, comparison: { ledger_portfolio_id: null, blocking_reasons: [
    { code: "INPUT_MISSING_AVAILABLE_CASH_YEN" }, { code: "LEDGER_MISSING" }, { code: "SETTINGS_MISSING" },
  ] } });
  expect(screen.getByLabelText("未完了の項目").textContent).toBe("未完了：現金残高・保有株の価格・残高の確定");
});

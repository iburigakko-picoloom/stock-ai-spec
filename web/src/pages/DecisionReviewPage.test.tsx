import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { DecisionReviewPage } from "./DecisionReviewPage";
import { apiGet, apiPost } from "../api";
import { useApiData } from "../hooks";
import { adoptedPayloads } from "../../mobile-tests/adopted-fixture";

vi.mock("../api",()=>({apiGet:vi.fn(),apiPost:vi.fn()}));
vi.mock("../hooks",()=>({useApiData:vi.fn()}));
const payloads=adoptedPayloads(null);
beforeEach(()=>{
  vi.resetAllMocks();
  vi.mocked(useApiData).mockReturnValue({data:payloads["/api/v1/today"],error:null,loading:false,reload:vi.fn(),savedAt:null});
  vi.mocked(apiGet).mockResolvedValue(null);
  vi.mocked(apiPost).mockResolvedValue(payloads["/api/v1/proposals/test-proposal/review"]);
});
afterEach(cleanup);
function open(){render(<MemoryRouter initialEntries={["/today/review?source=chatgpt"]}><DecisionReviewPage /></MemoryRouter>);}

test("legacy source URLs use the numeric proposal and expose no import or source-selection action",async()=>{
  open();
  await waitFor(()=>expect(apiPost).toHaveBeenLastCalledWith("/api/v1/proposals/test-proposal/review",{selectedTargets:{"test-line":200}}));
  expect(screen.queryByRole("button",{name:"ChatGPT"})).not.toBeInTheDocument();
  expect(screen.queryByText("ChatGPT提案を検算 ›")).not.toBeInTheDocument();
  expect(apiGet).not.toHaveBeenCalled();
  await waitFor(()=>expect(screen.getByRole("button",{name:"判断を保存"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"判断を保存"}));
  await screen.findByText("判断を保存しました");
  expect(apiPost).toHaveBeenLastCalledWith("/api/v1/proposals/test-proposal/decisions",expect.objectContaining({lines:[{proposalLineId:"test-line",selectedTargetShares:200}]}));
  expect(vi.mocked(apiPost).mock.calls.some(([path])=>/executions|apply|orders/.test(path))).toBe(false);
});

test.each([null,{recordId:"old",lines:[{symbol:"1234",accountBucketId:"another-account",currentShares:100,targetShares:300}]}])("stored external responses cannot supply a new judgment target",async decision_source=>{
  vi.mocked(apiGet).mockResolvedValue({decision_source});
  open();
  await waitFor(()=>expect(apiPost).toHaveBeenLastCalledWith("/api/v1/proposals/test-proposal/review",{selectedTargets:{"test-line":200}}));
  expect(apiGet).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"画面試験株式会社の提案を採用"}));
  await waitFor(()=>expect(apiPost).toHaveBeenLastCalledWith("/api/v1/proposals/test-proposal/review",{selectedTargets:{"test-line":100}}));
});

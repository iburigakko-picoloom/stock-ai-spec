import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { DecisionReviewPage } from "./DecisionReviewPage";
import { apiGet, apiPost } from "../api";
import { useApiData } from "../hooks";
import { adoptedPayloads } from "../../mobile-tests/adopted-fixture";

vi.mock("../api",()=>({apiGet:vi.fn(),apiPost:vi.fn()}));
vi.mock("../hooks",()=>({useApiData:vi.fn()}));
vi.mock("../mobile/native",()=>({isAndroid:()=>true}));
const payloads=adoptedPayloads(null);
const consultation={recordId:"saved-chatgpt-review",checkedAt:"2026-10-26T11:40:00+09:00",lines:[{symbol:"1234",accountBucketId:"synthetic-account",currentShares:100,targetShares:300}]};
beforeEach(()=>{
  vi.resetAllMocks();
  vi.mocked(useApiData).mockReturnValue({data:payloads["/api/v1/today"],error:null,loading:false,reload:vi.fn(),savedAt:null});
  vi.mocked(apiGet).mockImplementation(async path=>path.endsWith("/status") ? {decision_source:consultation} : null);
  vi.mocked(apiPost).mockResolvedValue(payloads["/api/v1/proposals/test-proposal/review"]);
});
afterEach(cleanup);
function open(){render(<MemoryRouter initialEntries={["/today/review?source=chatgpt"]}><DecisionReviewPage /></MemoryRouter>);}

test("a current ChatGPT review supplies separate targets and keeps its immutable receipt in the saved judgment",async()=>{
  open();
  await waitFor(()=>expect(apiPost).toHaveBeenLastCalledWith("/api/v1/proposals/test-proposal/review",{selectedTargets:{"test-line":300}}));
  expect(screen.getByRole("button",{name:"ChatGPT"})).toHaveAttribute("aria-pressed","true");
  await waitFor(()=>expect(screen.getByRole("button",{name:"判断を保存"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"判断を保存"}));
  await screen.findByText("判断を保存しました");
  expect(apiPost).toHaveBeenLastCalledWith("/api/v1/proposals/test-proposal/decisions",expect.objectContaining({lines:[{proposalLineId:"test-line",selectedTargetShares:300,note:"ChatGPT検算記録 saved-chatgpt-review"}]}));
  expect(vi.mocked(apiPost).mock.calls.some(([path])=>/executions|apply|orders/.test(path))).toBe(false);
  fireEvent.click(screen.getByRole("button",{name:"数値モデル"}));
  await waitFor(()=>expect(apiPost).toHaveBeenLastCalledWith("/api/v1/proposals/test-proposal/review",{selectedTargets:{"test-line":200}}));
});

test.each([null,{...consultation,lines:[{...consultation.lines[0],accountBucketId:"another-account"}]}])("missing or mismatched ChatGPT context blocks judgment saving",async decision_source=>{
  vi.mocked(apiGet).mockResolvedValue({decision_source});
  open();
  await screen.findByText("ChatGPT提案の最新検算が必要です");
  expect(screen.getByRole("button",{name:"判断を保存"})).toBeDisabled();
  expect(apiPost).not.toHaveBeenCalled();
});

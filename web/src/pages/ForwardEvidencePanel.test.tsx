import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ForwardEvidencePanel } from "./ForwardEvidencePanel";
import * as hooks from "../hooks";
import * as native from "../mobile/native";

vi.mock("../mobile/native",()=>({isAndroid:()=>true}));
vi.mock("../hooks",()=>({useApiData:vi.fn()}));
afterEach(()=>vi.restoreAllMocks());

test("daily records load only on request and do not claim outcomes",()=>{
  const use=vi.mocked(hooks.useApiData);
  use.mockImplementation((_path,options)=>({data:options?.enabled ? {runs:[{run_id:"r",as_of:"2026-10-28T11:30:00+09:00",generated_at:"2026-10-28T11:31:00+09:00",prediction_count:10,excluded_candidates:[{}],has_5d_return:true,has_20d_return:true,has_20d_rank:false}]} : null,loading:false,error:null,savedAt:null,reload:vi.fn()}));
  render(<ForwardEvidencePanel />);
  expect(native.isAndroid()).toBe(true);
  expect(use).toHaveBeenLastCalledWith("/api/v1/mobile/forward-evidence",expect.objectContaining({enabled:false}));
  expect(screen.getByText(/実績との比較や最終評価はまだ/)).toBeVisible();
  fireEvent.click(screen.getByRole("button",{name:"記録を確認"}));
  expect(use).toHaveBeenLastCalledWith("/api/v1/mobile/forward-evidence",expect.objectContaining({enabled:true}));
  expect(screen.getByText(/10銘柄 · 予測対象外 1銘柄 · 一部モデル未提供/)).toBeVisible();
});

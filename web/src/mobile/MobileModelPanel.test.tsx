import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { StockAI } from "./native";
import { MobileModelPanel } from "./MobileModelPanel";
import { Activity } from "react";

vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("./native", () => ({ StockAI: { importModel: vi.fn(), analysisStatus: async () => ({ state: "idle" }) }, isAndroid: () => true }));
afterEach(cleanup);
const model = { approved_bundle_count: 1, imported_bundle_count: 1, bundle_ready: true,
  model_adopted: false };
const decision = { run_id: "fixture-decision", phase: "published", outcome: "proposal",
  checked_at: "2026-02-03T11:50:01+09:00", is_active: true, blocking_reasons: [] };
function panel(inputsSaved = true): void {
  render(<MemoryRouter><MobileModelPanel disabled={false} inputsSaved={inputsSaved} onBusy={vi.fn()} /></MemoryRouter>);
}
const run = { run_id: "fixture-run", phase: "published", outcome: "forecast",
  checked_at: "2026-02-03T11:50:00+09:00", scope: { as_of: "2026-02-03T11:30:00+09:00",
    universe: { latest_source_date: "2026-02-02" } },
  snapshot: { generated_at: "2026-02-03T11:50:00+09:00", data_as_of: "2026-02-03T02:15:00Z",
    predictions: [] }, outputs: [
    { horizon: 5, task: "regression", values: [["7203", .01]] },
    { horizon: 20, task: "regression", values: [["7203", .04]] },
  ], excluded_candidates: [{ symbol: "186A", reason: "FEATURE_HISTORY_UNAVAILABLE" }],
  blocking_reasons: [] };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? model : null);
});

test("model and forecast display without waiting for the judgment, while calculation remains gated", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiGet).mockImplementation(path => path.endsWith("/models") ? Promise.resolve(model)
    : path.endsWith("/daily") ? Promise.resolve(run) : new Promise(resolve => {finish=resolve;}));
  panel();
  expect(await screen.findByText("1件取込済み")).toBeVisible();
  expect(await screen.findByText(/推奨株数：確認中/)).toBeVisible();
  expect(screen.getByRole("button",{name:"当日の予測・株数を計算・保存"})).toBeDisabled();
  await act(async () => finish(decision));
  expect(screen.getByText(/推奨株数：保存済み・研究用/)).toBeVisible();
  expect(screen.getByRole("button",{name:"当日の予測・株数を計算・保存"})).toBeEnabled();
});

test("a late initial model read cannot overwrite a successfully imported model", async () => {
  let finish!: (value: unknown) => void;
  let calls=0;
  vi.mocked(apiGet).mockImplementation(path => path.endsWith("/models")
    ? ++calls === 1 ? new Promise(resolve => {finish=resolve;}) : Promise.resolve({...model,imported_bundle_count:2})
    : Promise.resolve(null));
  vi.mocked(StockAI.importModel).mockResolvedValue({content:"synthetic bundle"});
  vi.mocked(apiPost).mockResolvedValue({});
  panel();
  await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/api/v1/mobile/models"));
  fireEvent.click(screen.getByRole("button",{name:"モデル一式を取り込む"}));
  expect(await screen.findByText("2件取込済み")).toBeVisible();
  await act(async () => finish(model));
  expect(screen.getByText("2件取込済み")).toBeVisible();
});

test("a failed judgment read leaves the independently loaded model and forecast visible, but blocks calculation", async () => {
  vi.mocked(apiGet).mockImplementation(async path=>{
    if(path.endsWith("/decision"))throw new Error("failed");
    return path.endsWith("/models") ? model : run;
  });
  panel();
  expect(await screen.findByText("1件取込済み")).toBeVisible();
  expect(await screen.findByRole("alert")).toHaveTextContent("確認できません");
  expect(screen.getByText(/推奨株数：未確認/)).toBeVisible();
  expect(screen.getByRole("button",{name:"当日の予測・株数を計算・保存"})).toBeDisabled();
});

test("failed recheck after model import cannot enable calculation with the previous bundle", async () => {
  let reads=0;
  vi.mocked(apiGet).mockImplementation(async path=>{
    if(path.endsWith("/models") && ++reads>1)throw new Error("再確認失敗");
    return path.endsWith("/models") ? model : null;
  });
  vi.mocked(StockAI.importModel).mockResolvedValue({content:"synthetic bundle"});
  vi.mocked(apiPost).mockResolvedValue({});
  panel();
  await waitFor(()=>expect(screen.getByRole("button",{name:"当日の予測・株数を計算・保存"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"モデル一式を取り込む"}));
  await waitFor(()=>expect(screen.getByRole("status")).toHaveTextContent("再確認失敗"));
  expect(screen.getByRole("button",{name:"当日の予測・株数を計算・保存"})).toBeDisabled();
  expect(screen.queryByText("1件取込済み")).not.toBeInTheDocument();
});

test("reopening keeps prior output read-only until current model and judgment are verified", async () => {
  vi.mocked(apiGet).mockImplementation(async path=>path.endsWith("/models") ? {...model,bundle_blocking_reason:"old"} : path.endsWith("/daily") ? run : decision);
  const content=(visible:boolean)=><MemoryRouter><Activity mode={visible ? "visible" : "hidden"}><MobileModelPanel disabled={false} inputsSaved onBusy={vi.fn()} /></Activity></MemoryRouter>;
  const view=render(content(true));
  await screen.findByRole("link",{name:"今日の判定を見る"});
  view.rerender(content(false));
  const pending: Record<string,(value:unknown)=>void> = {};
  vi.mocked(apiGet).mockImplementation(path=>new Promise(resolve=>{pending[path]=resolve;}));
  view.rerender(content(true));
  await waitFor(()=>expect(Object.keys(pending)).toHaveLength(1));
  expect(screen.getByText(/前回の表示・閲覧用/)).toBeVisible();
  expect(screen.queryByText("保存済みの一式を利用できません。確認済みのファイルを取り込んでください。")).not.toBeInTheDocument();
  expect(screen.queryByRole("link",{name:"今日の判定を見る"})).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"当日の予測・株数を計算・保存"})).toBeDisabled();
  await act(async()=>pending["/api/v1/mobile/daily"](run));
  await waitFor(()=>expect(pending["/api/v1/mobile/models"]).toBeDefined());
  await act(async()=>pending["/api/v1/mobile/models"](model));
  await waitFor(()=>expect(pending["/api/v1/mobile/decision"]).toBeDefined());
  await act(async()=>pending["/api/v1/mobile/decision"](decision));
  expect(await screen.findByRole("link",{name:"今日の判定を見る"})).toBeVisible();
});

test("leaving a model panel stops the two remaining interpreter reads", async () => {
  let finish!: (value:unknown)=>void;
  vi.mocked(apiGet).mockReturnValue(new Promise(resolve=>{finish=resolve;}));
  const content=(visible:boolean)=><MemoryRouter><Activity mode={visible ? "visible" : "hidden"}><MobileModelPanel disabled={false} inputsSaved onBusy={vi.fn()} /></Activity></MemoryRouter>;
  const view=render(content(true));
  expect(apiGet).toHaveBeenCalledTimes(1);
  expect(apiGet).toHaveBeenCalledWith("/api/v1/mobile/daily");
  view.rerender(content(false));
  await act(async()=>finish(model));
  expect(apiGet).toHaveBeenCalledTimes(1);
});

test("saved numerical results remain visible when model verification is slow", async () => {
  let finish!: (value:unknown)=>void;
  vi.mocked(apiGet).mockImplementation(path => path.endsWith("/daily") ? Promise.resolve(run)
    : path.endsWith("/models") ? new Promise(resolve => {finish=resolve;}) : Promise.resolve(decision));
  panel();
  expect(await screen.findByText("算出できた予測を見る 1社")).toBeVisible();
  expect(screen.getByRole("cell", {name:"4%"})).toBeVisible();
  expect(screen.getByRole("button",{name:"当日の予測・株数を計算・保存"})).toBeDisabled();
  await act(async()=>finish(model));
  await waitFor(()=>expect(screen.getByRole("button",{name:"当日の予測・株数を計算・保存"})).toBeEnabled());
});

test("saved numerical results are readable while the account is unverified", async () => {
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? model : path.endsWith("/daily") ? run : decision);
  panel(false);
  expect(await screen.findByRole("cell",{name:"4%"})).toBeVisible();
  expect(screen.getByRole("button",{name:"当日の予測・株数を計算・保存"})).toBeDisabled();
});

test("a failed model check can be retried without losing the saved result", async () => {
  let checks=0;
  vi.mocked(apiGet).mockImplementation(async path => {
    if(path.endsWith("/daily"))return run;
    if(path.endsWith("/models") && ++checks===1)throw new Error("failed");
    return path.endsWith("/models") ? model : decision;
  });
  panel();
  expect(await screen.findByRole("alert")).toHaveTextContent("一部を確認できませんでした");
  expect(screen.getByRole("cell",{name:"4%"})).toBeVisible();
  fireEvent.click(screen.getByRole("button",{name:"もう一度確認"}));
  await waitFor(()=>expect(screen.getByRole("button",{name:"当日の予測・株数を計算・保存"})).toBeEnabled());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
test("one file imports the reviewed bundle and refreshes saved status", async () => {
  vi.mocked(StockAI.importModel).mockResolvedValue({ content: "synthetic bundle file" });
  panel();
  const button = screen.getByRole("button", { name: "モデル一式を取り込む" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/models/import", { content: "synthetic bundle file" }));
  expect(screen.getByText("研究用・正式採用前")).toBeVisible();
});
test("first model import is available without a previously installed bundle", async () => {
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? { ...model, approved_bundle_count: 0, imported_bundle_count: 0, bundle_ready: false } : null);
  panel();
  await screen.findByText("0件取込済み");
  expect(screen.getByRole("button", { name: "モデル一式を取り込む" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "当日の予測・株数を計算・保存" })).toBeDisabled();
});
test("reference analysis runs in model settings and model errors do not link back to itself", async () => {
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? model : path.endsWith("/daily") ? { ...run, blocking_reasons: ["ALPHA_CUTOFF_OPEN"] } : null);
  vi.mocked(apiPost).mockResolvedValue({ phase: "blocked", blocking_reasons: ["CALIBRATED_MODEL_BUNDLE_UNAVAILABLE"] });
  render(<MemoryRouter initialEntries={["/settings?edit=model"]}><MobileModelPanel disabled={false} inputsSaved onBusy={vi.fn()} /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "ランキングを更新" }));
  await screen.findByText("取り込んだモデルの利用条件を確認してください。");
  expect(apiPost).toHaveBeenCalledWith("/api/v1/mobile/daily/generate", { reference_only: true });
  expect(screen.queryByRole("link", { name: "ランキングを作る" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "登録内容を確認する" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "モデル一式を取り込む" })).toBeEnabled();
});

test("native analysis owns both stages without a second page-owned request", async () => {
  vi.mocked(apiPost).mockResolvedValue({ ...run, manual_decision: decision });
  panel();
  const button = screen.getByRole("button", { name: "当日の予測・株数を計算・保存" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("予測と株数の判定を保存"));
  expect(apiPost).toHaveBeenCalledTimes(1);
});
test("frozen timestamps, excluded candidates and stored output remain readable", async () => {
  vi.mocked(apiPost).mockImplementation(async path => path.includes("/decision/") ? decision : run);
  panel();
  const button = screen.getByRole("button", { name: "当日の予測・株数を計算・保存" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("予測と株数の判定を保存"));
  expect(vi.mocked(apiPost).mock.calls.map(call => call[0])).toEqual([
    "/api/v1/mobile/daily/generate", "/api/v1/mobile/decision/generate",
  ]);
  expect(screen.getByText(/数値生成：/)).toHaveTextContent("2026/2/3 11:50:00 JST");
  expect(screen.getByText(/参照情報の受領：/)).toHaveTextContent("2026/2/3 11:15:00 JST");
  expect(screen.getByText("2026/2/3 11:15:00 JST")).toHaveAttribute("datetime", "2026-02-03T02:15:00Z");
  expect(screen.getByText(/推奨株数/)).toHaveTextContent("保存済み・研究用");
  expect(screen.getByRole("link", { name: "今日の判定を見る" })).toHaveAttribute("href", "/today");
  fireEvent.click(screen.getByText("算出できた予測を見る 1社"));
  expect(screen.getByRole("cell", { name: "4%" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "4. 除外銘柄" })).toBeVisible();
  expect(screen.getByText("186A", { exact: true })).toBeVisible();
});
test("missing held prediction is incomplete with useful preserved numeric output", async () => {
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? model : path.endsWith("/decision") ? null : {
    ...run, snapshot: null, phase: "blocked", outcome: "blocked", blocking_reasons: ["HELD_FORECAST_MISSING:1234"],
  });
  panel();
  await waitFor(() => expect(screen.getByText(/保有1234の予測/)).toBeVisible());
  expect(screen.getByText("算出できた予測を見る 1社")).toBeVisible();
});
test("unsaved personal changes disable generation while import remains available", async () => {
  panel(false);
  await waitFor(() => expect(screen.getByRole("button", { name: "モデル一式を取り込む" })).toBeEnabled());
  expect(screen.getByRole("button", { name: "当日の予測・株数を計算・保存" })).toBeDisabled();
});
test("quantity save failure preserves the already saved numerical stage", async () => {
  vi.mocked(apiPost).mockResolvedValueOnce(run).mockRejectedValueOnce(new Error("株数の保存を再開してください"));
  panel();
  const button = screen.getByRole("button", { name: "当日の予測・株数を計算・保存" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("株数の保存を再開"));
  fireEvent.click(screen.getByText("計算時刻・参照情報"));
  expect(screen.getByText(/数値生成：/)).toBeVisible();
  expect(screen.queryByRole("link", { name: "今日の判定を見る" })).not.toBeInTheDocument();
});
test.each(["cash_only", "proposal"])("saved %s receipt displays only while its references are current", async outcome => {
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? model : path.endsWith("/daily") ? run : { ...decision, outcome, is_active: false });
  panel();
  await waitFor(() => expect(screen.getByText(/保存後に入力や計算対象が変わっています/)).toBeVisible());
  expect(screen.queryByRole("link", { name: "今日の判定を見る" })).not.toBeInTheDocument();
});

test("return-only research imports without adoption and opens manual consultation", async () => {
  const research = { ...model, approved_bundle_count: 0, research_bundle_count: 1,
    return_only_research: true, risk_available: false };
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? research : null);
  vi.mocked(apiPost).mockImplementation(async path => path.includes("/decision/") ? {
    ...decision, outcome: "blocked", phase: "blocked", is_active: false,
    blocking_reasons: ["FORECAST_RISK_UNAVAILABLE"],
  } : { ...run, snapshot: { ...run.snapshot, candidate_symbols: ["7203"], holding_symbols: ["7203"] } });
  panel();
  await waitFor(() => expect(screen.getByRole("button", { name: "モデル一式を取り込む" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "当日の予測を計算・保存" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("ChatGPTへの相談"));
  expect(screen.getByRole("link", { name: "予測を使ってChatGPTへ相談する" })).toHaveAttribute("href", "/today/chatgpt");
  expect(screen.queryByRole("link", { name: "今日の判定を見る" })).not.toBeInTheDocument();
  expect(screen.getByText(/自動判定に必要なリスク情報・検証がそろっていません/)).toBeVisible();
  expect(screen.getByText(/分析はChatGPTで確認できます/)).toBeVisible();
  expect(screen.queryByText(/回答の検算/)).not.toBeInTheDocument();
  expect(screen.getByText("上位20と全保有の予測を見る 1社")).toBeVisible();
  expect(screen.getByText("研究用・正式採用前")).toBeVisible();
});

test("rank-only research preserves units, all holdings and unavailable returns", async () => {
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith("/models") ? {
    ...model, approved_bundle_count: 0, research_bundle_count: 1, ensemble_research: true,
  } : null);
  vi.mocked(apiPost).mockImplementation(async path => path.includes("/decision/") ? {
    ...decision, outcome: "blocked", phase: "blocked", is_active: false,
    blocking_reasons: ["FORECAST_RISK_UNAVAILABLE"],
  } : { ...run, snapshot: { ...run.snapshot, candidate_symbols: ["1000"], holding_symbols: ["7203"] },
    outputs: [
      { horizon: 5, role: "ranking", values: [["1000", .4], ["7203", .2]] },
      { horizon: 20, role: "ranking", values: [["1000", .9], ["7203", .1]] },
    ] });
  panel();
  const button = await screen.findByRole("button", { name: "当日の予測を計算・保存" });
  fireEvent.click(button);
  const summary = await screen.findByText("上位20と全保有の予測を見る 2社");
  fireEvent.click(summary);
  expect(screen.getByRole("columnheader", { name: "20日順位スコア" })).toBeVisible();
  expect(screen.getByRole("cell", { name: "0.9000" })).toBeVisible();
  expect(screen.getByRole("link", { name: "7203" })).toBeVisible();
  expect(screen.getAllByRole("cell", { name: "未提供" })).toHaveLength(4);
  expect(screen.queryByText(/NaN|90%/)).not.toBeInTheDocument();
  expect(screen.getByText(/期待リターン率ではありません/)).toBeVisible();
});


test("cutoff rejection is shown once and never claims a saved prediction", async () => {
  const blocked = { ...run, phase: "blocked", outcome: "blocked", snapshot: null,
    outputs: [], blocking_reasons: ["ALPHA_CUTOFF_OPEN"] };
  vi.mocked(apiPost).mockImplementation(async path => path.includes("/decision/") ? {
    ...decision, phase: "blocked", is_active: false, blocking_reasons: ["ALPHA_CUTOFF_OPEN"],
  } : blocked);
  panel();
  const button = screen.getByRole("button", { name: "当日の予測・株数を計算・保存" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("予測は未完了"));
  expect(screen.getAllByText("11:30の締切後に計算できます。")).toHaveLength(1);
  expect(screen.getByText("1件取込済み")).toBeVisible();
  expect(screen.getByRole("status")).not.toHaveTextContent("保存しました");
});

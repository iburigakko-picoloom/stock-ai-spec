import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ManualChatGPTPage } from "./ManualChatGPTPage";
import { apiGet, apiPost } from "../api";
import { useApiData } from "../hooks";

vi.mock("../mobile/native",()=>({isAndroid:()=>true,StockAI:{}}));
vi.mock("../hooks",()=>({useApiData:vi.fn(()=>({data:null,loading:false,error:null}))}));
vi.mock("../api",()=>({apiGet:vi.fn(),apiPost:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();vi.unstubAllGlobals();});
beforeEach(()=>vi.mocked(useApiData).mockReturnValue({data:null,loading:false,error:null,savedAt:null,reload:vi.fn()}));
function show(path="/today/chatgpt"){render(<MemoryRouter initialEntries={[path]}><ManualChatGPTPage /></MemoryRouter>);}
const savedInput={input_record_id:"saved-input",input_snapshot_id:"snapshot",expires_at:"2026-10-26T12:00:00+09:00",prompt:"保存済みの合成プロンプト",response_mode:"chatgpt-readable-report-v2"};
function resumedStatus(){return {ready:true,reason:null,selected_input:savedInput.input_record_id,saved_input:savedInput,answers:[]};}

test("saved records remain readable without an import or review action",async()=>{
  vi.mocked(apiGet).mockResolvedValue({ready:false,reason:"期限切れ",selected_input:null,answers:[],research:[{record_id:"saved",saved_at:"2026-10-26T09:00:00Z",original_json:"保存した回答原本"}]});
  show("/today/chatgpt/history");
  expect(await screen.findByText("保存した回答原本")).toBeVisible();
  expect(useApiData).toHaveBeenCalledWith("/api/v1/mobile/ranking/20d", { enabled: false });
  expect(screen.queryByRole("button",{name:"検証・保存"})).not.toBeInTheDocument();
  expect(screen.queryByRole("link",{name:"以前の回答を保存・検算"})).not.toBeInTheDocument();
  expect(apiPost).not.toHaveBeenCalled();
});

test("missing model or inputs stays blocked without an export",async()=>{
  vi.mocked(apiGet).mockResolvedValue({ready:false,reason:"原予測が未採用です",selected_input:null,answers:[]});
  show();
  expect(await screen.findByText("原予測が未採用です")).toBeVisible();
  expect(useApiData).toHaveBeenCalledWith("/api/v1/mobile/ranking/20d", { enabled: true });
  expect(screen.getByRole("button",{name:"作成・コピー"})).toBeDisabled();
  expect(apiPost).not.toHaveBeenCalled();
});

test("explicit conditions precede export and copy; no answer callback remains",async()=>{
  const clipboard=vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator",{clipboard:{writeText:clipboard}});
  vi.mocked(apiGet).mockResolvedValue({ready:true,reason:null,selected_input:null,answers:[]});
  vi.mocked(apiPost).mockResolvedValue(savedInput);
  show();
  const create=await screen.findByRole("button",{name:"作成・コピー"});
  expect(create).toBeDisabled();
  for(const checkbox of screen.getAllByRole("checkbox"))fireEvent.click(checkbox);
  fireEvent.click(create);
  await waitFor(()=>expect(clipboard).toHaveBeenCalledExactlyOnceWith(savedInput.prompt));
  expect(screen.getByRole("textbox",{name:"ChatGPTへ渡す入力"})).toHaveValue(savedInput.prompt);
  expect(screen.getByRole("link",{name:"ChatGPTを開く"})).toHaveAttribute("href","https://chatgpt.com/");
  expect(screen.queryByRole("textbox",{name:"ChatGPTの回答JSON"})).not.toBeInTheDocument();
  expect(apiPost).toHaveBeenCalledExactlyOnceWith("/api/v1/mobile/chatgpt-manual/export",expect.objectContaining({training_disabled:true,data_entitlement_confirmed:true}));
});

test("old legacy URLs cannot expose answer input, saving, or review controls",async()=>{
  vi.mocked(apiGet).mockResolvedValue({...resumedStatus(),research:[{record_id:"saved",saved_at:"2026-10-26T09:00:00Z",original_json:"保存原本"}]});
  show("/today/chatgpt?legacy=1");
  await screen.findByRole("button",{name:"プロンプトをコピー"});
  for(const label of ["ChatGPTの回答JSON","回答JSON"])expect(screen.queryByRole("textbox",{name:label})).not.toBeInTheDocument();
  for(const label of ["検証・保存","最新の条件で検算"])expect(screen.queryByRole("button",{name:label})).not.toBeInTheDocument();
  expect(apiPost).not.toHaveBeenCalled();
});

test("a cached legacy JSON-only prompt is not resumed for new consultation",async()=>{
  vi.mocked(apiGet).mockResolvedValue({...resumedStatus(),saved_input:{...savedInput,response_mode:undefined,prompt:"旧形式の相談文"}});
  show();
  await screen.findByRole("button",{name:"作成・コピー"});
  expect(screen.queryByRole("textbox",{name:"ChatGPTへ渡す入力"})).not.toBeInTheDocument();
  expect(apiPost).not.toHaveBeenCalled();
});

test("a saved v1 prompt is not reused after the risk research instructions change",async()=>{
  vi.mocked(apiGet).mockResolvedValue({...resumedStatus(),saved_input:{...savedInput,response_mode:"chatgpt-readable-report-v1",prompt:"以前の相談文"}});
  show();
  await screen.findByRole("button",{name:"作成・コピー"});
  expect(screen.queryByRole("textbox",{name:"ChatGPTへ渡す入力"})).not.toBeInTheDocument();
});

test("reopening restores the exact readable input without another export or permission",async()=>{
  vi.mocked(apiGet).mockResolvedValue(resumedStatus());
  show();
  expect(await screen.findByRole("textbox",{name:"ChatGPTへ渡す入力"})).toHaveValue(savedInput.prompt);
  expect(screen.getByRole("button",{name:"作成・コピー"})).toBeDisabled();
  for(const checkbox of screen.getAllByRole("checkbox"))expect(checkbox).not.toBeChecked();
  expect(apiPost).not.toHaveBeenCalled();
});

test("copy waits for current local permission and input checks",async()=>{
  const clipboard=vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator",{clipboard:{writeText:clipboard}});
  let finish!:(value:unknown)=>void;
  vi.mocked(apiGet).mockResolvedValueOnce(resumedStatus()).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  show();
  fireEvent.click(await screen.findByRole("button",{name:"プロンプトをコピー"}));
  expect(clipboard).not.toHaveBeenCalled();
  expect(screen.getByRole("button",{name:"プロンプトをコピー"})).toBeDisabled();
  finish(resumedStatus());
  expect(await screen.findByText("プロンプトをコピーしました。")).toBeVisible();
  expect(clipboard).toHaveBeenCalledExactlyOnceWith(savedInput.prompt);
  expect(apiPost).not.toHaveBeenCalled();
});

test.each(["expired","changed","snapshot","unavailable"])("copy rejects %s context without changing the saved prompt",async change=>{
  const clipboard=vi.fn();
  vi.stubGlobal("navigator",{clipboard:{writeText:clipboard}});
  vi.mocked(apiGet).mockResolvedValueOnce(resumedStatus());
  if(change==="unavailable")vi.mocked(apiGet).mockRejectedValueOnce(new Error("offline core"));
  else vi.mocked(apiGet).mockResolvedValueOnce(change==="expired"
    ? {...resumedStatus(),saved_input:null,saved_input_reason:"送信許可が期限切れです"}
    : change==="snapshot" ? {...resumedStatus(),ready:false,reason:"保有が更新されています",saved_input:null}
    : {...resumedStatus(),saved_input:{...savedInput,input_record_id:"different"}});
  show();
  const input=await screen.findByRole("textbox",{name:"ChatGPTへ渡す入力"});
  fireEvent.click(screen.getByRole("button",{name:"プロンプトをコピー"}));
  expect(await screen.findByText("処理を完了できません")).toBeVisible();
  expect(clipboard).not.toHaveBeenCalled();expect(input).toHaveValue(savedInput.prompt);
  expect(apiPost).not.toHaveBeenCalled();
});

test("a failed new export preserves the saved readable prompt",async()=>{
  vi.mocked(apiGet).mockResolvedValue(resumedStatus());
  vi.mocked(apiPost).mockRejectedValueOnce(new Error("入力条件が変わりました"));
  show();
  const input=await screen.findByRole("textbox",{name:"ChatGPTへ渡す入力"});
  for(const checkbox of screen.getAllByRole("checkbox"))fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button",{name:"作成・コピー"}));
  expect(await screen.findByText("入力条件が変わりました")).toBeVisible();
  expect(input).toHaveValue(savedInput.prompt);
});


test("consultation status is read before the optional ranking and remains usable while it loads", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiGet).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  vi.mocked(useApiData).mockReturnValue({data:null,loading:true,error:null,savedAt:null,reload:vi.fn()});
  show();
  expect(useApiData).toHaveBeenLastCalledWith("/api/v1/mobile/ranking/20d", { enabled: false });
  expect(apiGet).toHaveBeenCalledExactlyOnceWith("/api/v1/mobile/chatgpt-manual/status");
  await act(async () => { finish({ ready:true,reason:null,selected_input:null,answers:[] }); });
  expect(useApiData).toHaveBeenLastCalledWith("/api/v1/mobile/ranking/20d", { enabled: true });
  expect(screen.getByRole("button", { name:"作成・コピー" })).toBeVisible();
  expect(screen.getByText("相談対象を確認しています…")).toBeVisible();
  expect(screen.queryByText("相談対象を確認できません。最新の原予測を確認してください。")).not.toBeInTheDocument();
});

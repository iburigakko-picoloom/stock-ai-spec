import { afterEach, expect, test, vi } from "vitest";
import { apiGet, apiPost } from "./api";
import { isAndroid } from "./mobile/native";
import { mobileRequest } from "./mobile/runtime";
vi.mock("./mobile/native",()=>({isAndroid:vi.fn(()=>false)}));
vi.mock("./mobile/runtime",()=>({mobileRequest:vi.fn()}));
afterEach(()=>{vi.restoreAllMocks();vi.resetAllMocks();vi.unstubAllGlobals();});
const response=(value:unknown)=>new Response(JSON.stringify(value),{headers:{"Content-Type":"application/json"}});
test("concurrent reads share one request but their callers own independent data",async()=>{
  let finish!:(value:Response)=>void;
  const fetcher=vi.fn(()=>new Promise<Response>(resolve=>{finish=resolve;}));vi.stubGlobal("fetch",fetcher);
  const first=apiGet<{rows:number[]}>("/same"),second=apiGet<{rows:number[]}>("/same");
  expect(fetcher).toHaveBeenCalledTimes(1);finish(response({rows:[1]}));
  const [a,b]=await Promise.all([first,second]);a.rows.push(2);expect(b.rows).toEqual([1]);
  const third=apiGet("/same");expect(fetcher).toHaveBeenCalledTimes(2);finish(response({rows:[3]}));await third;
});
test("failed reads are not reused by a retry",async()=>{
  const fetcher=vi.fn().mockRejectedValueOnce(new Error("unavailable")).mockResolvedValue(response({ok:true}));vi.stubGlobal("fetch",fetcher);
  await expect(apiGet("/retry")).rejects.toThrow("unavailable");await expect(apiGet("/retry")).resolves.toEqual({ok:true});expect(fetcher).toHaveBeenCalledTimes(2);
});
test("a native save fences reads both before and during the write",async()=>{
  vi.mocked(isAndroid).mockReturnValue(true);
  const finish:((value:unknown)=>void)[]=[];
  vi.mocked(mobileRequest).mockImplementation(()=>new Promise(resolve=>finish.push(resolve)));
  const before=apiGet("/balance");const write=apiPost("/balance",{value:2});const during=apiGet("/balance");
  expect(mobileRequest).toHaveBeenCalledTimes(3);finish[1]({saved:true});await write;
  const after=apiGet("/balance");expect(mobileRequest).toHaveBeenCalledTimes(4);
  finish[0]({value:0});finish[2]({value:1});finish[3]({value:2});
  expect(await before).toEqual({value:0});expect(await during).toEqual({value:1});expect(await after).toEqual({value:2});
});

import { expect, test, vi } from "vitest";
import { visibleReads } from "./visibleReads";

test("closing a panel stops undispatched reads while the current read finishes", async () => {
  let active = true;
  let finish!: () => void;
  const first=vi.fn(()=>new Promise<void>(resolve=>{finish=resolve;}));
  const second=vi.fn(async()=>{}), third=vi.fn(async()=>{}), error=vi.fn();
  const result=visibleReads([first,second,third],()=>active,true,error);
  expect(first).toHaveBeenCalledOnce(); expect(second).not.toHaveBeenCalled();
  active=false; finish();
  expect(await result).toBe(false);
  expect(second).not.toHaveBeenCalled(); expect(third).not.toHaveBeenCalled(); expect(error).not.toHaveBeenCalled();
});

test("a failed read reports failure yet later independent results still load", async () => {
  const error=vi.fn(), second=vi.fn(async()=>{});
  const result=await visibleReads([async()=>{throw Error("failed");},second],()=>true,true,error);
  expect(result).toBe(false); expect(error).toHaveBeenCalledOnce(); expect(second).toHaveBeenCalledOnce();
});

test("closing after the first result preserves it but stops later queued reads", async () => {
  let active=true, finish!:()=>void;
  const first=vi.fn(async()=>{}), second=vi.fn(()=>new Promise<void>(resolve=>{finish=resolve;})), third=vi.fn(async()=>{});
  const result=visibleReads([first,second,third],()=>active,true,vi.fn());
  await Promise.resolve(); await Promise.resolve();
  expect(first).toHaveBeenCalledOnce(); expect(second).toHaveBeenCalledOnce();
  active=false; finish();
  expect(await result).toBe(false); expect(third).not.toHaveBeenCalled();
});

test("web reads are dispatched concurrently", async () => {
  let finish!:()=>void;
  const first=vi.fn(()=>new Promise<void>(resolve=>{finish=resolve;}));
  const second=vi.fn(async()=>{});
  const result=visibleReads([first,second],()=>true,false,vi.fn());
  expect(first).toHaveBeenCalledOnce(); expect(second).toHaveBeenCalledOnce();
  finish(); expect(await result).toBe(true);
});

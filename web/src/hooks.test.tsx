import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiGet } from "./api";
import { isAndroid, StockAI } from "./mobile/native";
import { useApiData } from "./hooks";

vi.mock("./api", () => ({ apiGet: vi.fn() }));
vi.mock("./mobile/native", () => ({ isAndroid: vi.fn(), StockAI: { readSavedView: vi.fn() } }));
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(StockAI.readSavedView).mockResolvedValue({ available: false });
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
  vi.mocked(apiGet).mockResolvedValue({ saved: 1 });
});

test("saved display arrives while authoritative computation is pending, then is replaced", async () => {
  vi.mocked(isAndroid).mockReturnValue(true);
  let resolve!: (value: unknown) => void;
  vi.mocked(apiGet).mockReturnValue(new Promise(done => { resolve = done; }));
  const savedAt = "2026-01-01T00:00:00Z";
  vi.mocked(StockAI.readSavedView).mockResolvedValue({ available: true, readOnly: true, savedAt, body: { saved: 7 } });
  const { result } = renderHook(() => useApiData("/api/v1/today"));
  await waitFor(() => expect(result.current.data).toEqual({ saved: 7 }));
  expect(result.current.loading).toBe(true);
  expect(result.current.savedAt).toBe(savedAt);
  await act(async () => resolve({ saved: 8 }));
  expect(result.current.data).toEqual({ saved: 8 });
  expect(result.current.savedAt).toBeNull();
});

test("Android home ledger shows a labeled historical copy only until fresh verification", async () => {
  vi.mocked(isAndroid).mockReturnValue(true);
  let finish!: (value: unknown) => void;
  vi.mocked(apiGet).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  vi.mocked(StockAI.readSavedView).mockResolvedValue({available:true,readOnly:true,savedAt:"2026-01-01T00:00:00Z",body:{balance:"old"}});
  const {result}=renderHook(()=>useApiData("/api/v1/home/ledger"));
  await waitFor(()=>expect(result.current.data).toEqual({balance:"old"}));
  expect(result.current.savedAt).toBe("2026-01-01T00:00:00Z");
  expect(result.current.loading).toBe(true);
  await waitFor(()=>expect(apiGet).toHaveBeenCalledWith("/api/v1/home/ledger"));
  await act(async()=>finish({balance:"current"}));
  expect(result.current.data).toEqual({balance:"current"});
  expect(result.current.savedAt).toBeNull();
});

test("failed home ledger verification removes its historical display", async () => {
  vi.mocked(isAndroid).mockReturnValue(true);
  let fail!: (reason: Error) => void;
  vi.mocked(apiGet).mockReturnValue(new Promise((_resolve,reject) => {fail=reject;}));
  vi.mocked(StockAI.readSavedView).mockResolvedValue({available:true,readOnly:true,savedAt:"2026-01-01T00:00:00Z",body:{balance:"old"}});
  const {result}=renderHook(()=>useApiData("/api/v1/home/ledger"));
  await waitFor(()=>expect(result.current.data).toEqual({balance:"old"}));
  await waitFor(()=>expect(apiGet).toHaveBeenCalledWith("/api/v1/home/ledger"));
  await act(async()=>fail(new Error("検証失敗")));
  expect(result.current.data).toBeNull();
  expect(result.current.savedAt).toBeNull();
  expect(result.current.error).toBe("検証失敗");
});

test("late saved display cannot overwrite fresh data and is never read for decision routes", async () => {
  vi.mocked(isAndroid).mockReturnValue(true);
  let resolve!: (value: { available: boolean; readOnly: boolean; savedAt: string; body: unknown }) => void;
  vi.mocked(StockAI.readSavedView).mockReturnValue(new Promise(done => { resolve = done; }));
  const { result, unmount } = renderHook(() => useApiData("/api/v1/home"));
  await waitFor(() => expect(result.current.data).toEqual({ saved: 1 }));
  await act(async () => resolve({ available: true, readOnly: true, savedAt: "2026-01-01T00:00:00Z", body: { saved: 0 } }));
  expect(result.current.data).toEqual({ saved: 1 });
  unmount(); vi.mocked(StockAI.readSavedView).mockClear();
  renderHook(() => useApiData("/api/v1/today/review"));
  expect(StockAI.readSavedView).not.toHaveBeenCalled();
});
test("authoritative failure removes a previously displayed saved view", async () => {
  vi.mocked(isAndroid).mockReturnValue(true);
  let reject!: (error: Error) => void;
  vi.mocked(apiGet).mockReturnValue(new Promise((_done, fail) => { reject = fail; }));
  vi.mocked(StockAI.readSavedView).mockResolvedValue({ available: true, readOnly: true, savedAt: "2026-01-01T00:00:00Z", body: { saved: 7 } });
  const { result } = renderHook(() => useApiData("/api/v1/today"));
  await waitFor(() => expect(result.current.data).toEqual({ saved: 7 }));
  await act(async () => reject(new Error("integrity failure")));
  expect(result.current.data).toBeNull();
  expect(result.current.savedAt).toBeNull();
  expect(result.current.error).toBe("integrity failure");
});

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

test("periodic checks do not discard a cold read lasting longer than two minutes", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  vi.mocked(isAndroid).mockReturnValue(true);
  const finishes: ((value: unknown) => void)[] = [];
  vi.mocked(apiGet).mockImplementation(() => new Promise(resolve => finishes.push(resolve)));
  const { result } = renderHook(() => useApiData("/api/v1/today"));
  await act(async () => { await vi.advanceTimersByTimeAsync(125_000); });
  expect(apiGet).toHaveBeenCalledTimes(1);
  await act(async () => finishes[0]({ savedAnalysis: { snapshotId: "saved-analysis" } }));
  expect(result.current.data).toEqual({ savedAnalysis: { snapshotId: "saved-analysis" } });
  expect(result.current.loading).toBe(false);
  expect(apiGet).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(55_000); });
  expect(apiGet).toHaveBeenCalledTimes(2);
  await act(async () => finishes[1]({ savedAnalysis: null }));
  expect(result.current.data).toEqual({ savedAnalysis: null });
});

test("Android rereads authoritative local results when offline or returning from a notification", async () => {
  vi.mocked(isAndroid).mockReturnValue(true);
  const { result } = renderHook(() => useApiData<{ saved: number }>("/api/v1/today"));
  await waitFor(() => expect(result.current.data).toEqual({ saved: 1 }));
  vi.mocked(apiGet).mockResolvedValue({ saved: 2 });
  act(() => window.dispatchEvent(new Event("offline")));
  await waitFor(() => expect(result.current.data).toEqual({ saved: 2 }));
  expect(result.current.error).toBeNull();
  vi.mocked(apiGet).mockResolvedValue({ saved: 3 });
  act(() => window.dispatchEvent(new Event("focus")));
  await waitFor(() => expect(result.current.data).toEqual({ saved: 3 }));
});

test("web offline behavior still hides a potentially stale proposal", async () => {
  vi.mocked(isAndroid).mockReturnValue(false);
  const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  const { result } = renderHook(() => useApiData("/api/v1/today"));
  await waitFor(() => expect(result.current.data).toEqual({ saved: 1 }));
  online.mockReturnValue(false);
  act(() => window.dispatchEvent(new Event("offline")));
  expect(result.current.data).toBeNull();
  expect(result.current.error).toContain("オフライン");
  act(() => window.dispatchEvent(new Event("focus")));
  expect(apiGet).toHaveBeenCalledTimes(1);
});

test("pending refreshes drain once and superseded responses never publish", async () => {
  vi.mocked(isAndroid).mockReturnValue(true);
  const finishes: ((value: unknown) => void)[] = [];
  vi.mocked(apiGet).mockImplementation(() => new Promise(resolve => finishes.push(resolve)));
  const { result } = renderHook(() => useApiData("/first"));
  act(() => { result.current.reload(); result.current.reload(); window.dispatchEvent(new Event("focus")); });
  expect(apiGet).toHaveBeenCalledTimes(1);
  await act(async () => finishes[0]({ stale: true }));
  expect(apiGet).toHaveBeenCalledTimes(2);
  expect(result.current.data).toBeNull();
  expect(result.current.loading).toBe(true);
  await act(async () => finishes[1]({ fresh: true }));
  expect(result.current.data).toEqual({ fresh: true });
  expect(result.current.loading).toBe(false);
});

test("offline invalidates late web success and a changed path owns its loading state", async () => {
  vi.mocked(isAndroid).mockReturnValue(false);
  const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  const finishes: ((value: unknown) => void)[] = [];
  vi.mocked(apiGet).mockImplementation(() => new Promise(resolve => finishes.push(resolve)));
  const { result, rerender } = renderHook(({ path }) => useApiData(path), { initialProps: { path: "/one" } });
  online.mockReturnValue(false);
  act(() => window.dispatchEvent(new Event("offline")));
  await act(async () => finishes[0]({ old: true }));
  expect(result.current.data).toBeNull();
  expect(result.current.error).toContain("オフライン");
  online.mockReturnValue(true);
  rerender({ path: "/two" });
  expect(result.current.loading).toBe(true);
  await act(async () => finishes[1]({ current: true }));
  expect(result.current.data).toEqual({ current: true });
});

test("saved display paints before heavy validation, while a missing preview never stalls it",async()=>{
  vi.mocked(isAndroid).mockReturnValue(true);
  const frames:FrameRequestCallback[]=[];
  vi.spyOn(window,"requestAnimationFrame").mockImplementation(callback=>{frames.push(callback);return frames.length;});
  vi.mocked(StockAI.readSavedView).mockResolvedValue({available:true,readOnly:true,savedAt:"2026-01-01T00:00:00Z",body:{saved:7}});
  const view=renderHook(()=>useApiData("/api/v1/stocks/7203"));
  await act(async()=>{await Promise.resolve();});
  expect(view.result.current.data).toEqual({saved:7});expect(view.result.current.loading).toBe(true);expect(apiGet).not.toHaveBeenCalled();
  act(()=>frames.shift()!(0));expect(apiGet).not.toHaveBeenCalled();
  await act(async()=>frames.shift()!(16));expect(apiGet).toHaveBeenCalledExactlyOnceWith("/api/v1/stocks/7203");
  expect(view.result.current.savedAt).toBeNull();view.unmount();vi.mocked(apiGet).mockClear();
  vi.mocked(StockAI.readSavedView).mockReturnValue(new Promise(()=>{}));
  vi.useFakeTimers({toFake:["setTimeout","clearTimeout"]});
  renderHook(()=>useApiData("/api/v1/validation?mode=paper"));
  expect(apiGet).not.toHaveBeenCalled();await act(async()=>{await vi.advanceTimersByTimeAsync(120);});
  expect(apiGet).toHaveBeenCalledExactlyOnceWith("/api/v1/validation?mode=paper");
});

test("leaving a preview before the deferred read prevents obsolete work from entering Python",async()=>{
  vi.mocked(isAndroid).mockReturnValue(true);
  const frames:FrameRequestCallback[]=[];
  vi.spyOn(window,"requestAnimationFrame").mockImplementation(callback=>{frames.push(callback);return frames.length;});
  const cancel=vi.spyOn(window,"cancelAnimationFrame");
  vi.mocked(StockAI.readSavedView).mockResolvedValue({available:true,readOnly:true,savedAt:"2026-01-01T00:00:00Z",body:{saved:7}});
  const view=renderHook(()=>useApiData("/api/v1/today"));await act(async()=>{await Promise.resolve();});view.unmount();
  act(()=>frames.shift()!(0));await act(async()=>frames.shift()!(16));
  expect(apiGet).not.toHaveBeenCalled();expect(cancel).toHaveBeenCalled();
});


test("input pages disable periodic and focus refresh while explicit reload still works", async () => {
  vi.useFakeTimers();
  try {
    vi.mocked(isAndroid).mockReturnValue(true);
    vi.mocked(apiGet).mockResolvedValue({ ready: true });
    const { result } = renderHook(() => useApiData("/input", { pollMs: 0, refreshOnFocus: false }));
    await act(async () => { await Promise.resolve(); });
    await act(async () => { vi.advanceTimersByTime(180_000); window.dispatchEvent(new Event("focus")); });
    expect(apiGet).toHaveBeenCalledTimes(1);
    await act(async () => result.current.reload());
    expect(apiGet).toHaveBeenCalledTimes(2);
  } finally { vi.useRealTimers(); }
});

test("disabled reads never start, and re-enabling discards an obsolete result", async () => {
  vi.mocked(isAndroid).mockReturnValue(true);
  let finish!: (value: unknown) => void;
  vi.mocked(apiGet).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const view = renderHook(({ enabled }) => useApiData("/hidden", { enabled }), { initialProps: { enabled: false } });
  expect(apiGet).not.toHaveBeenCalled();
  expect(view.result.current.loading).toBe(false);
  view.rerender({ enabled: true });
  expect(apiGet).toHaveBeenCalledTimes(1);
  view.rerender({ enabled: false });
  await act(async () => finish({ obsolete: true }));
  expect(view.result.current.data).toBeNull();
  vi.mocked(apiGet).mockResolvedValueOnce({ current: true });
  view.rerender({ enabled: true });
  expect(view.result.current.data).toBeNull();
  await waitFor(() => expect(view.result.current.data).toEqual({ current: true }));
  expect(apiGet).toHaveBeenCalledTimes(2);
});

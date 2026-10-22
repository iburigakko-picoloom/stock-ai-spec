import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { apiGet } from "./api";
import { isAndroid } from "./mobile/native";
import { useApiData } from "./hooks";

vi.mock("./api", () => ({ apiGet: vi.fn() }));
vi.mock("./mobile/native", () => ({ isAndroid: vi.fn() }));
beforeEach(() => {
  vi.resetAllMocks();
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
  vi.mocked(apiGet).mockResolvedValue({ saved: 1 });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

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

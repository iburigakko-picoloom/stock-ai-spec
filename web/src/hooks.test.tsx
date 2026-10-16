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
  const { result } = renderHook(() => useApiData("/api/v1/today"));
  await waitFor(() => expect(result.current.data).toEqual({ saved: 1 }));
  act(() => window.dispatchEvent(new Event("offline")));
  expect(result.current.data).toBeNull();
  expect(result.current.error).toContain("オフライン");
  act(() => window.dispatchEvent(new Event("focus")));
  expect(apiGet).toHaveBeenCalledTimes(1);
});

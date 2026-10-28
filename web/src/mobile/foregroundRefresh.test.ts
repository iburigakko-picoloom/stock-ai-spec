import { afterEach, expect, test, vi } from "vitest";
import { listenForForegroundRefresh } from "./foregroundRefresh";

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

test("combines foreground events and falls back if a frame is paused", async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  let frame!: FrameRequestCallback;
  vi.spyOn(window, "requestAnimationFrame").mockImplementation(callback => { frame = callback; return 1; });
  const refresh = vi.fn();
  const stop = listenForForegroundRefresh(refresh);
  document.dispatchEvent(new Event("visibilitychange"));
  window.dispatchEvent(new Event("focus"));
  await vi.advanceTimersByTimeAsync(119);
  expect(refresh).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1);
  expect(refresh).toHaveBeenCalledTimes(1);
  frame(0);
  expect(refresh).toHaveBeenCalledTimes(1);
  window.dispatchEvent(new Event("focus"));
  stop();
  frame(0);
  await vi.advanceTimersByTimeAsync(120);
  expect(refresh).toHaveBeenCalledTimes(1);
});

test("does not refresh after the app becomes hidden before dispatch", async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  vi.spyOn(window, "requestAnimationFrame").mockReturnValue(1);
  let visibility: DocumentVisibilityState = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
  const refresh = vi.fn();
  const stop = listenForForegroundRefresh(refresh);
  window.dispatchEvent(new Event("focus"));
  visibility = "hidden";
  await vi.advanceTimersByTimeAsync(120);
  expect(refresh).not.toHaveBeenCalled();
  visibility = "visible";
  document.dispatchEvent(new Event("visibilitychange"));
  await vi.advanceTimersByTimeAsync(120);
  expect(refresh).toHaveBeenCalledTimes(1);
  stop();
});

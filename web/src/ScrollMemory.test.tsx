import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Link, MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { ScrollMemory } from "./ScrollMemory";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("restoration observers disconnect once a delayed page reaches its saved position", () => {
  const resizeInstances: { callback: () => void; disconnect: ReturnType<typeof vi.fn> }[] = [];
  const mutationInstances: { callback: () => void; disconnect: ReturnType<typeof vi.fn> }[] = [];
  class ResizeMock {
    disconnect = vi.fn(); observe = vi.fn();
    constructor(callback: () => void) { resizeInstances.push({ callback, disconnect: this.disconnect }); }
  }
  class MutationMock {
    disconnect = vi.fn(); observe = vi.fn();
    constructor(callback: () => void) { mutationInstances.push({ callback, disconnect: this.disconnect }); }
  }
  const frames: FrameRequestCallback[] = [];
  vi.stubGlobal("ResizeObserver", ResizeMock); vi.stubGlobal("MutationObserver", MutationMock);
  vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) => { frames.push(fn); return frames.length; });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  render(<MemoryRouter><div className="app-shell--adopted"><div className="app-main"><div className="page" />
    <Link to="/other">other</Link><Link to="/">home</Link></div></div><ScrollMemory /></MemoryRouter>);
  const main = document.querySelector<HTMLElement>(".app-main")!;
  let height = 900;
  Object.defineProperty(main, "scrollHeight", { configurable: true, get: () => height });
  Object.defineProperty(main, "clientHeight", { configurable: true, value: 400 });
  main.scrollTo = vi.fn((_x?: number | ScrollToOptions, y?: number) => { main.scrollTop = Math.min(y ?? 0, Math.max(0, height - 400)); });
  act(() => frames.shift()!(0));
  expect(resizeInstances[0].disconnect).toHaveBeenCalled();
  expect(mutationInstances[0].disconnect).toHaveBeenCalled();
  // Navigation must capture the current position even if its scroll event is still queued.
  main.scrollTop = 450;
  fireEvent.click(screen.getByText("other")); act(() => frames.shift()!(0));
  height = 500;
  fireEvent.click(screen.getByText("home")); act(() => frames.shift()!(0));
  const lastResize = resizeInstances.at(-1)!; const lastMutation = mutationInstances.at(-1)!;
  expect(main.scrollTop).toBe(100);
  expect(lastMutation.disconnect).not.toHaveBeenCalled();
  height = 900; act(() => lastMutation.callback());
  expect(main.scrollTop).toBe(450);
  expect(lastMutation.disconnect).toHaveBeenCalled();
  expect(lastResize.disconnect).toHaveBeenCalled();
  fireEvent.click(screen.getByText("other")); act(() => frames.shift()!(0));
  height = 500;
  fireEvent.click(screen.getByText("home")); act(() => frames.shift()!(0));
  const cancelledResize = resizeInstances.at(-1)!; const cancelledMutation = mutationInstances.at(-1)!;
  expect(cancelledMutation.disconnect).not.toHaveBeenCalled();
  fireEvent.wheel(window);
  expect(cancelledMutation.disconnect).toHaveBeenCalled();
  expect(cancelledResize.disconnect).toHaveBeenCalled();
  main.scrollTop = 60; height = 900; act(() => cancelledMutation.callback());
  expect(main.scrollTop).toBe(60);
});

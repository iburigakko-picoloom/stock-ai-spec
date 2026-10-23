import { useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { SettingsPage } from "./SettingsPage";
import { apiGet } from "../api";

vi.mock("../api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("../mobile/native", () => ({ isAndroid: () => true, StockAI: {} }));
vi.mock("../mobile/MobileDevicePanel", () => ({ MobileDevicePanel: function Editor() {
  const [draft, setDraft] = useState("");
  return <input aria-label="draft" value={draft} onChange={e => setDraft(e.target.value)} />;
} }));
afterEach(() => { cleanup(); vi.useRealTimers(); });

test("native settings preserves its mounted draft through timer, focus and visibility refreshes", async () => {
  vi.useFakeTimers();
  render(<MemoryRouter><SettingsPage /></MemoryRouter>);
  const input = screen.getByLabelText("draft");
  fireEvent.change(input, { target: { value: "未保存の口座入力" } });
  await act(async () => {
    vi.advanceTimersByTime(120_000);
    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("online"));
  });
  expect(screen.getByLabelText("draft")).toBe(input);
  expect(input).toHaveValue("未保存の口座入力");
  expect(apiGet).not.toHaveBeenCalled();
});

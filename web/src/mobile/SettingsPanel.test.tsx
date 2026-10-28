import { useEffect, useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { SettingsPanel } from "./MobileDevicePanel";

afterEach(()=>{cleanup();vi.useRealTimers();});

test("unopened settings do no reads and preserve drafts after first opening", () => {
  const read = vi.fn();
  const poll = vi.fn();
  vi.useFakeTimers();
  function Editor() {
    const [draft, setDraft] = useState("");
    useEffect(() => { read(); const timer=setInterval(poll,1000);return ()=>clearInterval(timer); }, []);
    return <input aria-label="draft" value={draft} onChange={e => setDraft(e.target.value)} />;
  }
  const view = render(<SettingsPanel visible={false}><Editor /></SettingsPanel>);
  expect(read).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("draft")).not.toBeInTheDocument();
  view.rerender(<SettingsPanel visible><Editor /></SettingsPanel>);
  const input = screen.getByLabelText("draft");
  fireEvent.change(input, { target: { value: "未保存" } });
  expect(read).toHaveBeenCalledTimes(1);
  view.rerender(<SettingsPanel visible={false}><Editor /></SettingsPanel>);
  expect(input).not.toBeVisible();
  act(()=>vi.advanceTimersByTime(60000));
  expect(poll).not.toHaveBeenCalled();
  expect(read).toHaveBeenCalledTimes(1);
  view.rerender(<SettingsPanel visible><Editor /></SettingsPanel>);
  expect(screen.getByLabelText("draft")).toBe(input);
  expect(input).toHaveValue("未保存");
  expect(read).toHaveBeenCalledTimes(2); // Resume freshness checks without replacing the draft.
});

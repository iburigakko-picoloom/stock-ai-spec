/** Combine notifications for one return to the foreground without delaying work indefinitely. */
export function listenForForegroundRefresh(refresh: () => void): () => void {
  let active = true;
  let scheduled = false;
  let frame = 0;
  let timer = 0;
  const clear = () => {
    scheduled = false;
    window.cancelAnimationFrame(frame); window.clearTimeout(timer);
    frame = 0; timer = 0;
  };
  const dispatch = () => {
    if (!scheduled) return;
    clear();
    if (active && document.visibilityState === "visible") refresh();
  };
  const foreground = () => {
    if (!active || scheduled || document.visibilityState !== "visible") return;
    scheduled = true;
    frame = window.requestAnimationFrame(dispatch);
    timer = window.setTimeout(dispatch, 120);
  };
  window.addEventListener("focus", foreground);
  document.addEventListener("visibilitychange", foreground);
  return () => {
    active = false; clear();
    window.removeEventListener("focus", foreground);
    document.removeEventListener("visibilitychange", foreground);
  };
}

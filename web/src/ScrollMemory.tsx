import { useLayoutEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

/** Session-only viewport state; never persisted together with financial data. */
export function ScrollMemory() {
  const location = useLocation();
  const positions = useRef(new Map<string, number>());
  const route = location.pathname + location.search;
  useLayoutEffect(() => {
    const target = positions.current.get(route) ?? 0;
    let restoring = true;
    const restore = () => {
      if (!restoring) return;
      window.scrollTo(0, target);
      if (document.documentElement.scrollHeight - window.innerHeight >= target) restoring = false;
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(restore);
    observer?.observe(document.body);
    const frame = requestAnimationFrame(restore);
    const remember = () => { if (!restoring) positions.current.set(route, window.scrollY); };
    const stop = () => { restoring = false; };
    window.addEventListener("scroll", remember, { passive: true });
    window.addEventListener("touchstart", stop, { passive: true });
    window.addEventListener("wheel", stop, { passive: true });
    return () => {
      observer?.disconnect(); cancelAnimationFrame(frame);
      window.removeEventListener("scroll", remember);
      window.removeEventListener("touchstart", stop); window.removeEventListener("wheel", stop);
    };
  }, [route]);
  return null;
}

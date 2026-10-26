import { useLayoutEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

/** Session-only viewport state; never persisted together with financial data. */
export function ScrollMemory() {
  const location = useLocation();
  const positions = useRef(new Map<string, number>());
  const route = location.pathname + location.search;
  useLayoutEffect(() => {
    const main=document.querySelector<HTMLElement>(".app-shell--adopted .app-main");
    const scrollTop=()=>main ? main.scrollTop : window.scrollY;
    const move=(top:number)=>main ? main.scrollTo(0,top) : window.scrollTo(0,top);
    const maximum=()=>main ? main.scrollHeight-main.clientHeight : document.documentElement.scrollHeight-window.innerHeight;
    const target = positions.current.get(route) ?? 0;
    let restoring = true;
    const restore = () => {
      if (!restoring) return;
      move(target);
      if (maximum() >= target) restoring = false;
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(restore);
    observer?.observe(document.body);
    if(main)main.querySelectorAll(".page").forEach(page=>observer?.observe(page));
    const mutations=typeof MutationObserver === "undefined" ? null : new MutationObserver(restore);
    if(main)mutations?.observe(main,{childList:true,subtree:true});
    const frame = requestAnimationFrame(restore);
    const remember = () => { if (!restoring) positions.current.set(route, scrollTop()); };
    const stop = () => { restoring = false; };
    window.addEventListener("scroll", remember, { passive: true });
    main?.addEventListener("scroll",remember,{passive:true});
    window.addEventListener("touchstart", stop, { passive: true });
    window.addEventListener("wheel", stop, { passive: true });
    return () => {
      observer?.disconnect(); mutations?.disconnect(); cancelAnimationFrame(frame);
      window.removeEventListener("scroll", remember);
      main?.removeEventListener("scroll",remember);
      window.removeEventListener("touchstart", stop); window.removeEventListener("wheel", stop);
    };
  }, [route]);
  return null;
}

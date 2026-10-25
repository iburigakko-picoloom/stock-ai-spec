import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { apiGet } from "./api";
import { isAndroid, StockAI } from "./mobile/native";
import { ReadViewActivation } from "./readViewActivation";

export function useApiData<T>(path: string): {
  data: T | null; error: string | null; loading: boolean; savedAt: string | null; reload: () => void;
} {
  const activation = useContext(ReadViewActivation);
  const [result, setResult] = useState<{ path: string; activation: string; value: T | null }>({ path, activation, value: null });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const trigger = useRef<() => void>(() => undefined);
  const reload = useCallback(() => trigger.current(), []);
  useEffect(() => {
    let active = true;
    let epoch = 0;
    let occupied = false;
    let pending = false;
    const available = () => isAndroid() || navigator.onLine;
    const drain = (): void => {
      if (!active || occupied || !pending || !available()) return;
      pending = false;
      occupied = true;
      const started = epoch;
      let freshCompleted = false;
      setLoading(true); setError(null);
      setResult(previous => previous.path === path
        ? previous : { path, activation, value: null });
      if (isAndroid() && typeof StockAI.readSavedView === "function"
          && /^(\/api\/v1\/(home|today)|\/api\/v1\/mobile\/ranking\/(5d|20d)|\/api\/v1\/ranking\?rankType=(overall|5d|20d|morning)&limit=50)$/.test(path)) {
        void StockAI.readSavedView({ path }).then(saved => {
          if (active && started === epoch && !freshCompleted && saved.available && saved.readOnly === true
              && saved.savedAt && Number.isFinite(Date.parse(saved.savedAt)) && Date.parse(saved.savedAt) <= Date.now()) {
            setResult({ path, activation, value: saved.body as T });
            setSavedAt(saved.savedAt);
          }
        }).catch(() => { /* A missing/invalid display copy never bypasses the authoritative read. */ });
      }
      void apiGet<T>(path).then(value => {
        freshCompleted = true;
        if (active && started === epoch && available()) { setResult({ path, activation, value }); setSavedAt(null); }
      }).catch((reason: unknown) => {
        freshCompleted = true;
        if (active && started === epoch) {
          setSavedAt(null);
          setResult({ path, activation, value: null });
          setError(reason instanceof Error ? reason.message : "データを取得できませんでした");
        }
      }).finally(() => {
        occupied = false;
        if (!active) return;
        if (pending && available()) drain();
        else setLoading(false);
      });
    };
    const refresh = (): void => { epoch++; pending = true; drain(); };
    const visible = (): void => {
      if (document.visibilityState === "visible" && available()) refresh();
    };
    const offline = (): void => {
      if (isAndroid()) { refresh(); return; }
      epoch++; pending = false;
      setResult({ path, activation, value: null });
      setError("オフラインです。古い提案は表示しません。"); setLoading(false);
    };
    trigger.current = refresh;
    if (available()) refresh(); else offline();
    document.addEventListener("visibilitychange", visible);
    window.addEventListener("focus", visible);
    window.addEventListener("online", visible);
    window.addEventListener("offline", offline);
    // A periodic check must not invalidate an unfinished authoritative read.
    // Cold Android restoration can exceed one minute; superseding it on every
    // tick otherwise discards its result and immediately queues another read.
    // Explicit reload/focus still invalidates work after a possible change.
    const timer = window.setInterval(() => { if (!occupied) visible(); }, 60_000);
    return () => {
      active = false;
      if (trigger.current === refresh) trigger.current = () => undefined;
      document.removeEventListener("visibilitychange", visible);
      window.removeEventListener("focus", visible);
      window.removeEventListener("online", visible);
      window.removeEventListener("offline", offline);
      window.clearInterval(timer);
    };
  }, [path, activation]);
  return { data: result.path === path ? result.value : null, error, savedAt: result.path === path ? savedAt : null,
    loading: loading || result.path !== path || result.activation !== activation, reload };
}

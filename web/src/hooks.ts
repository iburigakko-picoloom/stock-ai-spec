import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { apiGet } from "./api";
import { isAndroid, StockAI } from "./mobile/native";
import { ReadViewActivation } from "./readViewActivation";

export function useApiData<T>(path: string, { pollMs = 60_000, refreshOnFocus = true, enabled = true }: { pollMs?: number; refreshOnFocus?: boolean; enabled?: boolean } = {}): {
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
    if (!enabled) {
      setResult({ path, activation, value: null });
      setError(null); setSavedAt(null); setLoading(true);
      return;
    }
    let active = true;
    let epoch = 0;
    let occupied = false;
    let pending = false;
    let deferred = 0;
    let frame = 0;
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
      const canPreview = isAndroid() && typeof StockAI.readSavedView === "function"
          && /^(\/api\/v1\/(home|today)|\/api\/v1\/mobile\/ranking\/(5d|20d)|\/api\/v1\/ranking\?rankType=(overall|5d|20d|morning)&limit=50|\/api\/v1\/stocks\/[A-Z0-9]{1,10}|\/api\/v1\/validation\?mode=(paper|live|historical))$/.test(path);
      let dispatched = false;
      const fresh = (): void => {
        if (dispatched) return;
        dispatched = true;
        window.clearTimeout(deferred); window.cancelAnimationFrame(frame);
        if (!active) return;
        if (started !== epoch) { occupied = false; drain(); return; }
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
      if (canPreview) {
        // Give a saved view a paint before cold Python restoration/validation.
        // A busy display reader or paused animation frames cannot stall freshness.
        deferred = window.setTimeout(fresh, 120);
        void StockAI.readSavedView({ path }).then(saved => {
          if (active && started === epoch && !freshCompleted && saved.available && saved.readOnly === true
              && saved.savedAt && Number.isFinite(Date.parse(saved.savedAt)) && Date.parse(saved.savedAt) <= Date.now()) {
            setResult({ path, activation, value: saved.body as T });
            setSavedAt(saved.savedAt);
            frame = window.requestAnimationFrame(() => { frame = window.requestAnimationFrame(fresh); });
          } else {
            fresh();
          }
        }).catch(fresh);
      } else fresh();
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
    if (refreshOnFocus) {
      document.addEventListener("visibilitychange", visible);
      window.addEventListener("focus", visible);
    }
    window.addEventListener("online", visible);
    window.addEventListener("offline", offline);
    // A periodic check must not invalidate an unfinished authoritative read.
    // Cold Android restoration can exceed one minute; superseding it on every
    // tick otherwise discards its result and immediately queues another read.
    // Explicit reload/focus still invalidates work after a possible change.
    const timer = pollMs > 0 ? window.setInterval(() => { if (!occupied) visible(); }, pollMs) : null;
    return () => {
      active = false;
      window.clearTimeout(deferred); window.cancelAnimationFrame(frame);
      if (trigger.current === refresh) trigger.current = () => undefined;
      document.removeEventListener("visibilitychange", visible);
      window.removeEventListener("focus", visible);
      window.removeEventListener("online", visible);
      window.removeEventListener("offline", offline);
      if (timer !== null) window.clearInterval(timer);
    };
  }, [path, activation, pollMs, refreshOnFocus, enabled]);
  return { data: enabled && result.path === path ? result.value : null, error: enabled ? error : null, savedAt: enabled && result.path === path ? savedAt : null,
    loading: enabled && (loading || result.path !== path || result.activation !== activation), reload };
}

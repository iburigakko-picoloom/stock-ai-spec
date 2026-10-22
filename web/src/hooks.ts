import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "./api";
import { isAndroid } from "./mobile/native";

export function useApiData<T>(path: string): {
  data: T | null; error: string | null; loading: boolean; reload: () => void;
} {
  const [result, setResult] = useState<{ path: string; value: T | null }>({ path, value: null });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
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
      setLoading(true); setError(null);
      setResult(previous => previous.path === path
        ? previous : { path, value: null });
      void apiGet<T>(path).then(value => {
        if (active && started === epoch && available()) setResult({ path, value });
      }).catch((reason: unknown) => {
        if (active && started === epoch) {
          setResult({ path, value: null });
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
      setResult({ path, value: null });
      setError("オフラインです。古い提案は表示しません。"); setLoading(false);
    };
    trigger.current = refresh;
    if (available()) refresh(); else offline();
    document.addEventListener("visibilitychange", visible);
    window.addEventListener("focus", visible);
    window.addEventListener("online", visible);
    window.addEventListener("offline", offline);
    const timer = window.setInterval(visible, 60_000);
    return () => {
      active = false;
      if (trigger.current === refresh) trigger.current = () => undefined;
      document.removeEventListener("visibilitychange", visible);
      window.removeEventListener("focus", visible);
      window.removeEventListener("online", visible);
      window.removeEventListener("offline", offline);
      window.clearInterval(timer);
    };
  }, [path]);
  return { data: result.path === path ? result.value : null, error,
    loading: loading || result.path !== path, reload };
}

import { type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import type { Action } from "./types";
import { MobileUpdateNotice } from "./mobile/MobileDevicePanel";
import { ScrollMemory } from "./ScrollMemory";

export function yen(value: string | number | null | undefined): string {
  if (value === null || value === undefined || (typeof value === "string" && value.trim() === "")) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${Math.round(number).toLocaleString("ja-JP")}円`;
}

export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(2)}%`;
}

export function dateTime(value: string | null | undefined, showYear = false): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return "—";
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: showYear ? "numeric" : undefined,
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

export function ActionBadge({ action }: { action: Action }): ReactNode {
  return <span className={`action action--${action.toLowerCase()}`}>{action}</span>;
}

export function PageHeader({
  eyebrow,
  title,
  meta,
  actions,
}: {
  eyebrow?: string;
  title: string;
  meta?: string;
  actions?: ReactNode;
}): ReactNode {
  return (
    <header className="page-header app-brand">
      <div className="page-header__line">
        <span className="brand-mark" aria-hidden="true">株AI</span>
        <h1>{title}</h1>
        {actions && <div className="page-header__actions">{actions}</div>}
      </div>
      {(eyebrow || meta) && <div className="page-header__context">{eyebrow && <p className="eyebrow">{eyebrow}</p>}{meta && <span className="page-header__meta">{meta}</span>}</div>}
    </header>
  );
}

export function StatePanel({
  title,
  detail,
  tone = "neutral",
}: {
  title: string;
  detail?: string | null;
  tone?: "neutral" | "error" | "warning";
}): ReactNode {
  return (
    <section className={`state-panel state-panel--${tone}`} role={tone === "error" ? "alert" : "status"}>
      <strong>{title}</strong>
      {detail && <p>{detail}</p>}
    </section>
  );
}

export function RuntimeBanner({ mode }: { mode: string }): ReactNode {
  if (mode === "LIVE") return null;
  const fixture = mode === "DETERMINISTIC_FIXTURE_ONLY";
  return (
    <div className="runtime-banner" role="status">
      <strong>{fixture ? "画面確認用データ（Fixture）" : "運用の準備が必要です"}</strong>
      <span>
        {fixture
          ? "実データ・運用成績ではありません。"
          : "実データ・採用モデルが揃うまで提案は停止します。"}
      </span>
    </div>
  );
}

const nav = [
  ["/", "M3 10 12 3l9 7v10H3Z M9 20v-7h6v7", "ホーム"],
  ["/today", "M5 5h14v16H5Z M8 3v4 M16 3v4 M5 10h14 M9 14h.01 M15 14h.01 M9 18h.01 M15 18h.01", "今日"],
  ["/ranking", "m3 6 5 4 4-7 4 7 5-4-2 14H5Z", "ランキング"],
  ["/validation", "M8 3h8 M10 3v7L4 19q-1 2 2 2h12q3 0 2-2l-6-9V3 M7 16h10", "検証"],
  ["/settings", "m10 3-.5 3-2 1-2.8-1L3 10l2.4 2L3 14l1.7 4 2.8-1 2 1 .5 3h4l.5-3 2-1 2.8 1 1.7-4-2.4-2L21 10l-1.7-4-2.8 1-2-1L14 3Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0", "設定"],
] as const;

export function AppShell(): ReactNode {
  const location = useLocation();
  const from: unknown = location.state?.from;
  const stockParent = location.pathname === "/holdings" || location.pathname.startsWith("/assets") || location.pathname === "/transactions" ? "/" : location.pathname.startsWith("/stocks/") ? from === "/" || from === "/ranking" ? from : from === "/transactions" ? "/" : "/today" : null;
  return (
    <div className="app-shell">
      <ScrollMemory />
      <MobileUpdateNotice />
      <a className="skip-link" href="#main">本文へ移動</a>
      <main id="main" className="app-main">
        <Outlet />
      </main>
      <nav className="bottom-nav" aria-label="メインナビゲーション">
        {nav.map(([to, path, label]) => {
          const content = <>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={path} /></svg>
            <strong>{label}</strong>
          </>;
          return stockParent ? <Link key={to} to={to} className={stockParent === to ? "active" : undefined} aria-current={stockParent === to ? "page" : undefined}>{content}</Link>
            : <NavLink key={to} to={to} end={to === "/"}>{content}</NavLink>;
        })}
      </nav>
    </div>
  );
}

/** A page-location guide, not a claim that earlier records have been saved. */
export function DecisionSteps({ current }: { current: "proposal" | "review" | "execution" }): ReactNode {
  return <ol className="decision-steps" aria-label="判断の流れ">
    {([ ["proposal", "提案を見る"], ["review", "判断を保存"], ["execution", "結果を記録"] ] as const).map(([key, label], index) => (
      <li key={key} aria-current={current === key ? "step" : undefined}>
        <span aria-hidden="true">{index + 1}</span>{label}
      </li>
    ))}
  </ol>;
}

export function Metric({ label, value, tone }: { label: string; value: string; tone?: string }): ReactNode {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={tone ? `text-${tone}` : undefined}>{value}</strong>
    </div>
  );
}

export function TabBar({ label, options, value, onChange, panelId }: {
  label: string;
  options: ReadonlyArray<readonly [string, string]>;
  value: string;
  onChange: (value: string) => void;
  panelId: string;
}): ReactNode {
  return <div className={`segmented${options.length === 3 ? " segmented--3" : ""}`} role="tablist" aria-label={label}>
    {options.map(([key, title], index) => <button key={key} id={`${panelId}-${key}`} type="button" role="tab" aria-selected={value === key} aria-controls={panelId} tabIndex={value === key ? 0 : -1} className={value === key ? "active" : ""} onClick={() => onChange(key)} onKeyDown={(event) => {
      const next = event.key === "ArrowRight" ? (index + 1) % options.length : event.key === "ArrowLeft" ? (index - 1 + options.length) % options.length : event.key === "Home" ? 0 : event.key === "End" ? options.length - 1 : null;
      if (next === null) return;
      event.preventDefault();
      onChange(options[next][0]);
      event.currentTarget.parentElement?.querySelectorAll("button")[next]?.focus();
    }}>{title}</button>)}
  </div>;
}

import { type ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import type { Action } from "./types";
import { MobileUpdateNotice } from "./mobile/MobileDevicePanel";

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

export function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return "—";
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
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
}: {
  eyebrow?: string;
  title: string;
  meta?: string;
}): ReactNode {
  return (
    <header className="page-header">
      {eyebrow && <p className="eyebrow">{eyebrow}</p>}
      <div className="page-header__line">
        <h1>{title}</h1>
        {meta && <span className="page-header__meta">{meta}</span>}
      </div>
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
  ["/today", "M8 3h8v4H8Z M8 5H5v16h14V5h-3 M8 12l2 2 5-5 M8 18h8", "今日"],
  ["/ranking", "M4 20V12h4v8 M10 20V4h4v16 M16 20V8h4v12", "ランキング"],
  ["/validation", "M4 3v17h17 M7 15l4-5 4 3 5-7", "検証"],
  ["/settings", "M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6", "設定"],
] as const;

export function AppShell(): ReactNode {
  return (
    <div className="app-shell">
      <MobileUpdateNotice />
      <a className="skip-link" href="#main">本文へ移動</a>
      <header className="app-brand">
        <span className="brand-mark" aria-hidden="true">株</span>
        <strong>株AI<span>投資判断サポート</span></strong>
        <span className="manual-only">自動発注なし</span>
      </header>
      <main id="main" className="app-main">
        <Outlet />
      </main>
      <nav className="bottom-nav" aria-label="メインナビゲーション">
        {nav.map(([to, path, label]) => (
          <NavLink key={to} to={to} end={to === "/"}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={path} /></svg>
            <strong>{label}</strong>
          </NavLink>
        ))}
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

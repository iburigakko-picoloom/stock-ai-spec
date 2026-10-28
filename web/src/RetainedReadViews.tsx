import { Activity, Suspense, useEffect, useState, type ComponentType, type ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { isAndroid } from "./mobile/native";
import { HomePage } from "./pages/HomePage";
import { TodayPage, RankingPage, ValidationPage, SettingsPage, HoldingsPage, DecisionReviewPage } from "./lazyPages";
import { ReadViewActivation } from "./readViewActivation";

const views = [
  ["/", HomePage], ["/today", TodayPage], ["/ranking", RankingPage], ["/validation", ValidationPage],
  ["/settings", SettingsPage], ["/holdings", HoldingsPage],
  ["/today/review", DecisionReviewPage],
] as const;

function RetainedView({ Page, active, activation }: { Page: ComponentType; active: boolean; activation: string }): ReactNode {
  const [visited, setVisited] = useState(active);
  useEffect(() => { if (active) setVisited(true); }, [active]);
  if (!visited && !active) return null;
  return <Activity mode={active ? "visible" : "hidden"}>
    <Suspense fallback={<LoadingPage />}><ReadViewActivation.Provider value={activation}><Page /></ReadViewActivation.Provider></Suspense>
  </Activity>;
}

function LoadingPage(): ReactNode {
  return <div className="page" role="status">画面を準備しています…</div>;
}

export function RetainedReadViews(): ReactNode {
  const location = useLocation();
  if (!isAndroid()) return <Suspense fallback={<LoadingPage />}><Outlet /></Suspense>;
  const retained = views.some(([path]) => path === location.pathname);
  return <>
    {views.map(([path, Page]) => <RetainedView key={path} Page={Page} active={path === location.pathname} activation={location.key} />)}
    {!retained && <Suspense fallback={<LoadingPage />}><Outlet /></Suspense>}
  </>;
}

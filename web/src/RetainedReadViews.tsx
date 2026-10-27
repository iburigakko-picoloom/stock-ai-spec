import { Activity, useEffect, useState, type ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { isAndroid } from "./mobile/native";
import { HomePage } from "./pages/HomePage";
import { TodayPage } from "./pages/TodayPage";
import { RankingPage } from "./pages/RankingPage";
import { ValidationPage } from "./pages/ValidationPage";
import { ReadViewActivation } from "./readViewActivation";
import { SettingsPage } from "./pages/SettingsPage";
import { HoldingsPage } from "./pages/HoldingsPage";
import { DecisionReviewPage } from "./pages/DecisionReviewPage";

const views = [
  ["/", HomePage], ["/today", TodayPage], ["/ranking", RankingPage], ["/validation", ValidationPage],
  ["/settings", SettingsPage], ["/holdings", HoldingsPage],
  ["/today/review", DecisionReviewPage],
] as const;

function RetainedView({ Page, active, activation }: { Page: () => ReactNode; active: boolean; activation: string }): ReactNode {
  const [visited, setVisited] = useState(active);
  useEffect(() => { if (active) setVisited(true); }, [active]);
  if (!visited && !active) return null;
  return <Activity mode={active ? "visible" : "hidden"}>
    <ReadViewActivation.Provider value={activation}><Page /></ReadViewActivation.Provider>
  </Activity>;
}

export function RetainedReadViews(): ReactNode {
  const location = useLocation();
  if (!isAndroid()) return <Outlet />;
  const retained = views.some(([path]) => path === location.pathname);
  return <>
    {views.map(([path, Page]) => <RetainedView key={path} Page={Page} active={path === location.pathname} activation={location.key} />)}
    {!retained && <Outlet />}
  </>;
}

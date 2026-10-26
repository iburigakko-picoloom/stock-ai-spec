import { Activity, type ReactNode } from "react";
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

export function RetainedReadViews(): ReactNode {
  const location = useLocation();
  if (!isAndroid()) return <Outlet />;
  const retained = views.some(([path]) => path === location.pathname);
  return <>
    {views.map(([path, Page]) => <Activity key={path} mode={path === location.pathname ? "visible" : "hidden"}>
      <ReadViewActivation.Provider value={location.key}>
        <Page />
      </ReadViewActivation.Provider>
    </Activity>)}
    {!retained && <Outlet />}
  </>;
}

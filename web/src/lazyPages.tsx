import { lazy } from "react";

export const DataOperationsPage = lazy(() => import("./pages/DataOperationsPage").then(module => ({ default: module.DataOperationsPage })));
export const DecisionReviewPage = lazy(() => import("./pages/DecisionReviewPage").then(module => ({ default: module.DecisionReviewPage })));
export const DecisionSavedPage = lazy(() => import("./pages/DecisionSavedPage").then(module => ({ default: module.DecisionSavedPage })));
export const ExecutionPage = lazy(() => import("./pages/ExecutionPage").then(module => ({ default: module.ExecutionPage })));
export const HoldingsPage = lazy(() => import("./pages/HoldingsPage").then(module => ({ default: module.HoldingsPage })));
export const ManualChatGPTPage = lazy(() => import("./pages/ManualChatGPTPage").then(module => ({ default: module.ManualChatGPTPage })));
export const RankingPage = lazy(() => import("./pages/RankingPage").then(module => ({ default: module.RankingPage })));
export const SettingsPage = lazy(() => import("./pages/SettingsPage").then(module => ({ default: module.SettingsPage })));
export const StockDetailPage = lazy(() => import("./pages/StockDetailPage").then(module => ({ default: module.StockDetailPage })));
export const TodayPage = lazy(() => import("./pages/TodayPage").then(module => ({ default: module.TodayPage })));
export const ValidationPage = lazy(() => import("./pages/ValidationPage").then(module => ({ default: module.ValidationPage })));
export const AssetManagementPage = lazy(() => import("./pages/AssetManagementPage").then(module => ({ default: module.AssetManagementPage })));
export const HistoryPage = lazy(() => import("./pages/HistoryPage").then(module => ({ default: module.HistoryPage })));
export const ResearchHistoryPage = lazy(() => import("./pages/ResearchHistoryPage").then(module => ({ default: module.ResearchHistoryPage })));

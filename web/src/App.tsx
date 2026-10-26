import { type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components";
import { RetainedReadViews } from "./RetainedReadViews";
import { DataOperationsPage } from "./pages/DataOperationsPage";
import { DecisionReviewPage } from "./pages/DecisionReviewPage";
import { DecisionSavedPage } from "./pages/DecisionSavedPage";
import { ExecutionPage } from "./pages/ExecutionPage";
import { HoldingsPage } from "./pages/HoldingsPage";
import { HomePage } from "./pages/HomePage";
import { ManualChatGPTPage } from "./pages/ManualChatGPTPage";
import { RankingPage } from "./pages/RankingPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StockDetailPage } from "./pages/StockDetailPage";
import { TodayPage } from "./pages/TodayPage";
import { ValidationPage } from "./pages/ValidationPage";
import { AssetManagementPage } from "./pages/AssetManagementPage";
import { HistoryPage } from "./pages/HistoryPage";
import { ResearchHistoryPage } from "./pages/ResearchHistoryPage";

export function App(): ReactNode {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route element={<RetainedReadViews />}>
        <Route index element={<HomePage />} />
        <Route path="holdings" element={<HoldingsPage />} />
        <Route path="assets" element={<AssetManagementPage />} />
        <Route path="assets/history" element={<HistoryPage />} />
        <Route path="assets/:section" element={<AssetManagementPage />} />
        <Route path="transactions" element={<HistoryPage />} />
        <Route path="today" element={<TodayPage />} />
        <Route path="today/details" element={<TodayPage />} />
        <Route path="today/review" element={<DecisionReviewPage />} />
        <Route path="today/decision" element={<DecisionSavedPage />} />
        <Route path="today/executions" element={<ExecutionPage />} />
        <Route path="today/chatgpt" element={<ManualChatGPTPage />} />
        <Route path="today/chatgpt/history" element={<ManualChatGPTPage />} />
        <Route path="ranking" element={<RankingPage />} />
        <Route path="validation" element={<ValidationPage />} />
        <Route path="validation/details" element={<ValidationPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/data" element={<DataOperationsPage />} />
        <Route path="settings/csv" element={<DataOperationsPage />} />
        <Route path="settings/logs" element={<DataOperationsPage />} />
        <Route path="settings/:section" element={<SettingsPage />} />
        <Route path="stocks/:symbol" element={<StockDetailPage />} />
        <Route path="stocks/:symbol/research" element={<ResearchHistoryPage />} />
        <Route path="models/:modelId" element={<ValidationPage />} />
        <Route path="*" element={<Navigate to="/today" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}

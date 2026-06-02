import { Component, type ReactNode, useEffect } from "react";
import { BrowserRouter, Routes, Route, useNavigate } from "react-router-dom";
import { QueryClient } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { Toaster } from "sonner";
import AppShell from "@/components/layout/AppShell";
import ProtectedRoute from "@/components/ProtectedRoute";
import Dashboard from "@/pages/Dashboard";
import ChartPage from "@/pages/ChartPage";
import Screener from "@/pages/Screener";
import WatchlistPage from "@/pages/WatchlistPage";
import Portfolio from "@/pages/Portfolio";
import Alerts from "@/pages/Alerts";
import StrategyLab from "@/pages/StrategyLab";
import News from "@/pages/News";
import Earnings from "@/pages/Earnings";
import Research from "@/pages/Research";
import PaperTrading from "@/pages/PaperTrading";
import LoginPage from "@/pages/LoginPage";
import LearnHome from "@/pages/LearnHome";
import LearnCourse from "@/pages/LearnCourse";
import LearnLesson from "@/pages/LearnLesson";
import OptionsLab from "@/pages/OptionsLab";
import CryptoLab from "@/pages/CryptoLab";
import NotificationsPage from "@/pages/NotificationsPage";
import Discovery from "@/pages/Discovery";
import DeFi from "@/pages/DeFi";
import Security from "@/pages/Security";
import Onboarding from "@/pages/Onboarding";
import JournalPage from "@/pages/JournalPage";
import AnalyticsPage from "@/pages/AnalyticsPage";
import WorkshopPage from "@/pages/WorkshopPage";
import MonitoringPage from "@/pages/MonitoringPage";
import Social from "@/pages/Social";
import UpgradePage from "@/pages/UpgradePage";
import SettingsPage from "@/pages/Settings";
import NetWorthPage from "@/pages/NetWorthPage";
import TaxXRayPage from "@/pages/TaxXRayPage";
import PodsPage from "@/pages/PodsPage";
import RiskParityPage from "@/pages/RiskParityPage";
import RulesPage from "@/pages/RulesPage";
import EstatePage from "@/pages/EstatePage";
import RSUConsolePage from "@/pages/RSUConsolePage";
import SmartTransfersPage from "@/pages/SmartTransfersPage";
import HeatMapPage from "@/pages/HeatMapPage";
import OptionsFlowPage from "@/pages/OptionsFlowPage";
import MacroDashboardPage from "@/pages/MacroDashboardPage";
import SmartMoneyPage from "@/pages/SmartMoneyPage";
import BacktestLabPage from "@/pages/BacktestLabPage";
import ScannersPage from "@/pages/ScannersPage";
import AlertBuilderPage from "@/pages/AlertBuilderPage";
import PitchPage from "@/pages/PitchPage";
import PitchDeckPage from "@/pages/PitchDeckPage";
import DailyChallengePage from "@/pages/DailyChallengePage";
import MorningBriefPage from "@/pages/MorningBriefPage";
import AchievementsPage from "@/pages/AchievementsPage";
import LeaguesPage from "@/pages/LeaguesPage";
import RoboDashboard from "@/pages/RoboDashboard";
import RiskQuizPage from "@/pages/RiskQuizPage";
import GoalsPage from "@/pages/GoalsPage";
import DirectIndexingPage from "@/pages/DirectIndexingPage";
import MissionControlPage from "@/pages/MissionControlPage";
import AutopilotPage from "@/pages/AutopilotPage";
import AutopilotPromisePage from "@/pages/AutopilotPromisePage";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useSignalToast } from "@/hooks/useSignalToast";
import { useAuthStore } from "@/store/authStore";

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center p-8">
          <div className="max-w-lg w-full bg-zinc-950 border border-red-900 rounded-xl p-6">
            <h1 className="text-red-400 font-bold text-lg mb-2">Application Error</h1>
            <pre className="text-zinc-400 text-xs whitespace-pre-wrap break-all bg-black rounded p-3 mb-4 overflow-auto max-h-64">
              {(this.state.error as Error).message}
              {"\n\n"}
              {(this.state.error as Error).stack}
            </pre>
            <button
              onClick={() => {
                ["REACT_QUERY_OFFLINE_CACHE", "BMG_QUERY_CACHE_v2", "BMG_QUERY_CACHE_v3", "BMG_QUERY_CACHE_v4", "BMG_QUERY_CACHE_v5"].forEach(k => {
                  try { localStorage.removeItem(k); } catch {}
                });
                window.location.reload();
              }}
              className="bg-white text-black text-sm font-semibold px-4 py-2 rounded-lg hover:bg-zinc-200"
            >
              Clear cache &amp; reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// Clean up old cache keys from previous versions
["REACT_QUERY_OFFLINE_CACHE", "BMG_QUERY_CACHE_v2", "BMG_QUERY_CACHE_v3", "BMG_QUERY_CACHE_v4"].forEach(k => {
  try { window.localStorage.removeItem(k); } catch {}
});
// Note: v5 is the active key — only cleared on error boundary, not on startup

// Apply saved appearance preferences before first render so there's no flash
try {
  const prefs = JSON.parse(window.localStorage.getItem("bmg_ui_prefs") ?? "{}");
  if (prefs.theme)   document.documentElement.dataset.theme   = prefs.theme;
  if (prefs.density) document.documentElement.dataset.density = prefs.density;
} catch {}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      gcTime: 1000 * 60 * 60 * 24, // keep cache in memory 24h so persister can save it
    },
  },
});

const persister = createSyncStoragePersister({
  storage: window.localStorage,
  key: "BMG_QUERY_CACHE_v5",
  throttleTime: 1000,
});

function AppInner() {
  useWebSocket();
  useSignalToast();
  const navigate = useNavigate();

  // Global 401 handler: when any API call receives a 401, the axios interceptor
  // fires this event. We log the user out and redirect to login.
  useEffect(() => {
    const handle = () => {
      useAuthStore.getState().logout();
      navigate("/login", { replace: true });
    };
    window.addEventListener("auth:expired", handle);
    return () => window.removeEventListener("auth:expired", handle);
  }, [navigate]);

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/chart" element={<ChartPage />} />
        <Route path="/screener" element={<Screener />} />
        <Route path="/strategy" element={<StrategyLab />} />
        <Route path="/watchlist" element={<WatchlistPage />} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/alerts" element={<Alerts />} />
        <Route path="/news" element={<News />} />
        <Route path="/earnings" element={<Earnings />} />
        <Route path="/research" element={<Research />} />
        <Route path="/paper" element={<PaperTrading />} />
        <Route path="/options" element={<OptionsLab />} />
        <Route path="/crypto" element={<CryptoLab />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/discovery" element={<Discovery />} />
        <Route path="/defi" element={<DeFi />} />
        <Route path="/security" element={<Security />} />
        <Route path="/learn" element={<LearnHome />} />
        <Route path="/learn/lesson/:lessonId" element={<LearnLesson />} />
        <Route path="/learn/:trackId" element={<LearnCourse />} />
        <Route path="/journal" element={<JournalPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/workshop" element={<WorkshopPage />} />
        <Route path="/admin/monitoring"  element={<MonitoringPage />} />
        <Route path="/admin/heatmap"     element={<HeatMapPage />} />
        <Route path="/admin/flow"        element={<OptionsFlowPage />} />
        <Route path="/admin/macro"       element={<MacroDashboardPage />} />
        <Route path="/admin/smart-money" element={<SmartMoneyPage />} />
        <Route path="/admin/backtest"    element={<BacktestLabPage />} />
        <Route path="/admin/scanners"    element={<ScannersPage />} />
        <Route path="/social" element={<Social />} />
        <Route path="/upgrade" element={<UpgradePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/net-worth" element={<NetWorthPage />} />
        <Route path="/tax-xray" element={<TaxXRayPage />} />
        <Route path="/pods" element={<PodsPage />} />
        <Route path="/risk-parity" element={<RiskParityPage />} />
        <Route path="/rules" element={<RulesPage />} />
        <Route path="/estate" element={<EstatePage />} />
        <Route path="/rsu-console" element={<RSUConsolePage />} />
        <Route path="/smart-transfers" element={<SmartTransfersPage />} />
        <Route path="/alerts/builder" element={<AlertBuilderPage />} />
        <Route path="/challenge" element={<DailyChallengePage />} />
        <Route path="/morning-brief" element={<MorningBriefPage />} />
        <Route path="/achievements" element={<AchievementsPage />} />
        <Route path="/leagues" element={<LeaguesPage />} />
        <Route path="/robo" element={<RoboDashboard />} />
        <Route path="/robo/quiz" element={<RiskQuizPage />} />
        <Route path="/robo/goals" element={<GoalsPage />} />
        <Route path="/robo/direct-index" element={<DirectIndexingPage />} />
        <Route path="/mission-control" element={<MissionControlPage />} />
        <Route path="/autopilot" element={<AutopilotPage />} />
        <Route path="/autopilot/activity" element={<AutopilotPage />} />
        <Route path="/autopilot/promise" element={<AutopilotPromisePage />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <PersistQueryClientProvider
        client={queryClient}
        persistOptions={{ persister, maxAge: 1000 * 60 * 60 * 24 }}
      >
        <BrowserRouter>
          <ErrorBoundary>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/pitch" element={<PitchPage />} />
              <Route path="/pitch/deck" element={<PitchDeckPage />} />
              <Route path="/onboarding" element={<ProtectedRoute><Onboarding /></ProtectedRoute>} />
              <Route
                path="/*"
                element={
                  <ProtectedRoute>
                    <AppInner />
                  </ProtectedRoute>
                }
              />
            </Routes>
            <Toaster position="bottom-right" theme="dark" richColors />
          </ErrorBoundary>
        </BrowserRouter>
      </PersistQueryClientProvider>
    </ErrorBoundary>
  );
}

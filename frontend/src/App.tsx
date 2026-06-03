import { Component, type ReactNode, useEffect, lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, useNavigate } from "react-router-dom";
import { QueryClient } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { Toaster } from "sonner";
import AppShell from "@/components/layout/AppShell";
import ProtectedRoute from "@/components/ProtectedRoute";
// Critical-path pages — kept as static imports
import Dashboard from "@/pages/Dashboard";
import ChartPage from "@/pages/ChartPage";
import Screener from "@/pages/Screener";
import LoginPage from "@/pages/LoginPage";
// Heavy/non-critical pages — lazy-loaded for code splitting
const WatchlistPage = lazy(() => import("@/pages/WatchlistPage"));
const Portfolio = lazy(() => import("@/pages/Portfolio"));
const Alerts = lazy(() => import("@/pages/Alerts"));
const StrategyLab = lazy(() => import("@/pages/StrategyLab"));
const News = lazy(() => import("@/pages/News"));
const Earnings = lazy(() => import("@/pages/Earnings"));
const Research = lazy(() => import("@/pages/Research"));
const PaperTrading = lazy(() => import("@/pages/PaperTrading"));
const LearnHome = lazy(() => import("@/pages/LearnHome"));
const LearnCourse = lazy(() => import("@/pages/LearnCourse"));
const LearnLesson = lazy(() => import("@/pages/LearnLesson"));
const OptionsLab = lazy(() => import("@/pages/OptionsLab"));
const CryptoLab = lazy(() => import("@/pages/CryptoLab"));
const NotificationsPage = lazy(() => import("@/pages/NotificationsPage"));
const Discovery = lazy(() => import("@/pages/Discovery"));
const DeFi = lazy(() => import("@/pages/DeFi"));
const Security = lazy(() => import("@/pages/Security"));
const Onboarding = lazy(() => import("@/pages/Onboarding"));
const JournalPage = lazy(() => import("@/pages/JournalPage"));
const AnalyticsPage = lazy(() => import("@/pages/AnalyticsPage"));
const WorkshopPage = lazy(() => import("@/pages/WorkshopPage"));
const MonitoringPage = lazy(() => import("@/pages/MonitoringPage"));
const Social = lazy(() => import("@/pages/Social"));
const UpgradePage = lazy(() => import("@/pages/UpgradePage"));
const SettingsPage = lazy(() => import("@/pages/Settings"));
const NetWorthPage = lazy(() => import("@/pages/NetWorthPage"));
const TaxXRayPage = lazy(() => import("@/pages/TaxXRayPage"));
const PodsPage = lazy(() => import("@/pages/PodsPage"));
const RiskParityPage = lazy(() => import("@/pages/RiskParityPage"));
const RulesPage = lazy(() => import("@/pages/RulesPage"));
const EstatePage = lazy(() => import("@/pages/EstatePage"));
const RSUConsolePage = lazy(() => import("@/pages/RSUConsolePage"));
const SmartTransfersPage = lazy(() => import("@/pages/SmartTransfersPage"));
const HeatMapPage = lazy(() => import("@/pages/HeatMapPage"));
const OptionsFlowPage = lazy(() => import("@/pages/OptionsFlowPage"));
const MacroDashboardPage = lazy(() => import("@/pages/MacroDashboardPage"));
const SmartMoneyPage = lazy(() => import("@/pages/SmartMoneyPage"));
const BacktestLabPage = lazy(() => import("@/pages/BacktestLabPage"));
const ScannersPage = lazy(() => import("@/pages/ScannersPage"));
const AlertBuilderPage = lazy(() => import("@/pages/AlertBuilderPage"));
const PitchPage = lazy(() => import("@/pages/PitchPage"));
const PitchDeckPage = lazy(() => import("@/pages/PitchDeckPage"));
const DailyChallengePage = lazy(() => import("@/pages/DailyChallengePage"));
const MorningBriefPage = lazy(() => import("@/pages/MorningBriefPage"));
const AchievementsPage = lazy(() => import("@/pages/AchievementsPage"));
const LeaguesPage = lazy(() => import("@/pages/LeaguesPage"));
const RoboDashboard = lazy(() => import("@/pages/RoboDashboard"));
const RiskQuizPage = lazy(() => import("@/pages/RiskQuizPage"));
const GoalsPage = lazy(() => import("@/pages/GoalsPage"));
const DirectIndexingPage = lazy(() => import("@/pages/DirectIndexingPage"));
const MissionControlPage = lazy(() => import("@/pages/MissionControlPage"));
const AutopilotPage = lazy(() => import("@/pages/AutopilotPage"));
const AutopilotPromisePage = lazy(() => import("@/pages/AutopilotPromisePage"));
const PlaybookPage = lazy(() => import("@/pages/PlaybookPage"));
const PlaybookDecisionsPage = lazy(() => import("@/pages/PlaybookDecisionsPage"));
const InvestorPipelinePage = lazy(() => import("@/pages/InvestorPipelinePage"));
const FounderHubPage = lazy(() => import("@/pages/FounderHubPage"));
const WaitlistAnalyticsPage = lazy(() => import("@/pages/WaitlistAnalyticsPage"));
const ContentCalendarPage = lazy(() => import("@/pages/ContentCalendarPage"));
const BotDetailPage = lazy(() => import("@/pages/BotDetailPage"));
import { useWebSocket } from "@/hooks/useWebSocket";
import { useSignalToast } from "@/hooks/useSignalToast";
import { useAuthStore } from "@/store/authStore";

const PageLoader = () => (
  <div style={{ minHeight: "100vh", background: "#0a0a0a", display: "flex", alignItems: "center", justifyContent: "center" }}>
    <div style={{ width: 32, height: 32, border: "2px solid #84cc16", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
    <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
  </div>
);

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
    <Suspense fallback={<PageLoader />}>
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/chart" element={<ChartPage />} />
        <Route path="/screener" element={<Screener />} />
        <Route path="/strategy" element={<StrategyLab />} />
        <Route path="/strategy/:botName" element={<BotDetailPage />} />
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
        <Route path="/settings/pitch/playbook" element={<PlaybookPage />} />
        <Route path="/settings/pitch/playbook/decisions" element={<PlaybookDecisionsPage />} />
        <Route path="/settings/founder" element={<FounderHubPage />} />
        <Route path="/settings/founder/investors" element={<InvestorPipelinePage />} />
        <Route path="/settings/founder/waitlist" element={<WaitlistAnalyticsPage />} />
        <Route path="/settings/founder/content" element={<ContentCalendarPage />} />
      </Route>
    </Routes>
    </Suspense>
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
            <Suspense fallback={<PageLoader />}>
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
            </Suspense>
            <Toaster position="bottom-right" theme="dark" richColors />
          </ErrorBoundary>
        </BrowserRouter>
      </PersistQueryClientProvider>
    </ErrorBoundary>
  );
}

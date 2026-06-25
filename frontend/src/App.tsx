import { Component, type ReactNode, type ComponentType, useEffect, useState, lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { QueryClient } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { Toaster } from "sonner";
import AppShell from "@/components/layout/AppShell";
import ProtectedRoute from "@/components/ProtectedRoute";
const LOGIN_V2 = import.meta.env.VITE_LOGIN_V2 === "true";
import NotFoundPage from "@/pages/NotFoundPage";
// All pages lazy-loaded for route-level code splitting
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const ChartPage = lazy(() => import("@/pages/ChartPage"));
const Screener = lazy(() => import("@/pages/Screener"));
const LoginPage = lazy(() => import("@/pages/LoginPage"));
// Heavy/non-critical pages — lazy-loaded for code splitting
const WatchlistPage = lazy(() => import("@/pages/WatchlistPage"));
const Portfolio = lazy(() => import("@/pages/Portfolio"));
const Alerts = lazy(() => import("@/pages/Alerts"));
const StrategyLab = lazy(() => import("@/pages/StrategyLab"));
const News = lazy(() => import("@/pages/News"));
const Earnings = lazy(() => import("@/pages/Earnings"));
const Research = lazy(() => import("@/pages/Research"));
// PaperTrading removed — paper tables archived 2026-06-06
const LearnHome = lazy(() => import("@/pages/LearnHome"));
const LearnCourse = lazy(() => import("@/pages/LearnCourse"));
const LearnLesson = lazy(() => import("@/pages/LearnLesson"));
// IMCP Learning Center (Phase A)
const IMCPLearnPage = lazy(() => import("@/pages/learn/LearnPage"));
const IMCPLearnTrackPage = lazy(() => import("@/pages/learn/LearnTrackPage"));
const IMCPLearnModulePage = lazy(() => import("@/pages/learn/LearnModulePage"));
const IMCPLearnLessonPage = lazy(() => import("@/pages/learn/LearnLessonPage"));
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
const SupportPage = lazy(() => import("@/pages/SupportPage"));
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
const BacktestLabPage = lazy(() => import("@/pages/BacktestLabPage"));
const CandidatesPage = lazy(() => import("@/pages/CandidatesPage"));
const ScannersPage = lazy(() => import("@/pages/ScannersPage"));
const SmartMoneyPage = lazy(() => import("@/pages/SmartMoneyPage"));
const AlertBuilderPage = lazy(() => import("@/pages/AlertBuilderPage"));
const PitchPage = lazy(() => import("@/pages/PitchPage"));
const LandingPage = lazy(() => import("@/pages/LandingPage"));
const PricingPage = lazy(() => import("@/pages/PricingPage"));
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
const RiskConsolePage = lazy(() => import("@/pages/RiskConsolePage"));
const AutopilotPage = lazy(() => import("@/pages/AutopilotPage"));
const AutopilotPromisePage = lazy(() => import("@/pages/AutopilotPromisePage"));
const PlaybookPage = lazy(() => import("@/pages/PlaybookPage"));
const PlaybookDecisionsPage = lazy(() => import("@/pages/PlaybookDecisionsPage"));
const InvestorPipelinePage = lazy(() => import("@/pages/InvestorPipelinePage"));
const FounderHubPage = lazy(() => import("@/pages/FounderHubPage"));
const WaitlistAnalyticsPage = lazy(() => import("@/pages/WaitlistAnalyticsPage"));
const ContentCalendarPage = lazy(() => import("@/pages/ContentCalendarPage"));
const ExternalPortfolioPage = lazy(() => import("@/pages/ExternalPortfolioPage"));
const ReferralPage = lazy(() => import("@/pages/ReferralPage"));
const LearnEarnPage = lazy(() => import("@/pages/LearnEarnPage"));
const IPOAccessPage = lazy(() => import("@/pages/IPOAccessPage"));
const CFPBookingPage = lazy(() => import("@/pages/CFPBookingPage"));
const StakingPage = lazy(() => import("@/pages/StakingPage"));
const DCABasketsPage = lazy(() => import("@/pages/DCABasketsPage"));
const BotDetailPage = lazy(() => import("@/pages/BotDetailPage"));
const CandidateDetailPage = lazy(() => import("@/pages/CandidateDetailPage"));
const BacktestResultPage = lazy(() => import("@/pages/BacktestResultPage"));
const WfaResultPage = lazy(() => import("@/pages/WfaResultPage"));
const TradeDetailPage = lazy(() => import("@/pages/TradeDetailPage"));
const AnalystPage = lazy(() => import("@/pages/AnalystPage"));
const PortfolioDetailPage = lazy(() => import("@/pages/PortfolioDetailPage"));
const NetPortfolio = lazy(() => import("@/pages/NetPortfolio"));
const NetWorthPage = lazy(() => import("@/pages/NetWorthPage"));
const StrategyLibraryPage = lazy(() => import("@/pages/StrategyLibraryPage"));
const CustomBotBuilderPage = lazy(() => import("@/pages/CustomBotBuilderPage"));
const StrategyScoutPage = lazy(() => import("@/pages/StrategyScoutPage"));
const ScoutChartPage = lazy(() => import("@/pages/ScoutChartPage"));
const StrategyWorkshopPage = lazy(() => import("@/pages/StrategyWorkshopPage"));
const ForgeBuilderPage = lazy(() => import("@/pages/ForgeBuilderPage"));
const SignalsFeedPage = lazy(() => import("@/pages/SignalsFeedPage"));
const ActivityPage = lazy(() => import("@/pages/ActivityPage"));
const FundPage = lazy(() => import("@/pages/FundPage"));
const ResearchFeedPage = lazy(() => import("@/pages/ResearchFeedPage"));
const PerformancePage = lazy(() => import("@/pages/PerformancePage"));
const StrategyLeaderboardPage = lazy(() => import("@/pages/StrategyLeaderboardPage"));
const MarketsPage = lazy(() => import("@/pages/MarketsPage"));
const LoginV2Page = lazy(() => import("@/pages/LoginV2Page"));
const ForgotPasswordPage = lazy(() => import("@/pages/ForgotPasswordPage"));
const TermsPage = lazy(() => import("@/pages/TermsPage"));
const PrivacyPage = lazy(() => import("@/pages/PrivacyPage"));
const ExamPage = lazy(() => import("@/pages/ExamPage"));
const ExamResultPage = lazy(() => import("@/pages/ExamResultPage"));
const CertificatesPage = lazy(() => import("@/pages/CertificatesPage"));
const VerifyPage = lazy(() => import("@/pages/VerifyPage"));
const AdminBotsPage = lazy(() => import("@/pages/AdminBotsPage"));
const AdminBotDetailPage = lazy(() => import("@/pages/AdminBotDetailPage"));
const BotHealthPage = lazy(() => import("@/pages/BotHealthPage"));
const SentinelDashboardPage = lazy(() => import("@/pages/SentinelDashboardPage"));
const DisciplineReportPage = lazy(() => import("@/pages/DisciplineReportPage"));
const HypothesesPage = lazy(() => import("@/pages/HypothesesPage"));
const BrainGraphPage = lazy(() => import("@/pages/BrainGraphPage"));
const TuningPage = lazy(() => import("@/pages/TuningPage"));
const AdminDiagnosticsPage = lazy(() => import("@/pages/AdminDiagnosticsPage"));
const IntroSequencePage = lazy(() => import("@/pages/IntroSequencePage"));
import { useWebSocket } from "@/hooks/useWebSocket";
import { useSignalToast } from "@/hooks/useSignalToast";
import { useAuthStore, useIsViewer } from "@/store/authStore";
import VoiceAIModal from "@/components/voice/VoiceAIModal";
import VoiceAIButton from "@/components/voice/VoiceAIButton";
import CoPilot from "@/components/CoPilot";
import { useCoPilot } from "@/hooks/useCoPilot";
import { fetchBars } from "@/api/bars";
import { useQueryClient } from "@tanstack/react-query";

const PageLoader = () => (
  <div style={{ minHeight: "100vh", background: "#0a0a0a", padding: "24px" }}>
    <style>{`
      @keyframes shimmer { 0% { background-position: -600px 0; } 100% { background-position: 600px 0; } }
      .sk { background: linear-gradient(90deg,#1c1c1e 25%,#2a2a2e 50%,#1c1c1e 75%); background-size: 600px 100%; animation: shimmer 1.4s infinite linear; border-radius: 8px; }
    `}</style>
    {/* Sidebar skeleton */}
    <div style={{ display: "flex", gap: 24, height: "calc(100vh - 48px)" }}>
      <div style={{ width: 220, flexShrink: 0, background: "#111113", borderRadius: 16, padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="sk" style={{ height: 32, width: "70%", marginBottom: 8 }} />
        {Array.from({ length: 7 }).map((_, i) => (
          <div key={i} className="sk" style={{ height: 32, width: i % 3 === 2 ? "60%" : "85%" }} />
        ))}
      </div>
      {/* Content skeleton */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 16 }}>
        {/* Header bar */}
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <div className="sk" style={{ height: 28, width: 180 }} />
          <div style={{ flex: 1 }} />
          <div className="sk" style={{ height: 28, width: 80 }} />
          <div className="sk" style={{ height: 28, width: 80 }} />
        </div>
        {/* Card row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} style={{ background: "#111113", borderRadius: 16, padding: 16, display: "flex", flexDirection: "column", gap: 8 }}>
              <div className="sk" style={{ height: 12, width: "50%" }} />
              <div className="sk" style={{ height: 28, width: "70%" }} />
              <div className="sk" style={{ height: 10, width: "40%" }} />
            </div>
          ))}
        </div>
        {/* Main content block */}
        <div style={{ background: "#111113", borderRadius: 16, padding: 20, flex: 1, display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="sk" style={{ height: 16, width: 140 }} />
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="sk" style={{ height: 40, width: i % 2 === 0 ? "100%" : "80%" }} />
          ))}
        </div>
      </div>
    </div>
  </div>
);

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error) {
    const msg = error.message ?? "";
    const isChunkError =
      msg.includes("Failed to fetch dynamically imported module") ||
      msg.includes("Importing a module script failed") ||
      msg.includes("Loading chunk") ||
      msg.includes("ChunkLoadError");
    if (isChunkError) {
      // Stale chunk after a new deploy — hard reload fixes it silently
      window.location.reload();
    }
    // All other errors are displayed via the render fallback below
  }
  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center p-8">
          <div className="text-center">
            <h1 className="text-white font-bold text-xl mb-2">Something went wrong</h1>
            <p className="text-zinc-500 text-sm mb-6">{(this.state.error as Error).message}</p>
            <button
              onClick={() => window.location.reload()}
              className="bg-white text-black text-sm font-semibold px-4 py-2 rounded-lg hover:bg-zinc-200"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// ─── Per-route error boundary ─────────────────────────────────────────────────

class RouteErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch() {
    // Non-chunk errors are shown inline; chunk errors are handled by the outer boundary
  }
  render() {
    if (this.state.error) {
      return (
        <div className="flex items-center justify-center p-8 min-h-[40vh]">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 max-w-md w-full text-center">
            <p className="text-white font-semibold mb-1">Something went wrong on this page</p>
            <p className="text-zinc-500 text-sm mb-4">{(this.state.error as Error).message}</p>
            <button
              onClick={() => this.setState({ error: null })}
              className="bg-zinc-800 hover:bg-zinc-700 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
            >
              Reload page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

/** Wraps a page component in a per-route error boundary. */
function Page({ component: C }: { component: ComponentType }) {
  return <RouteErrorBoundary><C /></RouteErrorBoundary>;
}

/** Guards admin-only routes — redirects non-admins to /dashboard. */
function AdminRoute({ children }: { children: ReactNode }) {
  const { user } = useAuthStore();
  const isAdmin = (user as any)?.is_admin === true;
  if (!isAdmin) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}

/** Login-page gate — first-time visitors see the cinematic intro before
 *  the login form renders. After the intro plays, localStorage.bmg_intro_seen
 *  is set so subsequent /login visits show the form immediately. */
function IntroGate({ children }: { children: ReactNode }) {
  let seen = false;
  try { seen = !!window.localStorage.getItem("bmg_intro_seen"); } catch { /* SSR safety */ }
  if (!seen) return <Navigate to="/intro" replace />;
  return <>{children}</>;
}

// Clean up old cache keys from previous versions
["REACT_QUERY_OFFLINE_CACHE", "BMG_QUERY_CACHE_v2", "BMG_QUERY_CACHE_v3", "BMG_QUERY_CACHE_v4", "BMG_QUERY_CACHE_v5", "BMG_QUERY_CACHE_v6", "BMG_QUERY_CACHE_v7"].forEach(k => {
  try { window.localStorage.removeItem(k); } catch {}
});

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
      // Audit bug 8: portfolio_value was showing stale numbers across sessions
      // ($1.42M ghost) because the previous config kept queries in cache for
      // 24h AND didn't refetch on window focus. So a value cached Friday at
      // 3:50 PM would surface again Monday morning. Now: refetch on focus,
      // and only keep cache 5 min so worst-case staleness is bounded.
      refetchOnWindowFocus: true,
      staleTime: 30_000,
      gcTime: 5 * 60_000, // 5 min (was 24h — too long for portfolio data)
    },
  },
});

const persister = createSyncStoragePersister({
  storage: window.localStorage,
  // Cache key bumped to v8 to invalidate any v7 entries on rollout —
  // otherwise users see the old stale entries until the 5-min TTL expires.
  key: "BMG_QUERY_CACHE_v8",
  throttleTime: 1000,
});

async function prefetchWatchlistBars(queryClient: ReturnType<typeof useQueryClient>) {
  try {
    const res = await fetch("/api/bots/watchlist-symbols", {
      headers: { Authorization: `Bearer ${localStorage.getItem("bmg_token") ?? ""}` },
    });
    if (!res.ok) return;
    const { symbols } = await res.json() as { symbols: string[] };
    const BATCH = 5;
    for (let i = 0; i < symbols.length; i += BATCH) {
      const batch = symbols.slice(i, i + BATCH);
      await Promise.all(
        batch.map((sym) =>
          queryClient.prefetchQuery({
            queryKey: ["bars", sym, "1Day", undefined, undefined],
            queryFn: () => fetchBars(sym, "1Day", undefined, undefined, 5000),
            staleTime: 5 * 60_000,
          })
        )
      );
    }
  } catch {}
}

function AppInner() {
  useWebSocket();
  useSignalToast();
  const navigate = useNavigate();
  const isViewer = useIsViewer();
  const [voiceOpen, setVoiceOpen] = useState(false);
  const coPilot = useCoPilot();
  const queryClient = useQueryClient();
  const { user } = useAuthStore();

  // Background prefetch watchlist symbols on login so bot pages load instantly
  useEffect(() => {
    if (user) prefetchWatchlistBars(queryClient);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

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

  // Global Cmd+Shift+V shortcut to toggle Voice AI
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "v") {
        e.preventDefault();
        setVoiceOpen(v => !v);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <ErrorBoundary>
    <Suspense fallback={<PageLoader />}>
    <Routes>
      {/* URL alias redirects — outside layout so they fire before AppShell renders */}
      <Route path="/strategy-lab" element={<Navigate to="/strategy" replace />} />
      <Route path="/strategy/lab" element={<Navigate to="/strategy" replace />} />
      <Route path="/strategy/analytics" element={<Navigate to="/strategy/performance" replace />} />
      <Route element={<AppShell />}>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/chart" element={<ChartPage />} />
        <Route path="/screener" element={<Screener />} />
        <Route path="/strategy" element={<Page component={StrategyLab} />} />
        <Route path="/signals" element={<SignalsFeedPage />} />
        <Route path="/strategy/scout" element={<StrategyScoutPage />} />
        <Route path="/strategy/scout/chart/:ticker/:strategyId" element={<ScoutChartPage />} />
        <Route path="/strategy/workshop" element={<Page component={StrategyWorkshopPage} />} />
        <Route path="/strategy/forge" element={<ForgeBuilderPage />} />
        <Route path="/fund" element={<FundPage />} />
        <Route path="/strategy/performance" element={<PerformancePage />} />
        <Route path="/strategy/leaderboard" element={<StrategyLeaderboardPage />} />
        <Route path="/markets" element={<MarketsPage />} />
        <Route path="/strategy/library" element={<StrategyLibraryPage />} />
        <Route path="/strategy-library" element={<Navigate to="/strategy/library" replace />} />
        <Route path="/strategy/library/custom-bot" element={<Navigate to="/strategy/forge" replace />} />
        <Route path="/strategy/analyst" element={<AnalystPage />} />
        <Route path="/strategy/portfolio/:assetClass" element={<PortfolioDetailPage />} />
        <Route path="/strategy/hypotheses" element={<HypothesesPage />} />
        <Route path="/strategy/brain" element={<AdminRoute><BrainGraphPage /></AdminRoute>} />
        <Route path="/strategy/trade/:tradeId" element={<TradeDetailPage />} />
        <Route path="/strategy/bot/:botName" element={<BotDetailPage />} />
        <Route path="/strategy/:botName" element={<BotDetailPage />} />
        <Route path="/candidates" element={<CandidatesPage />} />
        <Route path="/candidates/:candidateName" element={<CandidateDetailPage />} />
        <Route path="/candidates/:candidateName/backtest/:jobId" element={<BacktestResultPage />} />
        <Route path="/candidates/:candidateName/wfa/:jobId" element={<WfaResultPage />} />
        <Route path="/net-portfolio" element={<NetPortfolio />} />
        <Route path="/watchlist" element={<WatchlistPage />} />
        <Route path="/portfolio" element={<Page component={Portfolio} />} />
        <Route path="/alerts" element={<Alerts />} />
        <Route path="/news" element={<News />} />
        <Route path="/earnings" element={<Earnings />} />
        <Route path="/research" element={<Research />} />
        <Route path="/research-feed" element={<ResearchFeedPage />} />
        <Route path="/paper" element={<Navigate to="/portfolio" replace />} />
        <Route path="/options" element={<OptionsLab />} />
        <Route path="/crypto" element={<CryptoLab />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/discovery" element={<Discovery />} />
        <Route path="/defi" element={<DeFi />} />
        <Route path="/security" element={<Security />} />
        <Route path="/learn" element={<Navigate to="/learn/tracks" replace />} />
        <Route path="/learn/lesson/:lessonId" element={<LearnLesson />} />
        {/* IMCP Learning Center — canonical path */}
        <Route path="/learn/tracks" element={<IMCPLearnPage />} />
        <Route path="/learn/tracks/:trackSlug" element={<IMCPLearnTrackPage />} />
        <Route path="/learn/tracks/:trackSlug/:moduleSlug" element={<IMCPLearnModulePage />} />
        <Route path="/learn/tracks/:trackSlug/:moduleSlug/:lessonSlug" element={<IMCPLearnLessonPage />} />
        <Route path="/learn/:trackId" element={<LearnCourse />} />
        <Route path="/journal" element={<JournalPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/workshop" element={<Page component={WorkshopPage} />} />
        <Route path="/admin"             element={<AdminRoute><AdminBotsPage /></AdminRoute>} />
        <Route path="/admin/bots/:botId" element={<AdminRoute><AdminBotDetailPage /></AdminRoute>} />
        <Route path="/admin/monitoring"  element={<AdminRoute><MonitoringPage /></AdminRoute>} />
        <Route path="/admin/heatmap"     element={<AdminRoute><HeatMapPage /></AdminRoute>} />
        <Route path="/admin/flow"        element={<AdminRoute><OptionsFlowPage /></AdminRoute>} />
        <Route path="/admin/macro"       element={<AdminRoute><MacroDashboardPage /></AdminRoute>} />
        <Route path="/admin/backtest"    element={<AdminRoute><BacktestLabPage /></AdminRoute>} />
        <Route path="/admin/candidates"  element={<AdminRoute><CandidatesPage /></AdminRoute>} />
        <Route path="/admin/scanners"    element={<AdminRoute><ScannersPage /></AdminRoute>} />
        <Route path="/admin/smart-money" element={<AdminRoute><SmartMoneyPage /></AdminRoute>} />
        <Route path="/admin/sentinel"    element={<AdminRoute><SentinelDashboardPage /></AdminRoute>} />
        <Route path="/admin/bot-health"           element={<AdminRoute><BotHealthPage /></AdminRoute>} />
        <Route path="/admin/bot-health/:botId"    element={<AdminRoute><AdminBotDetailPage /></AdminRoute>} />
        <Route path="/admin/discipline-report"    element={<AdminRoute><DisciplineReportPage /></AdminRoute>} />
        <Route path="/admin/tuning"               element={<AdminRoute><TuningPage /></AdminRoute>} />
        <Route path="/admin/diagnostics"          element={<AdminRoute><AdminDiagnosticsPage /></AdminRoute>} />
        <Route path="/social" element={<Social />} />
        <Route path="/upgrade" element={<UpgradePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/support" element={<SupportPage />} />
        <Route path="/tax-xray" element={<TaxXRayPage />} />
        <Route path="/pods" element={<Page component={PodsPage} />} />
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
        <Route path="/mission-control" element={<Page component={MissionControlPage} />} />
        <Route path="/mission" element={<Navigate to="/mission-control" replace />} />
        <Route path="/smart-money" element={<Navigate to="/admin/smart-money" replace />} />
        <Route path="/brain" element={<Navigate to="/strategy/brain" replace />} />
        <Route path="/discipline" element={<Navigate to="/admin/discipline-report" replace />} />
        <Route path="/hypotheses" element={<Navigate to="/strategy/hypotheses" replace />} />
        <Route path="/risk-console" element={<Page component={RiskConsolePage} />} />
        <Route path="/autopilot" element={<Page component={AutopilotPage} />} />
        <Route path="/autopilot/activity" element={<AutopilotPage />} />
        <Route path="/activity" element={<Page component={ActivityPage} />} />
        <Route path="/autopilot/promise" element={<AutopilotPromisePage />} />
        <Route path="/settings/pitch/playbook" element={<PlaybookPage />} />
        <Route path="/settings/pitch/playbook/decisions" element={<PlaybookDecisionsPage />} />
        <Route path="/settings/founder" element={<FounderHubPage />} />
        <Route path="/settings/founder/investors" element={<InvestorPipelinePage />} />
        <Route path="/settings/founder/waitlist" element={<WaitlistAnalyticsPage />} />
        <Route path="/settings/founder/content" element={<ContentCalendarPage />} />
        <Route path="/external-portfolio" element={<ExternalPortfolioPage />} />
        <Route path="/referral" element={<ReferralPage />} />
        <Route path="/learn/earn" element={<LearnEarnPage />} />
        <Route path="/learn/exam" element={<Page component={ExamPage} />} />
        <Route path="/learn/exam/result" element={<Page component={ExamResultPage} />} />
        <Route path="/learn/certificates" element={<Page component={CertificatesPage} />} />
        <Route path="/ipo" element={<IPOAccessPage />} />
        <Route path="/settings/cfp" element={<CFPBookingPage />} />
        <Route path="/staking" element={<StakingPage />} />
        <Route path="/dca-baskets" element={<DCABasketsPage />} />
        {/* Friendly URL aliases */}
        <Route path="/dashboard" element={<Page component={Dashboard} />} />
        <Route path="/net-worth" element={<NetWorthPage />} />
        <Route path="/capital-pods" element={<Navigate to="/pods" replace />} />
        <Route path="/ta-workshop" element={<Navigate to="/workshop" replace />} />
        <Route path="/paper-trading" element={<Navigate to="/portfolio" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
    </Suspense>
    {!isViewer && <VoiceAIButton onClick={() => setVoiceOpen(true)} />}
    <VoiceAIModal open={voiceOpen} onClose={() => setVoiceOpen(false)} />
    <CoPilot
      isOpen={coPilot.isOpen}
      onClose={coPilot.close}
      prefillQuery={coPilot.prefillQuery}
    />
    </ErrorBoundary>
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
              <Route path="/" element={<LandingPage />} />
              {/* Cinematic intro — public, accessible to anonymous visitors.
                  Always plays when navigated to directly. The login route
                  below is gated by IntroGate so first-time visitors see the
                  intro before the login form. */}
              <Route path="/intro" element={<IntroSequencePage />} />
              <Route
                path="/login"
                element={
                  <IntroGate>{LOGIN_V2 ? <LoginV2Page /> : <LoginPage />}</IntroGate>
                }
              />
              <Route path="/signin" element={<Navigate to="/login" replace />} />
              <Route path="/signup" element={<Navigate to="/login" replace />} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
              <Route path="/pricing" element={<PricingPage />} />
              <Route path="/terms" element={<TermsPage />} />
              <Route path="/privacy" element={<PrivacyPage />} />
              <Route path="/pitch" element={<PitchPage />} />
              <Route path="/pitch/deck" element={<PitchDeckPage />} />
              <Route path="/verify/:certId" element={<VerifyPage />} />
              <Route path="/onboarding" element={<ProtectedRoute><Onboarding /></ProtectedRoute>} />
              <Route
                path="/*"
                element={
                  <ProtectedRoute>
                    <AppInner />
                  </ProtectedRoute>
                }
              />
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
            </Suspense>
            <Toaster position="bottom-right" theme="dark" richColors />
          </ErrorBoundary>
        </BrowserRouter>
      </PersistQueryClientProvider>
    </ErrorBoundary>
  );
}

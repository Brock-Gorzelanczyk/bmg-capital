import { Component, type ReactNode } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
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
import NotificationsPage from "@/pages/NotificationsPage";
import Discovery from "@/pages/Discovery";
import Onboarding from "@/pages/Onboarding";
import JournalPage from "@/pages/JournalPage";
import Social from "@/pages/Social";
import UpgradePage from "@/pages/UpgradePage";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useSignalToast } from "@/hooks/useSignalToast";

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
                localStorage.removeItem("REACT_QUERY_OFFLINE_CACHE");
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

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, gcTime: 1000 * 60 * 10 } },
});

// v2 key busts any old corrupted cache from previous deploys
const CACHE_KEY = "BMG_QUERY_CACHE_v2";
try { window.localStorage.removeItem("REACT_QUERY_OFFLINE_CACHE"); } catch {}

let persister: ReturnType<typeof createSyncStoragePersister>;
try {
  persister = createSyncStoragePersister({ storage: window.localStorage, key: CACHE_KEY });
} catch {
  persister = createSyncStoragePersister({ storage: window.sessionStorage, key: CACHE_KEY });
}

function AppInner() {
  useWebSocket();
  useSignalToast();
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
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/discovery" element={<Discovery />} />
        <Route path="/learn" element={<LearnHome />} />
        <Route path="/learn/lesson/:lessonId" element={<LearnLesson />} />
        <Route path="/learn/:trackId" element={<LearnCourse />} />
        <Route path="/journal" element={<JournalPage />} />
        <Route path="/social" element={<Social />} />
        <Route path="/upgrade" element={<UpgradePage />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <PersistQueryClientProvider client={queryClient} persistOptions={{ persister }}>
        <BrowserRouter>
          <ErrorBoundary>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
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

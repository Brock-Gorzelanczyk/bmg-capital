import { useEffect, useState, Suspense } from "react";
import { Outlet, useLocation, NavLink, Link } from "react-router-dom";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import { useIsAdmin, useIsViewer } from "@/store/authStore";
import { House, BarChart2, Bot, Newspaper, User } from "lucide-react";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import CommandPalette from "@/components/ui/CommandPalette";
import CopilotModal from "@/components/ui/CopilotModal";
import ExplainPanel from "@/components/explain/ExplainPanel";
import NotificationPanel from "@/components/notifications/NotificationPanel";
import SupportChatWidget from "@/components/support/SupportChatWidget";
import WelcomeModal from "@/components/onboarding/WelcomeModal";
import { getTrades, getCandidates, getSummary, getLog, getEquity, getRegime } from "@/api/strategy";
import { getMyTier } from "@/api/tiers";
import { getTodayChallenge } from "@/api/engagement";
import { getStatus as getAutonomousStatus, getLatestDigest } from "@/api/autonomous";
import { useTierStore } from "@/store/tierStore";
import { cn } from "@/lib/utils";

function ContentSkeleton() {
  return (
    <div className="p-4 md:p-6 space-y-4 animate-pulse">
      <div className="h-8 w-64 bg-zinc-800 rounded-lg" />
      <div className="h-4 w-96 bg-zinc-800/60 rounded" />
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6">
        {[0, 1, 2].map(i => <div key={i} className="h-32 bg-zinc-800 rounded-xl" />)}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {[0, 1, 2, 3].map(i => <div key={i} className="h-24 bg-zinc-800 rounded-xl" />)}
      </div>
    </div>
  );
}

const BOTTOM_NAV = [
  { to: "/",              label: "Home",       Icon: House },
  { to: "/strategy",      label: "Strategies", Icon: Bot },
  { to: "/chart",         label: "Markets",    Icon: BarChart2 },
  { to: "/morning-brief", label: "Brief",      Icon: Newspaper },
  { to: "/settings",      label: "Account",    Icon: User },
];

export default function AppShell() {
  const { pathname } = useLocation();
  const isAdmin = useIsAdmin();
  const isViewer = useIsViewer();
  const isChart = pathname === "/chart";
  const qc = useQueryClient();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showWelcome, setShowWelcome] = useState(
    () => !!localStorage.getItem("bmg_token") && !localStorage.getItem("bmg_onboarded")
  );

  const { data: challengeData } = useQuery({
    queryKey: ["engagement-challenge-today"],
    queryFn: getTodayChallenge,
    staleTime: 60_000,
  });

  const { data: autoStatus } = useQuery({
    queryKey: ["autonomous-status"],
    queryFn: getAutonomousStatus,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const { data: latestDigest } = useQuery({
    queryKey: ["autonomous-digest-latest"],
    queryFn: getLatestDigest,
    staleTime: 5 * 60 * 1000,
  });

  const todayStr = new Date().toISOString().slice(0, 10);
  const digestIsToday = latestDigest?.digest_date?.slice(0, 10) === todayStr;

  useEffect(() => {
    qc.prefetchQuery({ queryKey: ["strategy-trades"],     queryFn: getTrades,        staleTime: 55_000 });
    qc.prefetchQuery({ queryKey: ["strategy-candidates"], queryFn: getCandidates,    staleTime: 55_000 });
    qc.prefetchQuery({ queryKey: ["strategy-summary"],    queryFn: getSummary,       staleTime: 55_000 });
    qc.prefetchQuery({ queryKey: ["strategy-log"],        queryFn: () => getLog(80), staleTime: 55_000 });
    qc.prefetchQuery({ queryKey: ["strategy-equity"],     queryFn: getEquity,        staleTime: 290_000 });
    qc.prefetchQuery({ queryKey: ["strategy-regime"],     queryFn: getRegime,        staleTime: 290_000 });
    qc.fetchQuery({ queryKey: ["tier-me"], queryFn: getMyTier, staleTime: 300_000 })
      .then((d) => { if (d) useTierStore.getState().setTierData(d); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        const tag = (e.target as HTMLElement).tagName;
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        e.preventDefault();
        setCopilotOpen((o) => !o);
      }
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "k") {
        const tag = (e.target as HTMLElement).tagName;
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Close sidebar when route changes (mobile nav)
  useEffect(() => {
    setSidebarOpen(false);
  }, [pathname]);

  return (
    <div className="flex h-screen bg-gray-950 overflow-hidden">
      {/* Mobile backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar — always visible on md+, slide-in on mobile */}
      <div
        className={cn(
          "fixed inset-y-0 left-0 z-50 md:relative md:z-auto md:translate-x-0 transition-transform duration-300 ease-in-out",
          sidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        )}
      >
        <Sidebar
          onOpenPalette={() => { setCopilotOpen(true); setSidebarOpen(false); }}
          onClose={() => setSidebarOpen(false)}
          expanded={sidebarOpen}
        />
      </div>

      {/* Main content */}
      <div className="flex flex-col flex-1 overflow-hidden min-w-0">
        {/* Viewer banner — shown only to non-admin accounts */}
        {isViewer && (
          <div className="flex items-center gap-2 bg-blue-500/10 border-b border-blue-500/20 px-4 py-2 text-xs text-blue-300 shrink-0">
            <span>👀</span>
            <span>
              You're viewing BMG Capital in demo mode. Browse anything — you can't make changes. Like what you see? Ask the admin for full access.
            </span>
          </div>
        )}
        {!isChart && <TopBar onMenuToggle={() => setSidebarOpen((o) => !o)} />}
        <main
          className={
            isChart
              ? "flex-1 flex flex-col overflow-hidden"
              : "flex-1 overflow-auto p-3 md:p-4 pb-16 md:pb-4"
          }
        >
          <Suspense fallback={<ContentSkeleton />}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      {/* Bottom navigation — mobile only */}
      <div
        className="fixed bottom-0 left-0 right-0 md:hidden bg-[var(--bg-base)]/95 backdrop-blur-md border-t border-[var(--border-subtle)] flex z-30"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        {BOTTOM_NAV.map(({ to, label, Icon }) => {
          const showChallengeDot = false;

          const showAutonomousDot = false;

          const showDigestDot =
            to === "/" &&
            digestIsToday &&
            latestDigest != null;

          return (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex-1 flex flex-col items-center gap-1 py-3 text-[10px] transition-colors relative min-h-[52px] justify-center",
                  isActive ? "text-[#3B82F6]" : "text-[var(--text-tertiary)]"
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span className="absolute top-0 left-1/2 -translate-x-1/2 w-8 h-0.5 bg-[#3B82F6] rounded-full" />
                  )}
                  <span className="relative">
                    <Icon size={20} />
                    {showChallengeDot && (
                      <span className="absolute top-1.5 right-3 w-2 h-2 rounded-full bg-[#3B82F6]" />
                    )}
                    {showAutonomousDot && (
                      <span className="absolute top-1.5 right-3 w-2 h-2 rounded-full bg-[#84cc16] animate-pulse" />
                    )}
                    {showDigestDot && (
                      <span className="absolute top-1.5 right-3 w-2 h-2 rounded-full bg-[#84cc16]" />
                    )}
                  </span>
                  <span className="font-medium">{label}</span>
                </>
              )}
            </NavLink>
          );
        })}
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <CopilotModal open={copilotOpen} onClose={() => setCopilotOpen(false)} />
      <ExplainPanel />
      <NotificationPanel />
      <div className="md:hidden"><SupportChatWidget /></div>

      {/* Welcome / onboarding modal — shown to first-time authenticated users */}
      {showWelcome && pathname !== "/onboarding" && (
        <WelcomeModal onClose={() => setShowWelcome(false)} />
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import { Outlet, useLocation, NavLink } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { House, LineChart, PlayCircle, BookOpen, GraduationCap } from "lucide-react";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import CommandPalette from "@/components/ui/CommandPalette";
import ExplainPanel from "@/components/explain/ExplainPanel";
import NotificationPanel from "@/components/notifications/NotificationPanel";
import SupportChatWidget from "@/components/support/SupportChatWidget";
import { getTrades, getCandidates, getSummary, getLog, getEquity, getRegime } from "@/api/strategy";
import { getMyTier } from "@/api/tiers";
import { useTierStore } from "@/store/tierStore";
import { cn } from "@/lib/utils";

const BOTTOM_NAV = [
  { to: "/", label: "Home", Icon: House },
  { to: "/chart", label: "Chart", Icon: LineChart },
  { to: "/paper", label: "Paper", Icon: PlayCircle },
  { to: "/portfolio", label: "Portfolio", Icon: BookOpen },
  { to: "/learn", label: "Learn", Icon: GraduationCap },
];

export default function AppShell() {
  const { pathname } = useLocation();
  const isChart = pathname === "/chart";
  const qc = useQueryClient();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

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
          onOpenPalette={() => { setPaletteOpen(true); setSidebarOpen(false); }}
          onClose={() => setSidebarOpen(false)}
        />
      </div>

      {/* Main content */}
      <div className="flex flex-col flex-1 overflow-hidden min-w-0">
        {!isChart && <TopBar onMenuToggle={() => setSidebarOpen((o) => !o)} />}
        <main
          className={
            isChart
              ? "flex-1 flex flex-col overflow-hidden"
              : "flex-1 overflow-auto p-3 md:p-4 pb-16 md:pb-4"
          }
        >
          <Outlet />
        </main>
      </div>

      {/* Bottom navigation — mobile only */}
      <div className="fixed bottom-0 left-0 right-0 md:hidden bg-[#0F172A] border-t border-[#1E293B] flex z-30 safe-area-pb">
        {BOTTOM_NAV.map(({ to, label, Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex-1 flex flex-col items-center gap-1 py-2 text-[10px] transition-colors",
                isActive ? "text-[#3B82F6]" : "text-[#475569]"
              )
            }
          >
            <Icon size={20} />
            <span>{label}</span>
          </NavLink>
        ))}
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <ExplainPanel />
      <NotificationPanel />
      <SupportChatWidget />
    </div>
  );
}

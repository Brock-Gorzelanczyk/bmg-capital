import { useMemo, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, Wifi, WifiOff, Moon, Zap, LayoutGrid, Menu } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useWsStore, useAlertStore, useUiStore, useNotificationStore } from "@/store";
import { getNotifications } from "@/api/notifications";
import SymbolSearch from "@/components/ui/SymbolSearch";
import { DEMO_MODE } from "@/lib/demoMode";

function useMarketStatus() {
  return useMemo(() => {
    const now = new Date();
    const et = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
    const day = et.getDay();
    const mins = et.getHours() * 60 + et.getMinutes();
    const isWeekday = day >= 1 && day <= 5;
    return isWeekday && mins >= 570 && mins < 960 ? "open" : "closed";
  }, []);
}

interface TopBarProps {
  onMenuToggle?: () => void;
}

export default function TopBar({ onMenuToggle }: TopBarProps) {
  const navigate = useNavigate();
  const wsStatus = useWsStore((s) => s.status);
  const marketStatus = useMarketStatus();
  const mode = useUiStore((s) => s.mode);
  const toggleMode = useUiStore((s) => s.toggleMode);
  const { unreadCount, openPanel, setNotifications } = useNotificationStore();

  // Seed store on mount
  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: getNotifications,
    staleTime: 60_000,
  });
  useEffect(() => { if (data) setNotifications(data); }, [data, setNotifications]);

  return (
    <header className="h-12 backdrop-blur-md bg-[#020617]/90 border-b border-[#1E293B] flex items-center px-3 md:px-4 gap-2 md:gap-4 shrink-0">
      {/* Hamburger — mobile only */}
      <button
        onClick={onMenuToggle}
        className="md:hidden p-2 text-[#475569] hover:text-[#F8FAFC] transition-colors"
        aria-label="Open menu"
      >
        <Menu size={20} />
      </button>

      <SymbolSearch
        onSelect={(s) => navigate(`/chart?symbol=${s}`)}
        placeholder="Search ticker… AAPL"
        className="flex-1 max-w-xs"
        inputClassName="w-full h-8 bg-[#0F172A] text-[#F8FAFC] text-sm px-3 rounded-l border border-[#334155] focus:outline-none focus:border-[#3B82F6] placeholder-[#475569] uppercase transition-colors duration-150"
      />

      <div className="flex items-center gap-2 md:gap-3 ml-auto">
        {/* Demo mode pill */}
        {DEMO_MODE && (
          <div className="hidden sm:flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-[#22C55E]/30 bg-[#22C55E]/8 text-[#22C55E] font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-[#22C55E] animate-pulse" />
            Demo
          </div>
        )}
        {/* Market status pill */}
        <div className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-[#1E293B] bg-[#0F172A]">
          {wsStatus === "connected" && marketStatus === "open" ? (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-[#22C55E] animate-pulse" />
              <Wifi size={12} className="text-[#22C55E]" />
              <span className="text-[#22C55E] hidden sm:block font-medium">Live</span>
            </>
          ) : wsStatus === "connected" ? (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-[#F59E0B]" />
              <Moon size={12} className="text-[#F59E0B]" />
              <span className="text-[#F59E0B] hidden sm:block font-medium">Closed</span>
            </>
          ) : (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-[#EF4444]" />
              <WifiOff size={12} className="text-[#EF4444]" />
              <span className="text-[#EF4444] hidden sm:block font-medium">Offline</span>
            </>
          )}
        </div>

        {/* Simple / Pro mode toggle */}
        <button
          onClick={toggleMode}
          title={mode === "simple" ? "Switch to Pro Mode" : "Switch to Simple Mode"}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-colors duration-150 border cursor-pointer ${
            mode === "pro"
              ? "bg-[rgba(59,130,246,0.12)] border-[#3B82F6]/30 text-[#F8FAFC]"
              : "bg-transparent border-[#1E293B] text-[#475569] hover:text-[#94A3B8] hover:border-[#334155]"
          }`}
        >
          {mode === "pro" ? <Zap size={12} className="text-[#F59E0B]" /> : <LayoutGrid size={12} />}
          <span className="hidden sm:block">{mode === "pro" ? "Pro" : "Simple"}</span>
        </button>

        <button onClick={openPanel} className="relative text-[#94A3B8] hover:text-[#F8FAFC] transition-colors duration-150 cursor-pointer p-1">
          <Bell size={18} />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 bg-[#EF4444] text-white text-[9px] font-bold rounded-full w-4 h-4 flex items-center justify-center">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </button>
      </div>
    </header>
  );
}

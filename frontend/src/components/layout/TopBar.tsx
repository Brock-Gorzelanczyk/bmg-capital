import React, { useMemo, useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Bell, Wifi, WifiOff, Moon, Zap, LayoutGrid, Menu, Clock, TrendingUp, TrendingDown, BarChart2, AlertTriangle } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useWsStore, useAlertStore, useUiStore, useNotificationStore, useMarketStore } from "@/store";
import { getNotifications } from "@/api/notifications";
import { getRegime } from "@/api/strategy";
import SymbolSearch from "@/components/ui/SymbolSearch";
import { DEMO_MODE } from "@/lib/demoMode";

type MarketState = "open" | "after-hours" | "closed";

// Routes where the market is always 24/7 live (crypto, DeFi)
const ALWAYS_LIVE_PREFIXES = ["/crypto", "/defi", "/security"];

function useEquityMarketStatus(): MarketState {
  return useMemo(() => {
    const now = new Date();
    const et = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
    const day = et.getDay();
    const mins = et.getHours() * 60 + et.getMinutes();
    const isWeekday = day >= 1 && day <= 5;
    if (!isWeekday) return "closed";
    if (mins >= 570 && mins < 960) return "open";
    if ((mins >= 240 && mins < 570) || (mins >= 960 && mins < 1200)) return "after-hours";
    return "closed";
  }, []);
}

interface TopBarProps {
  onMenuToggle?: () => void;
}

export default function TopBar({ onMenuToggle }: TopBarProps) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const wsStatus = useWsStore((s) => s.status);
  const equityStatus = useEquityMarketStatus();
  const isCryptoRoute = ALWAYS_LIVE_PREFIXES.some((p) => pathname.startsWith(p));
  const marketStatus: MarketState = isCryptoRoute ? "open" : equityStatus;
  const mode = useUiStore((s) => s.mode);
  const toggleMode = useUiStore((s) => s.toggleMode);
  const { unreadCount, openPanel, setNotifications } = useNotificationStore();
  const lastQuoteTime = useMarketStore((s) => s.lastQuoteTime);
  const [now, setNow] = useState(Date.now());

  // Keep `now` fresh so the stale check updates automatically
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(id);
  }, []);

  const isStale = lastQuoteTime > 0 && now - lastQuoteTime > 10000;

  // Seed store on mount
  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => getNotifications(),
    staleTime: 60_000,
  });
  useEffect(() => { if (data) setNotifications(data); }, [data, setNotifications]);

  const { data: regimeData } = useQuery({
    queryKey: ["strategy-regime"],
    queryFn: getRegime,
    staleTime: 300_000,
  });
  const regime: string = regimeData?.regime ?? "unknown";

  const REGIME_MAP: Record<string, { label: string; abbr: string; cls: string; icon: React.ReactNode }> = {
    "Trend-Up":   { label: "Trend-Up",   abbr: "TU", cls: "text-emerald-400 border-emerald-400/30 bg-emerald-400/8",  icon: <TrendingUp size={11} /> },
    "Trend-Down": { label: "Trend-Down", abbr: "TD", cls: "text-red-400 border-red-400/30 bg-red-400/8",              icon: <TrendingDown size={11} /> },
    "Range":      { label: "Range",      abbr: "R",  cls: "text-blue-400 border-blue-400/30 bg-blue-400/8",           icon: <BarChart2 size={11} /> },
    "Crisis":     { label: "Crisis",     abbr: "Cr", cls: "text-orange-400 border-orange-400/30 bg-orange-400/8",     icon: <AlertTriangle size={11} /> },
    bull:         { label: "Trend-Up",   abbr: "TU", cls: "text-emerald-400 border-emerald-400/30 bg-emerald-400/8",  icon: <TrendingUp size={11} /> },
    risk_off:     { label: "Trend-Down", abbr: "TD", cls: "text-red-400 border-red-400/30 bg-red-400/8",              icon: <TrendingDown size={11} /> },
    unknown:      { label: "Regime…",    abbr: "—",  cls: "text-zinc-400 border-zinc-400/20 bg-zinc-400/5",           icon: <BarChart2 size={11} /> },
  };
  const regimeChip = REGIME_MAP[regime] ?? REGIME_MAP.unknown;

  return (
    <header className="h-14 backdrop-blur-md bg-[var(--bg-base)]/95 border-b border-[var(--border-subtle)] flex items-center px-3 md:px-4 gap-2 md:gap-4 shrink-0">
      {/* Hamburger — mobile only */}
      <button
        onClick={onMenuToggle}
        className="md:hidden p-2 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
        aria-label="Open menu"
      >
        <Menu size={20} />
      </button>

      <SymbolSearch
        onSelect={(s) => navigate(`/chart?symbol=${s}`)}
        placeholder="Search ticker… AAPL"
        className="flex-1 max-w-xs"
        inputClassName="w-full h-9 bg-[var(--bg-elevated)] text-[var(--text-primary)] text-sm px-3 rounded-l border border-[var(--border-subtle)] focus:outline-none focus:border-[#3B82F6] focus:bg-[var(--bg-elevated)] placeholder-[#475569] uppercase transition-colors duration-150"
      />

      <div className="flex items-center gap-2 md:gap-3 ml-auto">
        {/* Demo mode pill */}
        {DEMO_MODE && (
          <div className="hidden sm:flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-[#22C55E]/30 bg-[#22C55E]/8 text-[var(--accent-positive)] font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-[#22C55E] animate-pulse" />
            Demo
          </div>
        )}
        {/* Regime chip */}
        <div className={`hidden sm:flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border font-medium ${regimeChip.cls}`}>
          {regimeChip.icon}
          <span className="sm:hidden">{regimeChip.abbr}</span>
          <span className="hidden sm:inline">{regimeChip.label}</span>
        </div>
        {/* Stale data indicator */}
        {isStale && (
          <span className="text-[9px] text-[#F59E0B] px-1.5 py-0.5 rounded-full bg-[#F59E0B]/10 border border-[#F59E0B]/20">Data delayed</span>
        )}
        {/* Market status pill */}
        <div className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-[var(--border-subtle)] bg-[var(--bg-elevated)]">
          {wsStatus !== "connected" ? (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-[#F59E0B]" />
              <WifiOff size={12} className="text-[#F59E0B]" />
              <span className="text-[#F59E0B] hidden sm:block font-medium">Offline</span>
            </>
          ) : marketStatus === "open" ? (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-[#22C55E] animate-pulse" />
              <Wifi size={12} className="text-[var(--accent-positive)]" />
              <span className="text-[var(--accent-positive)] hidden sm:block font-medium">Live</span>
            </>
          ) : marketStatus === "after-hours" ? (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-[#F59E0B]" />
              <Clock size={12} className="text-[#F59E0B]" />
              <span className="text-[#F59E0B] hidden sm:block font-medium">After Hours</span>
            </>
          ) : (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-[#F59E0B]" />
              <Moon size={12} className="text-[#F59E0B]" />
              <span className="text-[#F59E0B] hidden sm:block font-medium">Closed</span>
            </>
          )}
        </div>

        {/* Simple / Pro mode toggle */}
        <button
          onClick={toggleMode}
          title={mode === "simple" ? "Switch to Pro Mode" : "Switch to Simple Mode"}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-colors duration-150 border cursor-pointer ${
            mode === "pro"
              ? "bg-[rgba(59,130,246,0.12)] border-[#3B82F6]/30 text-[var(--text-primary)]"
              : "bg-transparent border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:border-[var(--border-emphasis)]"
          }`}
        >
          {mode === "pro" ? <Zap size={12} className="text-[#F59E0B]" /> : <LayoutGrid size={12} />}
          <span className="hidden sm:block">{mode === "pro" ? "Pro" : "Simple"}</span>
        </button>

        <button onClick={openPanel} className="relative text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors duration-150 cursor-pointer p-1">
          <Bell size={18} />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 bg-[#EF4444] text-[var(--text-primary)] text-[9px] font-bold rounded-full w-4 h-4 flex items-center justify-center">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </button>
      </div>
    </header>
  );
}

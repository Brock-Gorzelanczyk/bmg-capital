import React, { useMemo, useEffect, useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { Bell, Wifi, WifiOff, Moon, Zap, LayoutGrid, Menu, Clock, TrendingUp, TrendingDown, BarChart2, AlertTriangle } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useWsStore, useAlertStore, useUiStore, useNotificationStore, useMarketStore } from "@/store";
import { useIsAdmin } from "@/store/authStore";
import { getNotifications } from "@/api/notifications";
import { getRegime } from "@/api/strategy";
import { getMyTier } from "@/api/tiers";
import { pauseAllBots } from "@/api/bots";
import SymbolSearch from "@/components/ui/SymbolSearch";
import { DEMO_MODE } from "@/lib/demoMode";
import DemoPill from "@/components/demo/DemoPill";

type MarketState = "open" | "after-hours" | "closed";

// Routes where the market is always 24/7 live (crypto, DeFi, bot strategy pages)
const ALWAYS_LIVE_PREFIXES = ["/crypto", "/defi", "/security", "/strategy/portfolio/crypto", "/strategy"];

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
  const qc = useQueryClient();
  const pauseMut = useMutation({
    mutationFn: pauseAllBots,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bots-v2"] });
      qc.invalidateQueries({ queryKey: ["strategy-lab-portfolio"] });
    },
  });
  const isAdmin = useIsAdmin();
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

  const { data: tierData } = useQuery({
    queryKey: ["tier-me"],
    queryFn: getMyTier,
    staleTime: 300_000,
    retry: 0,
  });
  const trialDaysLeft = tierData?.trial_ends_at
    ? Math.max(0, Math.ceil((new Date(tierData.trial_ends_at).getTime() - Date.now()) / 86_400_000))
    : 0;
  const showTrialBadge = tierData?.status === "trialing" && trialDaysLeft > 0;

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
        placeholder="Search ticker (e.g. AAPL)"
        className="flex-1 max-w-xs"
        inputClassName="w-full h-9 bg-[var(--bg-2)] text-[var(--text-hi)] text-sm px-3 border border-[var(--border-dim)] focus:outline-none focus:border-[var(--green)] placeholder-[var(--text-dim)] transition-colors duration-150 font-mono"
      />

      <div className="flex items-center gap-2 md:gap-3 ml-auto">
        {/* Pause All Bots — admin only */}
        {isAdmin && (
          <button
            onClick={() => pauseMut.mutate()}
            disabled={pauseMut.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 transition-colors"
          >
            {pauseMut.isPending ? "Pausing..." : "⏸ Pause All"}
          </button>
        )}
        {/* Demo mode pill */}
        {DEMO_MODE && <DemoPill />}
        {/* Regime chip */}
        <div className={`hidden sm:flex items-center gap-1.5 text-xs px-2.5 py-1 border font-bold ${regimeChip.cls}`} style={{ fontFamily: 'var(--font-mono-t)', letterSpacing: '0.08em' }}>
          {regimeChip.icon}
          <span className="sm:hidden">{regimeChip.abbr}</span>
          <span className="hidden sm:inline">{regimeChip.label}</span>
        </div>
        {/* Trial countdown badge */}
        {showTrialBadge && (
          <Link
            to="/pricing"
            className="hidden sm:flex items-center gap-1.5 text-xs font-bold border transition-colors whitespace-nowrap px-3 py-1"
            style={{ background: 'rgba(251,191,36,0.08)', borderColor: 'rgba(251,191,36,0.30)', color: '#fbbf24', fontFamily: 'var(--font-mono-t)', letterSpacing: '0.06em' }}
          >
            <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: '#fbbf24' }} />
            TRIAL · {trialDaysLeft}d
          </Link>
        )}
        {/* Stale data indicator */}
        {isStale && (
          <span className="text-[9px] text-[#F59E0B] px-1.5 py-0.5 rounded-full bg-[#F59E0B]/10 border border-[#F59E0B]/20">Data delayed</span>
        )}
        {/* Market status pill */}
        <div className="flex items-center gap-1.5 text-xs px-2.5 py-1 border" style={{ background: 'var(--bg-2)', borderColor: 'var(--border-dim)', fontFamily: 'var(--font-mono-t)', letterSpacing: '0.06em' }}>
          {wsStatus !== "connected" ? (
            <>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--amber)' }} />
              <WifiOff size={11} style={{ color: 'var(--amber)' }} />
              <span className="hidden sm:block" style={{ color: 'var(--amber)' }}>
                {isCryptoRoute ? "FEED OFFLINE" : "OFFLINE"}
              </span>
            </>
          ) : marketStatus === "open" ? (
            <>
              <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: 'var(--green)' }} />
              <Wifi size={11} style={{ color: 'var(--green)' }} />
              <span className="hidden sm:block" style={{ color: 'var(--green)' }}>{isCryptoRoute ? "24/7 LIVE" : "LIVE"}</span>
            </>
          ) : marketStatus === "after-hours" ? (
            <>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--amber)' }} />
              <Clock size={11} style={{ color: 'var(--amber)' }} />
              <span className="hidden sm:block" style={{ color: 'var(--amber)' }}>AH</span>
            </>
          ) : (
            <>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--text-dim)' }} />
              <Moon size={11} style={{ color: 'var(--text-dim)' }} />
              <span className="hidden sm:block" style={{ color: 'var(--text-dim)' }}>CLOSED</span>
            </>
          )}
        </div>

        {/* Simple / Pro mode toggle */}
        <button
          onClick={toggleMode}
          title={mode === "simple" ? "Switch to Pro Mode" : "Switch to Simple Mode"}
          className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-bold transition-colors duration-150 border cursor-pointer"
          style={mode === "pro"
            ? { background: 'rgba(251,191,36,0.08)', borderColor: 'rgba(251,191,36,0.30)', color: '#fbbf24', fontFamily: 'var(--font-mono-t)', letterSpacing: '0.08em' }
            : { background: 'transparent', borderColor: 'var(--border-dim)', color: 'var(--text-dim)', fontFamily: 'var(--font-mono-t)', letterSpacing: '0.08em' }
          }
        >
          {mode === "pro" ? <Zap size={11} color="#fbbf24" /> : <LayoutGrid size={11} />}
          <span className="hidden sm:block">{mode === "pro" ? "PRO" : "SIM"}</span>
        </button>

        <button onClick={openPanel} className="relative transition-colors duration-150 cursor-pointer p-1" style={{ color: 'var(--text-mid)' }}>
          <Bell size={17} />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 text-[var(--bg-base)] text-[9px] font-bold rounded-full w-4 h-4 flex items-center justify-center" style={{ background: 'var(--red)' }}>
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </button>
      </div>
    </header>
  );
}

import { useState, useRef, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bell, Wifi, WifiOff, ChevronDown,
  LayoutDashboard, Filter, BookMarked, Briefcase, Settings, Moon, GitCompare, X,
} from "lucide-react";
import { useWsStore, useAlertStore } from "@/store";
import { cn } from "@/lib/utils";
import SymbolSearch from "@/components/ui/SymbolSearch";
import type { ChartType } from "@/types/chart";

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

const CHART_TYPES: { value: ChartType; label: string }[] = [
  { value: "candle", label: "Candle" },
  { value: "heikinashi", label: "HA" },
  { value: "bar", label: "Bar" },
  { value: "line", label: "Line" },
  { value: "area", label: "Area" },
];

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", Icon: LayoutDashboard },
  { to: "/screener", label: "Screener", Icon: Filter },
  { to: "/watchlist", label: "Watchlist", Icon: BookMarked },
  { to: "/portfolio", label: "Portfolio", Icon: Briefcase },
];

const SEP = <div className="w-px h-5 bg-[#2a2e39] mx-1" />;

interface Props {
  symbol: string;
  chartType: ChartType;
  onSymbolChange: (s: string) => void;
  onChartTypeChange: (ct: ChartType) => void;
  onIndicatorsClick: () => void;
  onWatchlistToggle: () => void;
  showWatchlist: boolean;
  compareSymbol?: string;
  onCompare?: (s: string | null) => void;
  proMode?: boolean;
  onProModeToggle?: () => void;
  onTradeClick?: () => void;
}

export default function TvTopBar({
  symbol, chartType,
  onSymbolChange, onChartTypeChange,
  onIndicatorsClick, onWatchlistToggle, showWatchlist,
  compareSymbol, onCompare,
}: Props) {
  const navigate = useNavigate();
  const wsStatus = useWsStore((s) => s.status);
  const unread = useAlertStore((s) => s.unreadCount);
  const markAllRead = useAlertStore((s) => s.markAllRead);
  const marketStatus = useMarketStatus();

  const [searchMode, setSearchMode] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [typeOpen, setTypeOpen] = useState(false);
  const [compareMode, setCompareMode] = useState(false);
  const [compareInput, setCompareInput] = useState("");
  const navRef = useRef<HTMLDivElement>(null);
  const typeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (navRef.current && !navRef.current.contains(e.target as Node)) setNavOpen(false);
      if (typeRef.current && !typeRef.current.contains(e.target as Node)) setTypeOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const currentType = CHART_TYPES.find((t) => t.value === chartType);

  return (
    <header className="h-10 flex items-center gap-0 border-b border-[#2a2e39] bg-[#131722] shrink-0 select-none px-1">
      {/* Logo / Nav */}
      <div ref={navRef} className="relative">
        <button
          onClick={() => setNavOpen((o) => !o)}
          className="h-10 px-3 flex items-center gap-1.5 text-[var(--text-primary)] hover:bg-[#1e222d] font-bold text-sm tracking-wider"
        >
          BMG
          <ChevronDown size={12} className="text-[#4a4e5b]" />
        </button>
        {navOpen && (
          <div className="absolute top-10 left-0 z-50 bg-[#1e222d] border border-[#2a2e39] rounded shadow-2xl py-1 min-w-[160px]">
            {NAV_ITEMS.map(({ to, label, Icon }) => (
              <button
                key={to}
                onClick={() => { navigate(to); setNavOpen(false); }}
                className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-[#d1d4dc] hover:bg-[#2a2e39] hover:text-[var(--text-primary)]"
              >
                <Icon size={15} className="text-[#4a4e5b]" />
                {label}
              </button>
            ))}
            <div className="border-t border-[#2a2e39] my-1" />
            <button
              onClick={() => { navigate("/alerts"); setNavOpen(false); }}
              className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-[#d1d4dc] hover:bg-[#2a2e39] hover:text-[var(--text-primary)]"
            >
              <Bell size={15} className="text-[#4a4e5b]" />
              Alerts
            </button>
            <button
              onClick={() => setNavOpen(false)}
              className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-[#d1d4dc] hover:bg-[#2a2e39] hover:text-[var(--text-primary)]"
            >
              <Settings size={15} className="text-[#4a4e5b]" />
              Settings
            </button>
          </div>
        )}
      </div>

      {SEP}

      {/* Symbol search */}
      {searchMode ? (
        <SymbolSearch
          defaultValue={symbol}
          autoFocus
          onSelect={(s) => { onSymbolChange(s); setSearchMode(false); }}
          inputClassName="h-7 w-28 bg-[#2a2e39] text-[var(--text-primary)] text-sm font-bold px-2 rounded-l border border-white/20 focus:outline-none focus:border-white/50 uppercase tracking-wider"
        />
      ) : (
        <button
          onClick={() => setSearchMode(true)}
          className="h-10 px-3 flex items-center gap-2 text-[var(--text-primary)] font-bold text-sm hover:bg-[#1e222d] rounded"
        >
          <span className="tracking-wider">{symbol}</span>
        </button>
      )}

      {SEP}

      {/* Chart type dropdown */}
      <div ref={typeRef} className="relative">
        <button
          onClick={() => setTypeOpen((o) => !o)}
          className="h-10 px-2.5 flex items-center gap-1 text-xs text-[#d1d4dc] hover:bg-[#1e222d] font-medium"
        >
          {currentType?.label}
          <ChevronDown size={11} className="text-[#4a4e5b]" />
        </button>
        {typeOpen && (
          <div className="absolute top-10 left-0 z-50 bg-[#1e222d] border border-[#2a2e39] rounded shadow-2xl py-1 min-w-[110px]">
            {CHART_TYPES.map((ct) => (
              <button
                key={ct.value}
                onClick={() => { onChartTypeChange(ct.value); setTypeOpen(false); }}
                className={cn(
                  "w-full text-left px-3 py-1.5 text-sm",
                  chartType === ct.value
                    ? "text-[var(--text-primary)] bg-[#2a2e39]"
                    : "text-[#d1d4dc] hover:bg-[#2a2e39] hover:text-[var(--text-primary)]"
                )}
              >
                {ct.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {SEP}

      {/* Indicators */}
      <button
        onClick={onIndicatorsClick}
        className="h-10 px-3 text-xs font-medium text-[#d1d4dc] hover:bg-[#1e222d] hover:text-[var(--text-primary)]"
      >
        Indicators
      </button>

      {SEP}

      {/* Compare */}
      {compareSymbol ? (
        <div className="flex items-center gap-1 h-10 px-2">
          <span className="text-[11px] text-[#f59e0b] font-semibold">vs {compareSymbol}</span>
          <button
            onClick={() => { onCompare?.(null); setCompareMode(false); setCompareInput(""); }}
            className="text-[#4a4e5b] hover:text-[#d1d4dc] ml-0.5"
          >
            <X size={11} />
          </button>
        </div>
      ) : compareMode ? (
        <form
          className="flex items-center h-10 px-1 gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            const sym = compareInput.trim().toUpperCase();
            if (sym) { onCompare?.(sym); setCompareMode(false); setCompareInput(""); }
          }}
        >
          <input
            autoFocus
            value={compareInput}
            onChange={(e) => setCompareInput(e.target.value.toUpperCase())}
            placeholder="Symbol…"
            className="h-6 w-20 bg-[#2a2e39] text-[var(--text-primary)] text-xs font-mono px-1.5 rounded border border-[#4a4e5b] focus:outline-none focus:border-[#f59e0b] uppercase"
          />
          <button type="button" onClick={() => { setCompareMode(false); setCompareInput(""); }} className="text-[#4a4e5b] hover:text-[#d1d4dc]">
            <X size={11} />
          </button>
        </form>
      ) : (
        <button
          onClick={() => setCompareMode(true)}
          className="h-10 px-2.5 flex items-center gap-1 text-xs text-[#4a4e5b] hover:bg-[#1e222d] hover:text-[#d1d4dc]"
          title="Compare symbol"
        >
          <GitCompare size={13} />
          <span className="hidden sm:inline">Compare</span>
        </button>
      )}

      <div className="flex-1" />

      {/* Watchlist toggle */}
      <button
        onClick={onWatchlistToggle}
        className={cn(
          "h-10 px-2.5 text-xs font-medium hover:bg-[#1e222d]",
          showWatchlist ? "text-[var(--text-primary)]" : "text-[#4a4e5b]"
        )}
      >
        <BookMarked size={15} />
      </button>

      {/* WS status */}
      <div className="h-10 px-2 flex items-center gap-1.5 text-xs">
        {wsStatus === "connected" && marketStatus === "open" ? (
          <><Wifi size={13} className="text-[#26a69a]" /><span className="text-[#26a69a] hidden sm:block">Live</span></>
        ) : wsStatus === "connected" ? (
          <><Moon size={13} className="text-amber-500" /><span className="text-amber-500 hidden sm:block">Closed</span></>
        ) : (
          <><WifiOff size={13} className="text-[#ef5350]" /><span className="text-[#ef5350] hidden sm:block">Off</span></>
        )}
      </div>

      {/* Alerts bell */}
      <button onClick={markAllRead} className="relative h-10 px-2 flex items-center text-[#4a4e5b] hover:text-[#d1d4dc]">
        <Bell size={15} />
        {unread > 0 && (
          <span className="absolute top-1.5 right-1 bg-[#ef5350] text-[var(--text-primary)] text-[9px] rounded-full w-3.5 h-3.5 flex items-center justify-center font-bold">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
    </header>
  );
}

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { LayoutList, X, Check } from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { useSearchParams } from "react-router-dom";
import CandlestickChart, { type ChartHandle, type TradeLevels, type SignalMarker } from "@/components/chart/CandlestickChart";
import { getTrades } from "@/api/strategy";
import RsiChart from "@/components/chart/RsiChart";
import MacdChart from "@/components/chart/MacdChart";
import OscillatorPane from "@/components/chart/OscillatorPane";
import TvTopBar from "@/components/chart/TvTopBar";
import TvBottomBar, { type Period, PERIOD_CONFIGS } from "@/components/chart/TvBottomBar";
import DrawingToolbar from "@/components/chart/DrawingToolbar";
import IndicatorsModal from "@/components/chart/IndicatorsModal";
import WatchlistPanel from "@/components/panels/WatchlistPanel";
import OrderTicket from "@/components/trading/OrderTicket";
import PaywallSheet from "@/components/paywall/PaywallSheet";
import { useBars } from "@/hooks/useBars";
import { useMarketStore } from "@/store";
import { useTierStore } from "@/store/tierStore";
import { getDrawings, saveDrawings } from "@/api/chartDrawings";
import { formatCurrency, formatVolume, cn } from "@/lib/utils";
import type { ChartType, DrawingTool, HoveredBar, Drawing } from "@/types/chart";

const OVERLAY_COLORS: Record<string, string> = {
  SMA_20: "#f59e0b", SMA_50: "#3b82f6", SMA_200: "#8b5cf6",
  EMA_20: "#fbbf24", EMA_50: "#60a5fa", EMA_200: "#a78bfa",
  DEMA_20: "#f472b6",
  VWAP: "#06b6d4",
  BB_20_upper: "#64748b", BB_20_middle: "#94a3b8", BB_20_lower: "#64748b",
  ICHI_tenkan: "#26a69a",
  ICHI_kijun: "#ef5350",
  ICHI_senkou_a: "rgba(38,166,154,0.1)",
  ICHI_senkou_b: "rgba(239,83,80,0.1)",
  PSAR: "#9c27b0",
  DONCHIAN_upper: "#607d8b",
  DONCHIAN_mid: "#90a4ae",
  DONCHIAN_lower: "#607d8b",
  KELTNER_upper: "#ff9800",
  KELTNER_mid: "#ffb74d",
  KELTNER_lower: "#ff9800",
  // New overlay indicators
  WMA_10: "#34d399", WMA_20: "#10b981", WMA_50: "#059669",
  KAMA_10: "#f87171",
  TEMA_20: "#fb923c",
  HMA_20: "#facc15",
  LINREG: "#e2e8f0",
  NVI: "#d946ef",
  PVI: "#22c55e",
  VWAP_UPPER: "#67e8f9",
  VWAP_LOWER: "#67e8f9",
};

function indicatorLabel(key: string): string {
  if (key === "VWAP") return "VWAP";
  return key.replace(/_/g, " ");
}

function isOverlayKey(key: string): boolean {
  return key.startsWith("SMA_") || key.startsWith("EMA_") || key.startsWith("DEMA_")
    || key.startsWith("WMA_") || key.startsWith("KAMA_") || key.startsWith("TEMA_")
    || key.startsWith("HMA_")
    || key === "VWAP" || key === "PSAR" || key === "LINREG"
    || key === "NVI" || key === "PVI"
    || key === "VWAP_UPPER" || key === "VWAP_LOWER"
    || key.startsWith("ICHI_") || key.startsWith("DONCHIAN_") || key.startsWith("KELTNER_")
    || key.endsWith("_upper") || key.endsWith("_middle") || key.endsWith("_lower");
}

const toUnix = (t: string) => Math.floor(new Date(t).getTime() / 1000);

const PRESET_LABELS: Record<string, string> = {
  // Crypto strategies
  btc_ma_crossover:         "BTC Golden Cross",
  rsi_oversold_crypto:      "RSI Bounce",
  breakout_30d_high:        "30-Day Breakout",
  volume_surge_crypto:      "Volume Surge",
  dca_accumulation:         "DCA Accumulation",
  momentum_continuation:    "Momentum Continuation",
  oversold_bounce:          "Oversold Bounce",
  golden_zone_retrace:      "Golden Zone Retrace",
  pi_cycle_top:             "Pi Cycle Top",
  donchian_breakout:        "Donchian Breakout",
  tsmom:                    "Time-Series Momentum",
  ma_200w:                  "200-Day MA Support",
  zscore_reversal:          "Z-Score Reversion",
  halving_phase:            "Halving Phase",
  cross_sectional_momentum: "Cross-Sectional Momentum",
  altseason_index:          "Altseason Index",
  eth_btc_ratio:            "ETH/BTC Rotation",
  narrative_basket:         "Narrative Basket",
  nupl_signal:              "NUPL Accumulation",
  mvrv_zscore:              "MVRV Z-Score",
  sopr_reversal:            "SOPR Reversal",
  exchange_netflow:         "Exchange Net Flow",
  stablecoin_ratio:         "Stablecoin Supply Ratio",
  funding_rate_contrarian:  "Funding Rate Contrarian",
  oi_divergence:            "Open Interest Divergence",
  basis_carry:              "Cash & Carry Basis",
  // Equity strategies
  canslim_leaders: "CAN SLIM Leaders",
  stage2_breakout: "Stage 2 Breakout",
  momentum_surge: "Momentum Surge",
  high_rs_momentum: "High RS Leaders",
  power_trend: "Power Trend",
  mean_reversion_quality: "Quality Dip Buy",
  deep_value_bounce: "Quality Oversold",
  volatility_contraction: "Volatility Squeeze",
  ema_stack_uptrend: "EMA Stack",
  consecutive_gains: "Momentum Continuation",
  rsi_oversold: "RSI Oversold",
  golden_cross: "Golden Cross",
  macd_bullish: "MACD Crossover",
  volume_surge: "Volume Surge",
  breakout_52w: "52-Week High",
};

const PRESET_INDICATOR_MAP: Record<string, string[]> = {
  // Crypto strategies
  btc_ma_crossover:         ["SMA_50", "SMA_200"],
  rsi_oversold_crypto:      ["RSI_14", "SMA_50"],
  breakout_30d_high:        ["SMA_20", "SMA_50"],
  volume_surge_crypto:      ["SMA_20"],
  dca_accumulation:         ["SMA_200", "RSI_14"],
  momentum_continuation:    ["SMA_50", "SMA_200", "RSI_14"],
  oversold_bounce:          ["RSI_14"],
  golden_zone_retrace:      ["SMA_50", "SMA_200", "RSI_14"],
  pi_cycle_top:             ["SMA_50", "SMA_200"],
  donchian_breakout:        ["DONCHIAN"],
  tsmom:                    ["SMA_50", "SMA_200"],
  ma_200w:                  ["SMA_200"],
  zscore_reversal:          ["BB_20", "RSI_14"],
  halving_phase:            ["SMA_50", "SMA_200"],
  cross_sectional_momentum: ["RSI_14", "SMA_50"],
  altseason_index:          ["SMA_20", "SMA_50"],
  eth_btc_ratio:            ["SMA_20", "SMA_50"],
  narrative_basket:         ["SMA_20", "RSI_14"],
  nupl_signal:              ["SMA_50", "SMA_200", "RSI_14"],
  mvrv_zscore:              ["SMA_200", "RSI_14"],
  sopr_reversal:            ["SMA_50", "RSI_14"],
  exchange_netflow:         ["SMA_50", "SMA_200"],
  stablecoin_ratio:         ["SMA_50", "SMA_200", "RSI_14"],
  funding_rate_contrarian:  ["RSI_14", "EMA_20"],
  oi_divergence:            ["RSI_14", "SMA_50"],
  basis_carry:              ["EMA_20", "SMA_50"],
  // Equity strategies
  canslim_leaders:        ["SMA_50", "SMA_200", "RSI_14"],
  stage2_breakout:        ["SMA_50", "SMA_200", "RSI_14"],
  momentum_surge:         ["RSI_14", "SMA_50"],
  high_rs_momentum:       ["RSI_14", "SMA_50"],
  power_trend:            ["EMA_20", "EMA_50", "EMA_200"],
  mean_reversion_quality: ["SMA_200", "RSI_14"],
  deep_value_bounce:      ["SMA_200", "RSI_14"],
  volatility_contraction: ["BB_20", "SMA_50"],
  ema_stack_uptrend:      ["EMA_20", "EMA_50", "EMA_200"],
  consecutive_gains:      ["RSI_14"],
  rsi_oversold:           ["RSI_14"],
  golden_cross:           ["SMA_50", "SMA_200"],
  macd_bullish:           ["MACD"],
  volume_surge:           ["SMA_20", "SMA_50"],
  breakout_52w:           ["SMA_50", "SMA_200"],
};

function getStoredSymbol() {
  try { return localStorage.getItem("bmg_symbol") ?? "AAPL"; } catch { return "AAPL"; }
}

// ── Debounce helper ────────────────────────────────────────────────────────────
function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

export default function ChartPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [symbol, setSymbol] = useState(() => searchParams.get("symbol") ?? getStoredSymbol());
  const [period, setPeriod] = useState<Period>("1Y");
  const [userPickedPeriod, setUserPickedPeriod] = useState(false);
  const [chartType, setChartType] = useState<ChartType>("candle");
  // Initialize with preset indicators immediately so the first useBars call includes them
  const [activeIndicators, setActiveIndicators] = useState<Set<string>>(() => {
    const base = new Set<string>(["SMA_20", "SMA_50"]);
    const preset = searchParams.get("preset");
    if (preset) {
      for (const ind of PRESET_INDICATOR_MAP[preset] ?? []) base.add(ind);
    }
    return base;
  });
  const [activeTool, setActiveTool] = useState<DrawingTool>("cursor");
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [pendingTrendStart, setPendingTrendStart] = useState<{ time: number; price: number } | null>(null);
  const [pendingRectStart, setPendingRectStart] = useState<{ time: number; price: number } | null>(null);
  const [pendingFibStart, setPendingFibStart] = useState<{ time: number; price: number } | null>(null);
  const [pendingTextPoint, setPendingTextPoint] = useState<{ time: number; price: number } | null>(null);
  const [textInputValue, setTextInputValue] = useState("");
  const [pendingChannelPoints, setPendingChannelPoints] = useState<{ time: number; price: number }[]>([]);
  const [pendingPosPoints, setPendingPosPoints] = useState<{ time: number; price: number }[]>([]);
  const [pendingArrowPoint, setPendingArrowPoint] = useState<{ time: number; price: number } | null>(null);
  const [arrowInputValue, setArrowInputValue] = useState("");
  const [hoveredBar, setHoveredBar] = useState<HoveredBar | null>(null);
  const [showIndicatorsModal, setShowIndicatorsModal] = useState(false);
  const [showWatchlist, setShowWatchlist] = useState(true);
  const [compareSymbol, setCompareSymbol] = useState<string | null>(null);
  const [proMode, setProMode] = useState(false);
  const [showOrderTicket, setShowOrderTicket] = useState(false);
  const [showProPaywall, setShowProPaywall] = useState(false);
  const canProMode = useTierStore((s) => s.can("pro_mode"));
  const [savedIndicator, setSavedIndicator] = useState(false);
  const [aiDrawerOpen, setAiDrawerOpen] = useState(false);

  const presetKey = searchParams.get("preset") ?? null;

  const tradeLevels = useMemo<TradeLevels | undefined>(() => {
    const entry     = parseFloat(searchParams.get("entry")     ?? "");
    const stop      = parseFloat(searchParams.get("stop")      ?? "");
    const target    = parseFloat(searchParams.get("target")    ?? "");
    const exitPrice = parseFloat(searchParams.get("exitPrice") ?? "");
    const entryDate  = searchParams.get("entryDate")  ?? undefined;
    const exitDate   = searchParams.get("exitDate")   ?? undefined;
    const exitReason = searchParams.get("exitReason") ?? undefined;
    if (!isNaN(entry) || !isNaN(stop) || !isNaN(target) || !isNaN(exitPrice)) {
      return {
        entry:     isNaN(entry)     ? undefined : entry,
        stop:      isNaN(stop)      ? undefined : stop,
        target:    isNaN(target)    ? undefined : target,
        exitPrice: isNaN(exitPrice) ? undefined : exitPrice,
        entryDate,
        exitDate,
        exitReason,
      };
    }
    return undefined;
  }, [searchParams]);

  // Derive timeframe + start date from period, or from trade levels on initial load.
  // Once the user explicitly picks a period button, always honour their selection.
  const { timeframe, start } = useMemo(() => {
    if (tradeLevels?.entryDate && !userPickedPeriod) {
      const d = new Date(tradeLevels.entryDate);
      d.setDate(d.getDate() - 30);
      return { timeframe: "1Day", start: d.toISOString().slice(0, 10) };
    }
    const cfg = PERIOD_CONFIGS[period];
    return { timeframe: cfg.timeframe, start: cfg.getStart() };
  }, [period, tradeLevels, userPickedPeriod]);

  // Strategy signal markers for current symbol
  const { data: allTrades } = useQuery({
    queryKey: ["strategy-trades"],
    queryFn: getTrades,
    staleTime: 60_000,
  });
  const signalMarkers = useMemo<SignalMarker[]>(() => {
    if (!allTrades?.trades) return [];
    return (allTrades.trades as any[])
      .filter((t) => t.symbol === symbol && (t.entry_date || t.exit_date))
      .flatMap((t): SignalMarker[] => {
        const markers: SignalMarker[] = [];
        if (t.entry_date) {
          markers.push({
            time: Math.floor(new Date(t.entry_date).getTime() / 1000),
            isEntry: true,
            label: `B ${t.preset_label ?? ""}`.trim(),
          });
        }
        if (t.exit_date && t.status === "closed") {
          markers.push({
            time: Math.floor(new Date(t.exit_date).getTime() / 1000),
            isEntry: false,
            label: `S ${t.exit_reason ?? ""}`.replace("_", " ").trim(),
          });
        }
        return markers;
      });
  }, [allTrades, symbol]);

  // Extra years added when user zooms past the left edge
  const [extraYears, setExtraYears] = useState(0);
  const loadingMoreRef = useRef(false);

  // Reset extra years whenever the period or symbol changes
  useEffect(() => { setExtraYears(0); }, [period, symbol]);

  // Extend start further back when the user has scrolled past the data window
  const dynamicStart = useMemo(() => {
    if (!start || extraYears === 0) return start;
    const d = new Date(start);
    d.setFullYear(d.getFullYear() - extraYears);
    return d.toISOString().slice(0, 10);
  }, [start, extraYears]);

  const handleNearLeftEdge = useCallback(() => {
    if (loadingMoreRef.current || period === "All") return;
    loadingMoreRef.current = true;
    setExtraYears((y) => y + 2);
    setTimeout(() => { loadingMoreRef.current = false; }, 4000);
  }, [period]);

  const presetIndsRef = useRef<string[]>([]);
  const [presetActive, setPresetActive] = useState(true);
  const [showPresetBanner, setShowPresetBanner] = useState(!!presetKey);

  const chartRef = useRef<ChartHandle>(null);
  const liveBar = useMarketStore((s) => s.liveBars[symbol]);

  const indicatorsParam = Array.from(activeIndicators).join(",");
  const { data, isLoading, isFetching, isError } = useBars(symbol, timeframe, indicatorsParam || undefined, dynamicStart);
  const { data: compareData } = useBars(compareSymbol ?? "", timeframe, undefined, dynamicStart);

  const bars = data?.bars ?? [];
  const indicators = data?.indicators ?? {};

  // ── Drawing persistence ────────────────────────────────────────────────────
  // Load drawings when symbol/timeframe changes
  useEffect(() => {
    if (!symbol || !timeframe) return;
    getDrawings(symbol, timeframe)
      .then((res) => {
        if (res.drawings && Array.isArray(res.drawings)) {
          setDrawings(res.drawings);
        }
      })
      .catch((err) => console.error("Chart error:", err));
  }, [symbol, timeframe]);

  // Debounced save: persist drawings 500ms after last change
  const debouncedDrawings = useDebounce(drawings, 500);
  const saveRef = useRef({ symbol, timeframe });
  useEffect(() => { saveRef.current = { symbol, timeframe }; }, [symbol, timeframe]);

  const isInitialMount = useRef(true);
  useEffect(() => {
    // Skip the very first render so we don't overwrite loaded drawings
    if (isInitialMount.current) { isInitialMount.current = false; return; }
    const { symbol: sym, timeframe: tf } = saveRef.current;
    saveDrawings(sym, tf, debouncedDrawings)
      .then(() => {
        setSavedIndicator(true);
        setTimeout(() => setSavedIndicator(false), 1500);
      })
      .catch((err) => console.error("Chart error:", err));
  }, [debouncedDrawings]);

  // Live bar updates
  useEffect(() => {
    if (liveBar && chartRef.current) {
      chartRef.current.updateBar({
        t: liveBar.timestamp, o: liveBar.open, h: liveBar.high,
        l: liveBar.low, c: liveBar.close, v: liveBar.volume,
      });
    }
  }, [liveBar]);

  // Auto-enable preset indicators when arriving from the screener
  useEffect(() => {
    if (!presetKey) return;
    const inds = PRESET_INDICATOR_MAP[presetKey] ?? [];
    presetIndsRef.current = inds;
    setActiveIndicators((prev) => new Set([...prev, ...inds]));
    setPresetActive(true);
    setShowPresetBanner(true);
  }, [presetKey]);

  const handlePresetToggle = () => {
    const inds = presetIndsRef.current;
    if (presetActive) {
      setActiveIndicators((prev) => { const n = new Set(prev); inds.forEach((k) => n.delete(k)); return n; });
    } else {
      setActiveIndicators((prev) => new Set([...prev, ...inds]));
    }
    setPresetActive((p) => !p);
  };

  const handleSymbolChange = (s: string) => {
    setSymbol(s);
    setSearchParams({ symbol: s });
    try { localStorage.setItem("bmg_symbol", s); } catch (err) { console.error("Chart error:", err); }
    // Clear local drawings; new ones load via useEffect
    setDrawings([]);
    setPendingTrendStart(null);
    setPendingChannelPoints([]);
    setPendingPosPoints([]);
    setPendingArrowPoint(null);
    isInitialMount.current = true;
  };

  const handleAddDrawing = useCallback((partial: Omit<Drawing, "id">) => {
    if (partial.type === "trendline") {
      if (!pendingTrendStart) {
        setPendingTrendStart(partial.p1!);
      } else {
        setDrawings((prev) => [
          ...prev,
          { id: crypto.randomUUID(), type: "trendline", p1: pendingTrendStart, p2: partial.p1!, color: "#2196f3" },
        ]);
        setPendingTrendStart(null);
      }
    } else if (partial.type === "rect") {
      if (!pendingRectStart) {
        setPendingRectStart(partial.p1!);
      } else {
        setDrawings((prev) => [
          ...prev,
          { id: crypto.randomUUID(), type: "rect", p1: pendingRectStart, p2: partial.p1!, color: "#f59e0b" },
        ]);
        setPendingRectStart(null);
      }
    } else if (partial.type === "fib") {
      if (!pendingFibStart) {
        setPendingFibStart(partial.p1!);
      } else {
        setDrawings((prev) => [
          ...prev,
          { id: crypto.randomUUID(), type: "fib", p1: pendingFibStart, p2: partial.p1!, color: "#9c27b0" },
        ]);
        setPendingFibStart(null);
      }
    } else if (partial.type === "text") {
      setPendingTextPoint(partial.p1!);
      setTextInputValue("");
    } else if (partial.type === "channel") {
      setPendingChannelPoints((prev) => {
        const pts = [...prev, partial.p1!];
        if (pts.length === 1) return pts;
        if (pts.length === 2) return pts;
        // 3rd click: complete channel
        setDrawings((d) => [
          ...d,
          { id: crypto.randomUUID(), type: "channel", p1: pts[0], p2: pts[1], p3: pts[2], color: "#2196f3" },
        ]);
        return [];
      });
    } else if (partial.type === "longpos" || partial.type === "shortpos") {
      const posType = partial.type;
      setPendingPosPoints((prev) => {
        const pts = [...prev, partial.p1!];
        if (pts.length < 3) return pts;
        setDrawings((d) => [
          ...d,
          { id: crypto.randomUUID(), type: posType, p1: pts[0], p2: pts[1], p3: pts[2], color: "#2196f3" },
        ]);
        return [];
      });
    } else if (partial.type === "arrow") {
      setPendingArrowPoint(partial.p1!);
      setArrowInputValue("");
    } else {
      setDrawings((prev) => [...prev, { id: crypto.randomUUID(), ...partial }]);
    }
  }, [pendingTrendStart, pendingRectStart, pendingFibStart]);

  const handleClearDrawings = () => {
    setDrawings([]);
    setPendingTrendStart(null);
    setPendingRectStart(null);
    setPendingFibStart(null);
    setPendingTextPoint(null);
    setPendingChannelPoints([]);
    setPendingPosPoints([]);
    setPendingArrowPoint(null);
    setActiveTool("cursor");
  };

  // Price display fallback to last bar
  const displayBar = hoveredBar ?? (bars.length > 0 ? {
    time: 0,
    open: bars.at(-1)!.o,
    high: bars.at(-1)!.h,
    low: bars.at(-1)!.l,
    close: bars.at(-1)!.c,
    volume: bars.at(-1)!.v,
  } : null);

  const isUp = displayBar ? displayBar.close >= displayBar.open : true;
  const priceColor = isUp ? "#26a69a" : "#ef5350";

  // Find bar index matching the hovered crosshair time for indicator overlay
  const hoveredIdx = useMemo(() => {
    if (!hoveredBar) return bars.length - 1;
    const idx = bars.findIndex((b) => toUnix(b.t) === hoveredBar.time);
    return idx >= 0 ? idx : bars.length - 1;
  }, [hoveredBar, bars]);

  const overlayIndicators = useMemo(() =>
    Object.entries(indicators).filter(([k]) => isOverlayKey(k)),
    [indicators]
  );

  // Existing sub-pane indicators
  const hasRsi   = "RSI_14"    in indicators;
  const hasMacd  = "MACD_line" in indicators;
  const hasStoch = "STOCH_k"   in indicators;
  const hasWillR = "WILLR"     in indicators;
  const hasCci   = "CCI"       in indicators;
  const hasObv   = "OBV"       in indicators;
  const hasAtr   = "ATR"       in indicators;

  // Existing derived indicator checks
  const hasAdx      = "ADX"          in indicators;
  const hasIchimoku = "ICHI_tenkan"  in indicators;
  const hasPsar     = "PSAR"         in indicators;
  const hasDonchian = "DONCHIAN_upper" in indicators;
  const hasKeltner  = "KELTNER_upper"  in indicators;
  const hasCmf      = "CMF"          in indicators;
  const hasMfi      = "MFI"          in indicators;
  const hasRoc      = "ROC"          in indicators;

  // New sub-pane indicator checks
  const hasAo         = "AO"           in indicators;
  const hasUo         = "UO"           in indicators;
  const hasTrix       = "TRIX_15"      in indicators;
  const hasAroon      = "AROON_up"     in indicators;
  const hasDpo        = "DPO"          in indicators;
  const hasMass       = "MASS"         in indicators;
  const hasKst        = "KST_line"     in indicators;
  const hasVortex     = "VORTEX_pos"   in indicators;
  const hasStc        = "STC"          in indicators;
  const hasPpo        = "PPO_line"     in indicators;
  const hasTsi        = "TSI"          in indicators;
  const hasCmo        = "CMO"          in indicators;
  const hasFisher     = "FISHER_line"  in indicators;
  const hasCoppock    = "COPPOCK"      in indicators;
  const hasUi         = "UI"           in indicators;
  const hasBbwidth    = "BBWIDTH"      in indicators;
  const hasBbp        = "BBP"          in indicators;
  const hasNatr       = "NATR"         in indicators;
  const hasHv         = "HV"           in indicators;
  const hasRviVol     = "RVI_VOL"      in indicators;
  const hasAdi        = "ADI"          in indicators;
  const hasEom        = "EOM"          in indicators;
  const hasFi         = "FI"           in indicators;
  const hasZscore     = "ZSCORE"       in indicators;
  const hasLinregSlope = "LINREG_SLOPE" in indicators;
  const hasMomentum   = "MOMENTUM_10"  in indicators;

  // Sub-pane indicators are only visible in pro mode
  const showSubPanes = proMode;

  return (
    <div className="flex flex-col flex-1 overflow-hidden bg-[var(--bg-base)] text-[var(--text-secondary)]">
      {/* Top bar */}
      <TvTopBar
        symbol={symbol}
        chartType={chartType}
        onSymbolChange={handleSymbolChange}
        onChartTypeChange={setChartType}
        onIndicatorsClick={() => setShowIndicatorsModal(true)}
        onWatchlistToggle={() => setShowWatchlist((s) => !s)}
        showWatchlist={showWatchlist}
        compareSymbol={compareSymbol ?? undefined}
        onCompare={(s) => setCompareSymbol(s)}
        proMode={proMode}
        onProModeToggle={() => {
          if (!proMode && !canProMode) {
            setShowProPaywall(true);
          } else {
            setProMode((p) => !p);
          }
        }}
        onTradeClick={() => setShowOrderTicket(true)}
        onAnalyzeClick={() => setAiDrawerOpen(true)}
      />

      {/* Preset context banner */}
      {showPresetBanner && presetKey && PRESET_LABELS[presetKey] && (
        <div className="h-8 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated)] flex items-center px-3 gap-3 shrink-0">
          <span className="text-[11px] text-[var(--text-tertiary)]">Screened by</span>
          <span className="text-[11px] font-semibold text-[var(--text-secondary)]">{PRESET_LABELS[presetKey]}</span>
          <button
            onClick={handlePresetToggle}
            title={presetActive ? "Hide preset indicators" : "Show preset indicators"}
            className={cn(
              "w-8 h-4 rounded-full relative transition-colors shrink-0 focus:outline-none",
              presetActive ? "bg-[var(--accent-positive)]" : "bg-[#2a2e39]"
            )}
          >
            <span className={cn(
              "absolute top-0.5 w-3 h-3 bg-white rounded-full shadow transition-all",
              presetActive ? "left-[18px]" : "left-0.5"
            )} />
          </button>
          <span className="text-[10px] text-[var(--text-tertiary)]">{presetActive ? "on" : "off"}</span>
          <button
            onClick={() => setShowPresetBanner(false)}
            className="ml-auto text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            title="Dismiss"
          >
            <X size={12} />
          </button>
        </div>
      )}

      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left drawing toolbar — only visible in pro mode */}
        {proMode && (
          <DrawingToolbar
            activeTool={activeTool}
            onChange={setActiveTool}
            onClearAll={handleClearDrawings}
          />
        )}

        {/* Chart area */}
        <div className="flex-1 flex flex-col overflow-hidden relative">
          {/* OHLCV info overlay */}
          <div className="absolute top-0 left-0 z-10 pointer-events-none flex items-center gap-0 px-2 pt-1.5 flex-wrap">
            <span className="text-[var(--text-secondary)] font-semibold text-xs mr-2">{symbol}</span>
            {displayBar && (
              <>
                <span className="text-[var(--text-tertiary)] text-[11px] mr-1.5">O</span>
                <span className="text-[11px] mr-2" style={{ color: priceColor }}>{displayBar.open.toFixed(2)}</span>
                <span className="text-[var(--text-tertiary)] text-[11px] mr-1.5">H</span>
                <span className="text-[11px] mr-2" style={{ color: priceColor }}>{displayBar.high.toFixed(2)}</span>
                <span className="text-[var(--text-tertiary)] text-[11px] mr-1.5">L</span>
                <span className="text-[11px] mr-2" style={{ color: priceColor }}>{displayBar.low.toFixed(2)}</span>
                <span className="text-[var(--text-tertiary)] text-[11px] mr-1.5">C</span>
                <span className="text-[11px] font-semibold mr-2" style={{ color: priceColor }}>{displayBar.close.toFixed(2)}</span>
                <span className="text-[var(--text-tertiary)] text-[11px] mr-1.5">V</span>
                <span className="text-[var(--text-tertiary)] text-[11px] mr-3">{formatVolume(displayBar.volume)}</span>
              </>
            )}
            {overlayIndicators.map(([key, vals]) => {
              const val = vals[hoveredIdx];
              if (val == null) return null;
              const color = OVERLAY_COLORS[key] ?? "#94a3b8";
              return (
                <span key={key} className="flex items-center gap-0.5 mr-2">
                  <span style={{ color }} className="text-[9px] leading-none">●</span>
                  <span style={{ color }} className="text-[11px]">
                    {indicatorLabel(key)} {val.toFixed(2)}
                  </span>
                </span>
              );
            })}
            {pendingTrendStart && (
              <span className="ml-3 text-[11px] text-[var(--text-secondary)]">Click second point to complete trend line</span>
            )}
            {pendingRectStart && (
              <span className="ml-3 text-[11px] text-[#F59E0B]">Click opposite corner to complete rectangle</span>
            )}
            {pendingFibStart && (
              <span className="ml-3 text-[11px] text-[#A78BFA]">Click second point to complete Fibonacci</span>
            )}
            {pendingTextPoint && (
              <span className="ml-3 text-[11px] text-[var(--text-secondary)]">Type label and press Enter</span>
            )}
            {pendingChannelPoints.length === 1 && (
              <span className="ml-3 text-[11px] text-[#2196f3]">Click second point to set channel direction</span>
            )}
            {pendingChannelPoints.length === 2 && (
              <span className="ml-3 text-[11px] text-[#2196f3]">Click to set second channel line offset</span>
            )}
            {pendingPosPoints.length === 1 && (
              <span className="ml-3 text-[11px] text-[#ef4444]">Click to set stop loss level</span>
            )}
            {pendingPosPoints.length === 2 && (
              <span className="ml-3 text-[11px] text-[#22c55e]">Click to set target level</span>
            )}
            {pendingArrowPoint && (
              <span className="ml-3 text-[11px] text-[var(--text-secondary)]">Type arrow label and press Enter</span>
            )}
          </div>

          {/* Saved drawings indicator */}
          {savedIndicator && (
            <div className="absolute top-1 right-16 z-20 flex items-center gap-1 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded px-2 py-0.5 text-[10px] text-[var(--accent-positive)] pointer-events-none animate-in fade-in duration-200">
              <Check size={10} />
              saved
            </div>
          )}

          {/* Text label input overlay */}
          {pendingTextPoint && (
            <div className="absolute inset-0 z-30 flex items-center justify-center pointer-events-none">
              <div className="pointer-events-auto bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 flex items-center gap-2 shadow-xl">
                <input
                  autoFocus
                  type="text"
                  value={textInputValue}
                  onChange={(e) => setTextInputValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && textInputValue.trim()) {
                      setDrawings((prev) => [
                        ...prev,
                        { id: crypto.randomUUID(), type: "text", p1: pendingTextPoint, color: "#d1d4dc", label: textInputValue.trim() },
                      ]);
                      setPendingTextPoint(null);
                      setTextInputValue("");
                    } else if (e.key === "Escape") {
                      setPendingTextPoint(null);
                      setTextInputValue("");
                    }
                  }}
                  placeholder="Label text…"
                  className="bg-transparent text-[var(--text-secondary)] text-sm outline-none w-40 placeholder:text-[var(--text-tertiary)]"
                />
                <span className="text-[var(--text-tertiary)] text-[10px]">Enter ↵</span>
              </div>
            </div>
          )}

          {/* Arrow label input overlay */}
          {pendingArrowPoint && (
            <div className="absolute inset-0 z-30 flex items-center justify-center pointer-events-none">
              <div className="pointer-events-auto bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 flex items-center gap-2 shadow-xl">
                <input
                  autoFocus
                  type="text"
                  value={arrowInputValue}
                  onChange={(e) => setArrowInputValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && arrowInputValue.trim()) {
                      setDrawings((prev) => [
                        ...prev,
                        { id: crypto.randomUUID(), type: "arrow", p1: pendingArrowPoint, color: "#d1d4dc", metadata: { label: arrowInputValue.trim() } },
                      ]);
                      setPendingArrowPoint(null);
                      setArrowInputValue("");
                    } else if (e.key === "Escape") {
                      setPendingArrowPoint(null);
                      setArrowInputValue("");
                    }
                  }}
                  placeholder="Arrow label…"
                  className="bg-transparent text-[var(--text-secondary)] text-sm outline-none w-40 placeholder:text-[var(--text-tertiary)]"
                />
                <span className="text-[var(--text-tertiary)] text-[10px]">Enter ↵</span>
              </div>
            </div>
          )}

          {/* Main chart */}
          <div className="flex-1 overflow-hidden relative">
            {isLoading ? (
              <div className="w-full h-full flex items-center justify-center text-[var(--text-tertiary)] text-sm">
                Loading {symbol}...
              </div>
            ) : isError && bars.length === 0 ? (
              <div className="w-full h-full flex flex-col items-center justify-center gap-3 text-center px-8">
                <div className="text-3xl">📡</div>
                <p className="text-[var(--text-secondary)] font-semibold text-sm">No chart data for {symbol}</p>
                <p className="text-[var(--text-tertiary)] text-xs max-w-xs leading-relaxed">
                  This symbol may not be supported. For crypto, try the full ticker (e.g. BTC-USD) or check the Crypto Lab for on-chain data.
                </p>
              </div>
            ) : (
              <>
                <CandlestickChart
                  ref={chartRef}
                  bars={bars}
                  indicators={indicators}
                  chartType={chartType}
                  activeTool={proMode ? activeTool : "cursor"}
                  drawings={drawings}
                  tradeLevels={tradeLevels}
                  signalMarkers={signalMarkers}
                  compareBars={compareData?.bars}
                  compareSymbol={compareSymbol ?? undefined}
                  onCrosshairMove={setHoveredBar}
                  onAddDrawing={handleAddDrawing}
                  onNearLeftEdge={handleNearLeftEdge}
                />
                {isFetching && (
                  <div className="absolute top-2 left-1/2 -translate-x-1/2 z-20 pointer-events-none">
                    <div className="flex items-center gap-1.5 text-[10px] text-[var(--text-tertiary)] bg-[var(--bg-elevated)]/90 border border-[var(--border-subtle)] px-2.5 py-1 rounded-full backdrop-blur-sm">
                      <span className="w-1.5 h-1.5 rounded-full bg-[var(--text-tertiary)] animate-pulse" />
                      Loading…
                    </div>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Sub-panes — only shown in pro mode */}
          {showSubPanes && (
            <>
              {hasRsi && !isLoading && (
                <RsiChart bars={bars} values={indicators.RSI_14} height={100} />
              )}
              {hasMacd && !isLoading && (
                <MacdChart
                  bars={bars}
                  macdLine={indicators.MACD_line}
                  macdSignal={indicators.MACD_signal ?? []}
                  macdHist={indicators.MACD_hist ?? []}
                  height={100}
                />
              )}
              {hasStoch && !isLoading && (
                <OscillatorPane
                  bars={bars}
                  line1={indicators.STOCH_k}
                  color1="#f97316"
                  label1="%K"
                  line2={indicators.STOCH_d}
                  color2="#3b82f6"
                  label2="%D"
                  levels={[{ price: 80, color: "#787b86" }, { price: 20, color: "#787b86" }]}
                  title="Stochastic (14,3,3)"
                  height={100}
                  explainTerm="Stochastic Oscillator"
                />
              )}
              {hasWillR && !isLoading && (
                <OscillatorPane
                  bars={bars}
                  line1={indicators.WILLR}
                  color1="#14b8a6"
                  label1="%R"
                  levels={[{ price: -20, color: "#787b86" }, { price: -80, color: "#787b86" }]}
                  title="Williams %R (14)"
                  height={100}
                />
              )}
              {hasCci && !isLoading && (
                <OscillatorPane
                  bars={bars}
                  line1={indicators.CCI}
                  color1="#e879f9"
                  levels={[{ price: 100, color: "#787b86" }, { price: -100, color: "#787b86" }]}
                  title="CCI (20)"
                  height={100}
                />
              )}
              {hasObv && !isLoading && (
                <OscillatorPane
                  bars={bars}
                  line1={indicators.OBV}
                  color1="#fbbf24"
                  title="OBV"
                  height={100}
                />
              )}
              {hasAtr && !isLoading && (
                <OscillatorPane
                  bars={bars}
                  line1={indicators.ATR}
                  color1="#64748b"
                  title="ATR (14)"
                  height={100}
                />
              )}
              {hasAdx && !isLoading && (
                <OscillatorPane
                  bars={bars}
                  line1={indicators.ADX}
                  color1="#fbbf24"
                  label1="ADX"
                  line2={indicators.ADX_pos}
                  color2="#22c55e"
                  label2="+DI"
                  levels={[{ price: 25, color: "#787b86" }]}
                  title="ADX (14)"
                  height={100}
                  explainTerm="ADX (Average Directional Index)"
                />
              )}
              {hasCmf && !isLoading && (
                <OscillatorPane
                  bars={bars}
                  line1={indicators.CMF}
                  color1="#06b6d4"
                  levels={[{ price: 0, color: "#787b86" }]}
                  title="CMF (20)"
                  height={100}
                />
              )}
              {hasMfi && !isLoading && (
                <OscillatorPane
                  bars={bars}
                  line1={indicators.MFI}
                  color1="#a78bfa"
                  levels={[{ price: 80, color: "#787b86" }, { price: 20, color: "#787b86" }]}
                  title="MFI (14)"
                  height={100}
                />
              )}
              {hasRoc && !isLoading && (
                <OscillatorPane
                  bars={bars}
                  line1={indicators.ROC}
                  color1="#fb923c"
                  levels={[{ price: 0, color: "#787b86" }]}
                  title="ROC (12)"
                  height={100}
                />
              )}
            </>
          )}
        </div>

        {/* Right watchlist */}
        {showWatchlist ? (
          <WatchlistPanel
            activeSymbol={symbol}
            onSymbolClick={handleSymbolChange}
            onClose={() => setShowWatchlist(false)}
          />
        ) : (
          <button
            onClick={() => setShowWatchlist(true)}
            title="Show watchlist"
            className="w-8 shrink-0 flex flex-col items-center justify-center border-l border-[var(--border-subtle)] bg-[var(--bg-base)] hover:bg-[var(--bg-elevated)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors gap-1"
          >
            <LayoutList size={14} />
          </button>
        )}
      </div>

      {/* Bottom bar — period selector + status */}
      <TvBottomBar
        period={period}
        onPeriodChange={(p) => { setPeriod(p); setUserPickedPeriod(true); }}
        symbol={symbol}
        displayPrice={displayBar?.close}
        displayVolume={displayBar?.volume}
        drawingCount={drawings.length}
      />

      {/* Indicators modal */}
      {showIndicatorsModal && (
        <IndicatorsModal
          active={activeIndicators}
          onChange={setActiveIndicators}
          onClose={() => setShowIndicatorsModal(false)}
        />
      )}

      {/* Order ticket modal */}
      {showOrderTicket && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--bg-base)]/80 backdrop-blur-sm">
          <div className="w-96">
            <OrderTicket symbol={symbol} onClose={() => setShowOrderTicket(false)} />
          </div>
        </div>
      )}

      <PaywallSheet
        open={showProPaywall}
        onClose={() => setShowProPaywall(false)}
        requiredTier="plus"
        featureLabel="Pro Mode"
        featureDescription="Sub-pane indicators, drawing tools, and advanced chart analysis require Plus or Premium."
      />

      {/* AI chart analysis drawer */}
      <AskAIDrawer
        open={aiDrawerOpen}
        onClose={() => setAiDrawerOpen(false)}
        title={`BMG Analysis — ${symbol}`}
        context={`Chart analysis for ${symbol}. User is viewing a price chart.`}
        suggestedQuestions={[
          `What's the current trend for ${symbol}?`,
          `What are key support and resistance levels?`,
          `Is ${symbol} overbought or oversold right now?`,
          `What does the recent price action suggest?`,
          `What catalysts could move ${symbol} in the next 30 days?`,
        ]}
      />
    </div>
  );
}

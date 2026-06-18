import { useEffect, useRef, useState, useMemo } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, Save, Zap, Trash2, Plus, X } from "lucide-react";
import { createChart, CandlestickSeries, LineSeries, ColorType, LineStyle } from "lightweight-charts";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import { fetchBars } from "@/api/bars";
import { createSetup, deleteSetup, getSetups } from "@/api/scout";
import { getStrategyDescription } from "@/api/candidates";
import client from "@/api/client";
import { cn } from "@/lib/utils";

// ── Strategy → indicator config ───────────────────────────────────────────────

interface IndicatorConfig {
  type: "SMA" | "EMA" | "RSI" | "BBANDS";
  period: number;
  color: string;
  label: string;
}

interface StrategyChartConfig {
  indicators: IndicatorConfig[];
  triggerDescription: string;
  apiIndicators: string; // comma-sep keys for fetchBars
}

const STRATEGY_CHART_CONFIG: Record<string, StrategyChartConfig> = {
  golden_cross: {
    indicators: [
      { type: "SMA", period: 50,  color: "#a78bfa", label: "50d MA" },
      { type: "SMA", period: 200, color: "#fb923c", label: "200d MA" },
    ],
    triggerDescription: "50d MA crosses above 200d MA",
    apiIndicators: "SMA_50,SMA_200",
  },
  momentum_breakout: {
    indicators: [
      { type: "SMA", period: 20, color: "#a78bfa", label: "20d MA" },
      { type: "SMA", period: 50, color: "#fb923c", label: "50d MA" },
    ],
    triggerDescription: "Price breaks above 20d resistance with volume",
    apiIndicators: "SMA_20,SMA_50",
  },
  rsi2_mean_reversion: {
    indicators: [
      { type: "SMA", period: 200, color: "#fb923c", label: "200d MA" },
    ],
    triggerDescription: "RSI(2) drops below 10 while above 200d MA",
    apiIndicators: "SMA_200,RSI_2",
  },
  macd_crossover: {
    indicators: [
      { type: "SMA", period: 12, color: "#4ade80", label: "12d EMA" },
      { type: "SMA", period: 26, color: "#f87171", label: "26d EMA" },
    ],
    triggerDescription: "MACD line crosses above signal line",
    apiIndicators: "SMA_12,SMA_26",
  },
  bollinger_squeeze: {
    indicators: [
      { type: "SMA", period: 20, color: "#a78bfa", label: "20d MA" },
    ],
    triggerDescription: "Bollinger band width contracts then breaks out",
    apiIndicators: "SMA_20",
  },
  fifty_two_week_high_momentum: {
    indicators: [
      { type: "SMA", period: 50,  color: "#a78bfa", label: "50d MA" },
      { type: "SMA", period: 200, color: "#fb923c", label: "200d MA" },
    ],
    triggerDescription: "Price near 52-week high with momentum",
    apiIndicators: "SMA_50,SMA_200",
  },
  options_iron_condor_spy: {
    indicators: [
      { type: "SMA", period: 20, color: "#a78bfa", label: "20d MA" },
      { type: "SMA", period: 50, color: "#fb923c", label: "50d MA" },
    ],
    triggerDescription: "ATR contracting + IVR > 30",
    apiIndicators: "SMA_20,SMA_50",
  },
  crypto_quant_mean_reversion: {
    indicators: [
      { type: "SMA", period: 21, color: "#4ade80", label: "21d MA" },
    ],
    triggerDescription: "21-day z-score < -2.0 (price below lower band)",
    apiIndicators: "SMA_21",
  },
  cross_sectional_momentum: {
    indicators: [
      { type: "SMA", period: 50,  color: "#a78bfa", label: "50d MA" },
      { type: "SMA", period: 200, color: "#fb923c", label: "200d MA" },
    ],
    triggerDescription: "Top 20% ranked by 12-1M return",
    apiIndicators: "SMA_50,SMA_200",
  },
};

const DEFAULT_CONFIG: StrategyChartConfig = {
  indicators: [
    { type: "SMA", period: 50,  color: "#a78bfa", label: "50d MA" },
    { type: "SMA", period: 200, color: "#fb923c", label: "200d MA" },
  ],
  triggerDescription: "Setup conditions met per strategy definition",
  apiIndicators: "SMA_50,SMA_200",
};

function getConfig(strategyId: string): StrategyChartConfig {
  return STRATEGY_CHART_CONFIG[strategyId] ?? DEFAULT_CONFIG;
}

// ── Drawing types ─────────────────────────────────────────────────────────────

interface HorizontalDrawing {
  id: string;
  type: "horizontal";
  price: number;
  color: string;
  label: string;
}
type Drawing = HorizontalDrawing;

// ── Chart component ───────────────────────────────────────────────────────────

interface OHLCBar {
  time: UTCTimestamp;
  open: number; high: number; low: number; close: number;
}

function ScoutPriceChart({
  bars,
  indicators,
  indicatorConfigs,
  crossoverMarkers,
  drawings,
}: {
  bars: OHLCBar[];
  indicators: Record<string, (number | null)[]>;
  indicatorConfigs: IndicatorConfig[];
  crossoverMarkers: { time: UTCTimestamp; direction: "up" | "down" }[];
  drawings: Drawing[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || bars.length === 0) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#050805" },
        textColor: "#7e8e7e",
      },
      grid: {
        vertLines: { color: "rgba(74,222,128,0.06)" },
        horzLines: { color: "rgba(74,222,128,0.06)" },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: "rgba(74,222,128,0.15)" },
      timeScale: { borderColor: "rgba(74,222,128,0.15)", timeVisible: true },
      width: containerRef.current.clientWidth,
      height: 340,
    });
    chartRef.current = chart;

    const priceSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#4ade80",
      downColor: "#f87171",
      borderVisible: false,
      wickUpColor: "#4ade80",
      wickDownColor: "#f87171",
    });
    priceSeries.setData(bars);

    // Horizontal price-level drawings
    drawings.forEach((d) => {
      if (d.type === "horizontal") {
        priceSeries.createPriceLine({
          price: d.price,
          color: d.color,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          title: d.label,
          axisLabelVisible: true,
        });
      }
    });

    // Indicator lines
    indicatorConfigs.forEach((cfg) => {
      const key = `${cfg.type}_${cfg.period}`;
      const values = indicators[key];
      if (!values) return;
      const lineSeries = chart.addSeries(LineSeries, {
        color: cfg.color,
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
        title: cfg.label,
      });
      const lineData = bars
        .map((b, i) => ({ time: b.time, value: values[i] }))
        .filter((d) => d.value != null) as { time: UTCTimestamp; value: number }[];
      lineSeries.setData(lineData);
    });

    // Crossover markers
    if (crossoverMarkers.length > 0) {
      const markerSeries = chart.addSeries(LineSeries, { visible: false, priceLineVisible: false });
      markerSeries.setData(bars.map((b) => ({ time: b.time, value: b.close })));
      try {
        (markerSeries as any).setMarkers(crossoverMarkers.map((m) => ({
          time: m.time,
          position: m.direction === "up" ? "belowBar" : "aboveBar",
          color: m.direction === "up" ? "#4ade80" : "#f87171",
          shape: m.direction === "up" ? "arrowUp" : "arrowDown",
          size: 1,
        })));
      } catch {}
    }

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, indicators, indicatorConfigs, crossoverMarkers, drawings]);

  return <div ref={containerRef} className="w-full" style={{ height: 340 }} />;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function computeCrossovers(
  bars: OHLCBar[],
  indicators: Record<string, (number | null)[]>,
  cfg: StrategyChartConfig
) {
  // Only works for two-SMA golden/death cross pattern
  const smaKeys = cfg.indicators.filter(i => i.type === "SMA").map(i => `SMA_${i.period}`);
  if (smaKeys.length < 2) return [];
  const [fastKey, slowKey] = smaKeys;
  const fast = indicators[fastKey];
  const slow = indicators[slowKey];
  if (!fast || !slow) return [];

  const crossovers: { time: UTCTimestamp; direction: "up" | "down"; barIndex: number }[] = [];
  for (let i = 1; i < bars.length; i++) {
    const fPrev = fast[i - 1], sPrev = slow[i - 1];
    const fCurr = fast[i],     sCurr = slow[i];
    if (fPrev == null || sPrev == null || fCurr == null || sCurr == null) continue;
    if (fPrev <= sPrev && fCurr > sCurr) {
      crossovers.push({ time: bars[i].time, direction: "up", barIndex: i });
    } else if (fPrev >= sPrev && fCurr < sCurr) {
      crossovers.push({ time: bars[i].time, direction: "down", barIndex: i });
    }
  }
  return crossovers;
}

function fmtDate(ts: UTCTimestamp): string {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

function fmtPct(v: number): string {
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

// ── Drawing toolbar ───────────────────────────────────────────────────────────

const DRAWING_COLORS = ["#f59e0b", "#a78bfa", "#4ade80", "#f87171", "#38bdf8", "#fb923c"];

function DrawingToolbar({
  drawings,
  onAdd,
  onRemove,
}: {
  drawings: Drawing[];
  onAdd: (d: Drawing) => void;
  onRemove: (id: string) => void;
}) {
  const [price, setPrice] = useState("");
  const [label, setLabel] = useState("");
  const [color, setColor] = useState(DRAWING_COLORS[0]);

  function handleAdd() {
    const p = parseFloat(price);
    if (isNaN(p) || p <= 0) return;
    onAdd({
      id: Math.random().toString(36).slice(2),
      type: "horizontal",
      price: p,
      color,
      label: label.trim() || `$${p.toFixed(2)}`,
    });
    setPrice("");
    setLabel("");
  }

  return (
    <div className="bg-t-bg1 border border-t-dim rounded-2xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-mono-t text-t-faint uppercase tracking-widest">// PRICE LEVELS</span>
        {drawings.length > 0 && (
          <span className="text-[10px] font-mono-t text-t-gdim">{drawings.length} level{drawings.length !== 1 ? "s" : ""} saved</span>
        )}
      </div>

      {/* Add row */}
      <div className="flex items-center gap-2 flex-wrap">
        <input
          type="number"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          placeholder="Price level"
          className="w-28 bg-t-bg0 border border-t-dim rounded-lg px-3 py-1.5 text-xs text-t-hi font-mono-t outline-none focus:border-t-mid"
        />
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          placeholder="Label (e.g. Support)"
          className="flex-1 min-w-24 bg-t-bg0 border border-t-dim rounded-lg px-3 py-1.5 text-xs text-t-hi font-mono-t outline-none focus:border-t-mid"
        />
        <div className="flex gap-1 shrink-0">
          {DRAWING_COLORS.map((c) => (
            <button
              key={c}
              onClick={() => setColor(c)}
              className={cn("w-4 h-4 rounded-full border-2 transition-all", color === c ? "border-white scale-110" : "border-transparent")}
              style={{ background: c }}
            />
          ))}
        </div>
        <button
          onClick={handleAdd}
          disabled={!price || isNaN(parseFloat(price))}
          className="flex items-center gap-1 px-3 py-1.5 text-xs font-mono-t text-t-bg0 bg-t-amber rounded-lg font-bold disabled:opacity-40 shrink-0"
        >
          <Plus size={12} /> Add
        </button>
      </div>

      {/* Existing levels */}
      {drawings.length > 0 && (
        <div className="space-y-1 pt-1 border-t border-t-dim/40">
          {drawings.map((d) => (
            <div key={d.id} className="flex items-center gap-2 text-xs font-mono-t group">
              <div className="w-3 h-0.5 shrink-0 rounded" style={{ background: d.color }} />
              <span className="text-t-body flex-1 truncate">{d.label}</span>
              <span className="text-t-gdim tabular-nums">${d.price.toFixed(2)}</span>
              <button
                onClick={() => onRemove(d.id)}
                className="opacity-0 group-hover:opacity-100 transition-opacity text-t-muted hover:text-t-red"
              >
                <X size={11} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Save to Workshop modal ────────────────────────────────────────────────────

function SaveModal({
  ticker,
  strategyId,
  onClose,
  onSave,
}: {
  ticker: string;
  strategyId: string;
  onClose: () => void;
  onSave: (name: string, notes: string) => void;
}) {
  const [name, setName] = useState(`${ticker} × ${strategyId.replace(/_/g, " ")}`);
  const [notes, setNotes] = useState("");

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-t-bg1 border border-t-mid rounded-2xl p-6 w-full max-w-md space-y-4">
        <h2 className="text-t-hi font-semibold font-ui-t">Save to Workshop</h2>
        <div className="space-y-3">
          <div>
            <label className="text-[11px] text-t-gdim font-mono-t uppercase tracking-widest block mb-1">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full bg-t-bg0 border border-t-dim rounded-lg px-3 py-2 text-sm text-t-hi font-mono-t outline-none focus:border-t-mid"
            />
          </div>
          <div>
            <label className="text-[11px] text-t-gdim font-mono-t uppercase tracking-widest block mb-1">Notes (optional)</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Setup notes, entry thesis, risk levels..."
              className="w-full bg-t-bg0 border border-t-dim rounded-lg px-3 py-2 text-sm text-t-hi font-mono-t outline-none focus:border-t-mid resize-none"
            />
          </div>
        </div>
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm font-mono-t text-t-muted border border-t-dim rounded-lg hover:border-t-mid">
            Cancel
          </button>
          <button
            onClick={() => onSave(name.trim() || `${ticker} × ${strategyId}`, notes)}
            disabled={!name.trim()}
            className="px-4 py-2 text-sm font-mono-t text-t-bg0 bg-t-green rounded-lg font-bold disabled:opacity-40"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ScoutChartPage() {
  const { ticker: rawTicker, strategyId } = useParams<{ ticker: string; strategyId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [searchParams] = useSearchParams();
  const [drawings, setDrawings] = useState<Drawing[]>([]);

  const ticker = (rawTicker ?? "").toUpperCase();
  const sid = strategyId ?? "";
  const cfg = getConfig(sid);

  // Fetch description for display name
  const { data: descData } = useQuery({
    queryKey: ["strategy-desc", sid],
    queryFn: () => getStrategyDescription(sid),
    staleTime: Infinity,
    retry: 1,
  });

  // Fetch bars with indicators
  const { data: barsData, isLoading: barsLoading, isError: barsError } = useQuery({
    queryKey: ["scout-chart-bars", ticker, cfg.apiIndicators],
    queryFn: () => fetchBars(ticker, "1Day", cfg.apiIndicators, undefined, 365),
    staleTime: 300_000,
    enabled: !!ticker,
  });

  const bars: OHLCBar[] = useMemo(() => {
    if (!barsData?.bars) return [];
    return barsData.bars.map((b: any) => ({
      time: Math.floor(new Date(b.t ?? b.time ?? b.timestamp).getTime() / 1000) as UTCTimestamp,
      open: b.o ?? b.open,
      high: b.h ?? b.high,
      low: b.l ?? b.low,
      close: b.c ?? b.close,
    }));
  }, [barsData]);

  const indicators = barsData?.indicators ?? {};

  const crossovers = useMemo(() => computeCrossovers(bars, indicators, cfg), [bars, indicators, cfg]);

  // Load saved price-level drawings
  const { data: savedDrawings } = useQuery<Drawing[]>({
    queryKey: ["chart-drawings", ticker, "1D"],
    queryFn: () =>
      client
        .get<{ drawings: Drawing[] }>("/chart-drawings", { params: { symbol: ticker, timeframe: "1D" } })
        .then((r) => r.data.drawings ?? []),
    enabled: !!ticker,
    staleTime: 60_000,
  });
  // Sync server drawings into local state (only on initial load)
  const drawingsInitialized = useRef(false);
  useEffect(() => {
    if (!drawingsInitialized.current && savedDrawings && savedDrawings.length > 0) {
      drawingsInitialized.current = true;
      setDrawings(savedDrawings);
    }
  }, [savedDrawings]);

  const saveDrawingsMutation = useMutation({
    mutationFn: (ds: Drawing[]) =>
      client.put("/chart-drawings", { symbol: ticker, timeframe: "1D", drawings: ds }),
  });

  function handleAddDrawing(d: Drawing) {
    const next = [...drawings, d];
    setDrawings(next);
    saveDrawingsMutation.mutate(next);
  }

  function handleRemoveDrawing(id: string) {
    const next = drawings.filter((d) => d.id !== id);
    setDrawings(next);
    saveDrawingsMutation.mutate(next);
  }

  // Find current setup status
  const currentStatus = useMemo(() => {
    const smaKeys = cfg.indicators.filter(i => i.type === "SMA").map(i => `SMA_${i.period}`);
    if (smaKeys.length < 2 || !bars.length) return null;
    const [fastKey, slowKey] = smaKeys;
    const fastArr = indicators[fastKey];
    const slowArr = indicators[slowKey];
    if (!fastArr || !slowArr) return null;
    const last = bars.length - 1;
    const fastVal = fastArr[last];
    const slowVal = slowArr[last];
    const currentPrice = bars[last]?.close;
    if (fastVal == null || slowVal == null) return null;
    const gap = fastVal - slowVal;
    const isActive = gap > 0;
    // Find when last upward cross happened
    const lastUp = [...crossovers].reverse().find(c => c.direction === "up");
    const daysSince = lastUp ? Math.round((Date.now() - lastUp.time * 1000) / 86400000) : null;
    return {
      fastVal, slowVal, gap, isActive, currentPrice,
      fastLabel: cfg.indicators.find(i => i.type === "SMA")?.label ?? "Fast MA",
      slowLabel: cfg.indicators.filter(i => i.type === "SMA")[1]?.label ?? "Slow MA",
      crossedAt: lastUp ? fmtDate(lastUp.time) : null,
      daysSince,
      status: isActive ? "ACTIVE" : "WAITING",
    };
  }, [bars, indicators, cfg, crossovers]);

  // Past trigger performance (last 5 upward crossovers with forward return)
  const pastTriggers = useMemo(() => {
    return crossovers
      .filter(c => c.direction === "up")
      .slice(-5)
      .map((c) => {
        const entryPrice = bars[c.barIndex]?.close;
        const exitBarIdx = Math.min(c.barIndex + 60, bars.length - 1);
        const exitPrice = bars[exitBarIdx]?.close;
        const fwd = entryPrice && exitPrice ? (exitPrice - entryPrice) / entryPrice : null;
        return {
          date: fmtDate(c.time),
          forwardReturn: fwd,
          daysHeld: Math.min(60, bars.length - 1 - c.barIndex),
        };
      })
      .reverse();
  }, [crossovers, bars]);

  // Find existing setup for this pairing
  const { data: setupsData } = useQuery({
    queryKey: ["scout-setups"],
    queryFn: getSetups,
    staleTime: 30_000,
  });
  const existingSetup = setupsData?.setups.find(
    s => s.ticker === ticker && s.strategy_id === sid
  );

  // ARM mutation
  const armMutation = useMutation({
    mutationFn: () => createSetup(ticker, sid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scout-setups"] });
      toast.success(`Armed ${ticker} × ${sid}`);
    },
  });

  // DISARM mutation
  const disarmMutation = useMutation({
    mutationFn: () => deleteSetup(existingSetup!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scout-setups"] });
      toast.success(`Disarmed ${ticker} × ${sid}`);
    },
  });

  // Save to Workshop mutation (calls new strategy-workshop endpoint)
  const saveMutation = useMutation({
    mutationFn: ({ name, notes }: { name: string; notes: string }) =>
      client.post("/strategy-workshop/charts", { ticker, strategy_id: sid, name, notes }).then(r => r.data),
    onSuccess: () => {
      setShowSaveModal(false);
      toast.success("Saved to Workshop");
      navigate("/strategy/workshop");
    },
    onError: () => toast.error("Save failed — try again"),
  });

  const displayName = descData?.display_name ?? sid.replace(/_/g, " ");
  const statusColor = currentStatus?.status === "ACTIVE" ? "text-t-green border-t-green/40 bg-t-green/10"
    : "text-t-amber border-t-amber/40 bg-t-amber/10";

  return (
    <div className="min-h-screen bg-t-bg0 text-t-hi">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-6 space-y-5">

        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-[11px] font-mono-t text-t-faint">
          <button onClick={() => navigate("/strategy/scout")} className="hover:text-t-mid flex items-center gap-1">
            <ArrowLeft size={12} /> Strategy Lab
          </button>
          <span>/</span><span>Scout</span><span>/</span>
          <span className="text-t-violet">{ticker} × {displayName}</span>
        </div>

        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl font-bold font-ui-t text-t-hi">{ticker} — {displayName}</h1>
              {currentStatus && (
                <span className={cn("text-[11px] font-mono-t font-bold px-2 py-0.5 rounded border", statusColor)}>
                  {currentStatus.status}
                </span>
              )}
            </div>
            {currentStatus && (
              <p className="text-xs text-t-muted font-mono-t mt-1">
                Last price: ${currentStatus.currentPrice?.toFixed(2) ?? "—"}
                {" · "}
                {currentStatus.fastLabel}: ${currentStatus.fastVal?.toFixed(2) ?? "—"}
                {" · "}
                {currentStatus.slowLabel}: ${currentStatus.slowVal?.toFixed(2) ?? "—"}
              </p>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex gap-2 flex-wrap">
            {!existingSetup ? (
              <button
                onClick={() => armMutation.mutate()}
                disabled={armMutation.isPending}
                className="flex items-center gap-1.5 px-4 py-2 text-sm font-mono-t font-bold text-t-bg0 bg-t-green rounded-lg hover:bg-t-green/80 disabled:opacity-50"
              >
                <Zap size={14} /> ARM
              </button>
            ) : (
              <button
                onClick={() => disarmMutation.mutate()}
                disabled={disarmMutation.isPending}
                className="flex items-center gap-1.5 px-4 py-2 text-sm font-mono-t text-t-red border border-t-red/30 rounded-lg hover:bg-t-red/10"
              >
                <Trash2 size={14} /> Disarm
              </button>
            )}
            <button
              onClick={() => setShowSaveModal(true)}
              className="flex items-center gap-1.5 px-4 py-2 text-sm font-mono-t text-t-violet border border-t-violet/30 rounded-lg hover:bg-t-violet/10"
            >
              <Save size={14} /> Save to Workshop
            </button>
          </div>
        </div>

        {/* Chart */}
        <div className="bg-t-bg1 border border-t-dim rounded-2xl p-4 space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-[10px] font-mono-t text-t-faint uppercase tracking-widest">// PRICE CHART — 1Y DAILY</span>
            <div className="flex gap-3 flex-wrap">
              {cfg.indicators.map((ind) => (
                <div key={`${ind.type}_${ind.period}`} className="flex items-center gap-1.5">
                  <div className="w-4 h-0.5 rounded" style={{ background: ind.color }} />
                  <span className="text-[10px] font-mono-t text-t-muted">{ind.label}</span>
                </div>
              ))}
              {crossovers.length > 0 && (
                <>
                  <div className="flex items-center gap-1"><span className="text-t-green text-xs">▲</span><span className="text-[10px] font-mono-t text-t-muted">Cross up</span></div>
                  <div className="flex items-center gap-1"><span className="text-t-red text-xs">▼</span><span className="text-[10px] font-mono-t text-t-muted">Cross down</span></div>
                </>
              )}
            </div>
          </div>
          {barsLoading ? (
            <div className="h-[340px] bg-t-bg0 rounded-xl animate-pulse" />
          ) : barsError || bars.length === 0 ? (
            <div className="h-[340px] bg-t-bg0 rounded-xl flex items-center justify-center text-t-muted text-sm font-mono-t">
              Chart data unavailable for {ticker}
            </div>
          ) : (
            <ScoutPriceChart
              bars={bars}
              indicators={indicators}
              indicatorConfigs={cfg.indicators}
              crossoverMarkers={crossovers.map(c => ({ time: c.time, direction: c.direction }))}
              drawings={drawings}
            />
          )}

          {/* Price level annotations — lives inside chart card so it's always in-frame */}
          <DrawingToolbar
            drawings={drawings}
            onAdd={handleAddDrawing}
            onRemove={handleRemoveDrawing}
          />
        </div>

        {/* Setup status */}
        {currentStatus && (
          <div className="bg-t-bg1 border border-t-dim rounded-2xl p-5 space-y-3">
            <span className="text-[10px] font-mono-t text-t-faint uppercase tracking-widest">// SETUP STATUS</span>
            <div className="space-y-1.5 text-sm font-mono-t">
              <div className="flex items-baseline gap-2">
                <span className="text-t-gdim">Trigger:</span>
                <span className="text-t-body">{cfg.triggerDescription}</span>
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-t-gdim">Current gap:</span>
                <span className={currentStatus.gap > 0 ? "text-t-green" : "text-t-red"}>
                  {currentStatus.fastLabel} is ${Math.abs(currentStatus.gap).toFixed(2)}{" "}
                  {currentStatus.gap > 0 ? "above" : "below"} {currentStatus.slowLabel}
                </span>
              </div>
              {currentStatus.crossedAt && (
                <div className="flex items-baseline gap-2">
                  <span className="text-t-green">✓</span>
                  <span className="text-t-body">
                    {currentStatus.status === "ACTIVE"
                      ? `Crossed ${currentStatus.daysSince ?? "?"} days ago (${currentStatus.crossedAt}) — setup ACTIVE`
                      : `Last cross: ${currentStatus.crossedAt}`}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Past triggers */}
        {pastTriggers.length > 0 && (
          <div className="bg-t-bg1 border border-t-dim rounded-2xl p-5 space-y-3">
            <span className="text-[10px] font-mono-t text-t-faint uppercase tracking-widest">// PAST TRIGGERS ON {ticker}</span>
            <table className="w-full text-xs font-mono-t">
              <thead>
                <tr className="text-t-gdim border-b border-t-dim/50">
                  <th className="text-left pb-2 font-medium">Date</th>
                  <th className="text-left pb-2 font-medium">Side</th>
                  <th className="text-right pb-2 font-medium">60-day fwd</th>
                  <th className="text-right pb-2 font-medium">Days</th>
                </tr>
              </thead>
              <tbody>
                {pastTriggers.map((t, i) => (
                  <tr key={i} className="border-b border-t-dim/30 last:border-0">
                    <td className="py-1.5 text-t-body">{t.date}</td>
                    <td className="py-1.5 text-t-green">Cross UP</td>
                    <td className={cn("py-1.5 text-right", t.forwardReturn == null ? "text-t-muted" : t.forwardReturn >= 0 ? "text-t-green" : "text-t-red")}>
                      {t.forwardReturn != null ? fmtPct(t.forwardReturn) : "—"}
                    </td>
                    <td className="py-1.5 text-right text-t-muted">{t.daysHeld}d</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showSaveModal && (
        <SaveModal
          ticker={ticker}
          strategyId={sid}
          onClose={() => setShowSaveModal(false)}
          onSave={(name, notes) => saveMutation.mutate({ name, notes })}
        />
      )}
    </div>
  );
}

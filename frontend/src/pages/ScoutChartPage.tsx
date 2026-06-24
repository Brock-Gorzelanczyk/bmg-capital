import { useEffect, useRef, useState, useMemo } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, Save, Zap, Trash2, Plus, X, Bell } from "lucide-react";
import { createChart, CandlestickSeries, LineSeries, ColorType, LineStyle } from "lightweight-charts";
import type { IChartApi, UTCTimestamp } from "lightweight-charts";
import { fetchBars } from "@/api/bars";
import { createSetup, deleteSetup, getSetups } from "@/api/scout";
import { getStrategyDescription, getStrategyIndicators } from "@/api/candidates";
import type { ScoutIndicatorSpec, ScoutTimeframe } from "@/api/candidates";
import client from "@/api/client";
import { cn } from "@/lib/utils";
import SetupChecklist from "@/components/SetupChecklist";
import BacktestPanel from "@/components/BacktestPanel";

// ── Strategy → indicator config (server-driven via /strategy-lab/indicators) ─
// Each strategy declares its own overlay/subpanel set on the backend. We fetch
// the spec for the active strategy and dispatch each entry to a renderer below.
// This replaces the legacy hardcoded 50d/200d MA pair that was wrong for ~90%
// of strategies.

// ── Price alert types ─────────────────────────────────────────────────────────

interface PriceAlert {
  id: number;
  workshop_chart_id: number | null;
  ticker: string;
  price: number;
  direction: "above" | "below";
  message: string | null;
  status: "armed" | "triggered" | "cancelled" | "snoozed";
  notif_discord: boolean;
  notif_inapp: boolean;
  created_at: string;
  triggered_at: string | null;
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
  indicatorSpecs,
  crossoverMarkers,
  drawings,
}: {
  bars: OHLCBar[];
  indicators: Record<string, (number | null)[]>;
  indicatorSpecs: ScoutIndicatorSpec[];
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

    // Horizontal price-level drawings (user-added support/resistance lines)
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

    // ── Indicator dispatcher ────────────────────────────────────────────────
    // Each spec is rendered via its `type`. Anything not yet supported (or
    // missing data) is skipped silently so the chart never breaks.
    const addLine = (
      key: string,
      color: string,
      label: string,
      paneIndex = 0,
      lineWidth: 1 | 2 = 2,
      lineStyle: LineStyle = LineStyle.Solid,
    ) => {
      const values = indicators[key];
      if (!values || !values.length) return null;
      const opts: any = {
        color, lineWidth, lineStyle,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
        title: label,
      };
      // lightweight-charts ≥ 5.x supports pane indices via 3rd arg; we
      // fall back gracefully if the build doesn't.
      const lineSeries = paneIndex > 0
        ? (chart as any).addSeries(LineSeries, opts, paneIndex)
        : chart.addSeries(LineSeries, opts);
      const data = bars
        .map((b, i) => ({ time: b.time, value: values[i] }))
        .filter((d) => d.value != null) as { time: UTCTimestamp; value: number }[];
      lineSeries.setData(data);
      return lineSeries;
    };

    const renderPriorDayHighLow = (color: string, label: string) => {
      // Compute prior session H/L from `bars` — group by calendar date,
      // take the most recent COMPLETED day, draw horizontal price lines.
      if (bars.length < 2) return;
      const byDay = new Map<string, { high: number; low: number }>();
      for (const b of bars) {
        const day = new Date(b.time * 1000).toISOString().slice(0, 10);
        const cur = byDay.get(day);
        if (!cur) byDay.set(day, { high: b.high, low: b.low });
        else {
          cur.high = Math.max(cur.high, b.high);
          cur.low = Math.min(cur.low, b.low);
        }
      }
      const days = Array.from(byDay.keys()).sort();
      if (days.length < 2) return;
      const prior = byDay.get(days[days.length - 2]);
      if (!prior) return;
      priceSeries.createPriceLine({
        price: prior.high, color, lineWidth: 1, lineStyle: LineStyle.Dashed,
        title: `${label} (H)`, axisLabelVisible: true,
      });
      priceSeries.createPriceLine({
        price: prior.low, color, lineWidth: 1, lineStyle: LineStyle.Dashed,
        title: `${label} (L)`, axisLabelVisible: true,
      });
    };

    const renderOpeningRange = (minutes: number, color: string, label: string) => {
      // Find the first `minutes` worth of bars in the most recent session and
      // draw H/L horizontal lines. For daily bars this degrades to "today's
      // bar H/L"; for intraday bars it picks the first N min.
      if (!bars.length) return;
      const lastDay = new Date(bars[bars.length - 1].time * 1000).toISOString().slice(0, 10);
      const sessionBars = bars.filter(
        (b) => new Date(b.time * 1000).toISOString().slice(0, 10) === lastDay
      );
      if (!sessionBars.length) return;
      const startTs = sessionBars[0].time;
      const cutoff = startTs + minutes * 60;
      const orBars = sessionBars.filter((b) => b.time <= cutoff);
      if (!orBars.length) return;
      const high = Math.max(...orBars.map((b) => b.high));
      const low = Math.min(...orBars.map((b) => b.low));
      priceSeries.createPriceLine({
        price: high, color, lineWidth: 1, lineStyle: LineStyle.Dotted,
        title: `${label} H`, axisLabelVisible: true,
      });
      priceSeries.createPriceLine({
        price: low, color, lineWidth: 1, lineStyle: LineStyle.Dotted,
        title: `${label} L`, axisLabelVisible: true,
      });
    };

    indicatorSpecs.forEach((spec) => {
      const p = (spec.params ?? {}) as Record<string, any>;
      const pane = spec.panel === "subpanel_1" ? 1 : spec.panel === "subpanel_2" ? 2 : 0;
      switch (spec.type) {
        case "sma": {
          addLine(`SMA_${Number(p.period ?? 20)}`, spec.color, spec.label);
          break;
        }
        case "ema": {
          addLine(`EMA_${Number(p.period ?? 20)}`, spec.color, spec.label);
          break;
        }
        case "donchian": {
          const period = Number(p.period ?? 20);
          addLine(`DONCHIAN_${period}_upper`, spec.color, `${spec.label} ↑`, 0, 1);
          addLine(`DONCHIAN_${period}_lower`, spec.color, `${spec.label} ↓`, 0, 1);
          break;
        }
        case "bollinger": {
          const period = Number(p.period ?? 20);
          addLine(`BB_${period}_upper`, spec.color, `${spec.label} ↑`, 0, 1, LineStyle.Solid);
          addLine(`BB_${period}_middle`, spec.color, `${spec.label} mid`, 0, 1, LineStyle.Dotted);
          addLine(`BB_${period}_lower`, spec.color, `${spec.label} ↓`, 0, 1, LineStyle.Solid);
          break;
        }
        case "rsi": {
          const period = Number(p.period ?? 14);
          const series = addLine(`RSI_${period}`, spec.color, spec.label, pane);
          if (series) {
            const ob = Number(p.overbought ?? 70);
            const os = Number(p.oversold ?? 30);
            try {
              series.createPriceLine({ price: ob, color: "#f87171", lineWidth: 1, lineStyle: LineStyle.Dashed, title: String(ob), axisLabelVisible: true });
              series.createPriceLine({ price: os, color: "#4ade80", lineWidth: 1, lineStyle: LineStyle.Dashed, title: String(os), axisLabelVisible: true });
            } catch {}
          }
          break;
        }
        case "macd": {
          addLine("MACD_line", spec.color, "MACD", pane);
          addLine("MACD_signal", "#f87171", "Signal", pane, 1);
          // Histogram could be a histogram series; render as faint line for now.
          addLine("MACD_hist", "#7e8e7e", "Hist", pane, 1, LineStyle.Dotted);
          break;
        }
        case "vwap": {
          addLine("VWAP", spec.color, spec.label, 0, 2);
          break;
        }
        case "vwap_bands": {
          addLine("VWAP_UPPER", spec.color, "VWAP +σ", 0, 1, LineStyle.Dotted);
          addLine("VWAP_LOWER", spec.color, "VWAP −σ", 0, 1, LineStyle.Dotted);
          break;
        }
        case "atr": {
          const period = Number(p.period ?? 14);
          const key = period === 14 ? "ATR" : `ATR_${period}`;
          addLine(key, spec.color, spec.label, pane);
          break;
        }
        case "bb_bandwidth": {
          addLine("BBWIDTH", spec.color, spec.label, pane);
          break;
        }
        case "zscore": {
          const series = addLine("ZSCORE", spec.color, spec.label, pane);
          if (series) {
            try {
              series.createPriceLine({ price: 2, color: "#f87171", lineWidth: 1, lineStyle: LineStyle.Dashed, title: "+2σ", axisLabelVisible: true });
              series.createPriceLine({ price: -2, color: "#4ade80", lineWidth: 1, lineStyle: LineStyle.Dashed, title: "−2σ", axisLabelVisible: true });
            } catch {}
          }
          break;
        }
        case "prior_day_high_low": {
          renderPriorDayHighLow(spec.color, spec.label);
          break;
        }
        case "opening_range": {
          renderOpeningRange(Number(p.minutes ?? 15), spec.color, spec.label);
          break;
        }
        // Placeholders — the data feed isn't wired up yet. Render a dashed
        // zero-line in a dedicated subpanel so the user sees that the chart
        // KNOWS about this indicator (just doesn't have data yet). The
        // legend chip carries the "(coming soon)" suffix from the backend
        // spec; the visual stub here ensures the chart doesn't silently
        // fall back to the old 50/200 MA template.
        case "ofi":
        case "delta":
        case "relative_strength_vs_spy":
        case "session_markers": {
          try {
            const placeholderPane = pane > 0 ? pane : 2;
            const placeholder = (chart as any).addSeries(
              LineSeries,
              {
                color: spec.color,
                lineWidth: 1,
                lineStyle: LineStyle.Dotted,
                priceLineVisible: false,
                crosshairMarkerVisible: false,
                title: spec.label,
              },
              placeholderPane,
            );
            placeholder.setData(
              bars.map((b) => ({ time: b.time, value: 0 })),
            );
          } catch {
            /* lightweight-charts pane creation may fail on older builds */
          }
          break;
        }
        case "volume":
          // Volume gets its own treatment elsewhere; skip here.
          break;
        default:
          // Unknown type — render nothing rather than falling back to a
          // generic MA so we never silently lie about what's on the chart.
          break;
      }
    });

    // Crossover markers (still useful for two-SMA strategies)
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
  }, [bars, indicators, indicatorSpecs, crossoverMarkers, drawings]);

  return <div ref={containerRef} className="w-full" style={{ height: 340 }} />;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function computeCrossovers(
  bars: OHLCBar[],
  indicators: Record<string, (number | null)[]>,
  indicatorSpecs: ScoutIndicatorSpec[],
) {
  // Only meaningful for two-SMA golden/death-cross style strategies. For any
  // other spec set we return [] (the chart still renders, just without arrows).
  const smaPeriods = indicatorSpecs
    .filter((s) => s.type === "sma")
    .map((s) => Number((s.params as any)?.period))
    .filter((p) => Number.isFinite(p))
    .sort((a, b) => a - b);
  if (smaPeriods.length < 2) return [];
  const fastKey = `SMA_${smaPeriods[0]}`;
  const slowKey = `SMA_${smaPeriods[1]}`;
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

// ── Price alert modal ─────────────────────────────────────────────────────────

function AlertModal({
  drawing,
  currentPrice,
  ticker,
  existingAlert,
  onClose,
  onSave,
  onCancel,
}: {
  drawing: Drawing;
  currentPrice: number | null;
  ticker: string;
  existingAlert: PriceAlert | null;
  onClose: () => void;
  onSave: (direction: "above" | "below", message: string, notifDiscord: boolean) => void;
  onCancel: (alertId: number) => void;
}) {
  const defaultDir: "above" | "below" =
    currentPrice != null && drawing.price > currentPrice ? "above" : "below";
  const [direction, setDirection] = useState<"above" | "below">(existingAlert?.direction ?? defaultDir);
  const [message, setMessage] = useState(existingAlert?.message ?? "");
  const [notifDiscord, setNotifDiscord] = useState(existingAlert?.notif_discord ?? true);

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-t-bg1 border border-t-mid rounded-2xl p-6 w-full max-w-sm space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div>
          <h3 className="text-t-hi font-semibold font-ui-t text-sm">Set Price Alert</h3>
          <p className="text-[11px] text-t-muted font-mono-t mt-0.5">
            {ticker} · ${drawing.price.toFixed(2)} · {drawing.label}
          </p>
        </div>

        {/* Direction */}
        <div className="space-y-1">
          <p className="text-[11px] text-t-gdim font-mono-t uppercase tracking-widest">Alert when price goes</p>
          <div className="flex gap-2">
            {(["above", "below"] as const).map((d) => (
              <button
                key={d}
                onClick={() => setDirection(d)}
                className={cn(
                  "flex-1 py-1.5 text-xs font-mono-t rounded-lg border transition-all",
                  direction === d
                    ? "border-t-amber bg-t-amber/10 text-t-amber font-bold"
                    : "border-t-dim text-t-muted hover:border-t-mid"
                )}
              >
                {d.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        {/* Message */}
        <div className="space-y-1">
          <p className="text-[11px] text-t-gdim font-mono-t uppercase tracking-widest">Note (optional)</p>
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder={`e.g. ${ticker} entry zone hit`}
            className="w-full bg-t-bg0 border border-t-dim rounded-lg px-3 py-2 text-xs text-t-hi font-mono-t outline-none focus:border-t-mid"
          />
        </div>

        {/* Discord toggle */}
        <label className="flex items-center gap-2.5 cursor-pointer">
          <div
            onClick={() => setNotifDiscord((v) => !v)}
            className={cn(
              "w-8 h-4 rounded-full transition-colors relative cursor-pointer",
              notifDiscord ? "bg-t-amber" : "bg-t-dim"
            )}
          >
            <div className={cn(
              "absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform",
              notifDiscord ? "translate-x-4" : "translate-x-0.5"
            )} />
          </div>
          <span className="text-xs font-mono-t text-t-body">Post to #price-alerts on Discord</span>
        </label>

        {/* Actions */}
        <div className="flex gap-2 justify-between pt-1">
          {existingAlert ? (
            <button
              onClick={() => onCancel(existingAlert.id)}
              className="text-xs font-mono-t text-t-red border border-t-red/30 rounded-lg px-3 py-1.5 hover:bg-t-red/10"
            >
              Disarm alert
            </button>
          ) : (
            <div />
          )}
          <div className="flex gap-2">
            <button onClick={onClose} className="text-xs font-mono-t text-t-muted border border-t-dim rounded-lg px-3 py-1.5 hover:border-t-mid">
              Cancel
            </button>
            <button
              onClick={() => onSave(direction, message, notifDiscord)}
              className="text-xs font-mono-t text-t-bg0 bg-t-amber rounded-lg px-4 py-1.5 font-bold hover:bg-t-amber/80"
            >
              {existingAlert ? "Update" : "Arm alert"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Drawing toolbar ───────────────────────────────────────────────────────────

const DRAWING_COLORS = ["#f59e0b", "#a78bfa", "#4ade80", "#f87171", "#38bdf8", "#fb923c"];

function DrawingToolbar({
  drawings,
  onAdd,
  onRemove,
  armedAlerts,
  onAlertClick,
}: {
  drawings: Drawing[];
  onAdd: (d: Drawing) => void;
  onRemove: (id: string) => void;
  armedAlerts: PriceAlert[];
  onAlertClick: (d: Drawing) => void;
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
              {/* Alert bell */}
              {(() => {
                const armed = armedAlerts.find(
                  (a) => Math.abs(a.price - d.price) < 0.01
                );
                return (
                  <button
                    onClick={(e) => { e.stopPropagation(); onAlertClick(d); }}
                    title={armed ? "Alert armed — click to manage" : "Set price alert"}
                    className="transition-opacity text-t-muted hover:text-t-amber"
                  >
                    <Bell size={11} className={armed ? "text-t-amber" : ""} />
                  </button>
                );
              })()}
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
  const [alertTarget, setAlertTarget] = useState<Drawing | null>(null);

  const ticker = (rawTicker ?? "").toUpperCase();
  const sid = strategyId ?? "";

  // Fetch the per-strategy chart indicator spec (server-driven).
  // While this is loading we render the chart with no overlays — the chart
  // itself still appears so the user sees price action immediately.
  const { data: indicatorsCfg } = useQuery({
    queryKey: ["scout-strategy-indicators", sid],
    queryFn: () => getStrategyIndicators(sid),
    staleTime: Infinity,
    enabled: !!sid,
  });

  const indicatorSpecs: ScoutIndicatorSpec[] = indicatorsCfg?.indicators ?? [];
  const apiIndicators = indicatorsCfg?.engine_keys ?? "";

  // ── Timeframe chip rail ────────────────────────────────────────────────────
  // The full chip set is fixed at 6 (1D / 4H / 1H / 15m / 5m / 1m). The
  // strategy's `timeframes.allowed` controls which chips are interactive; the
  // rest render grayed out so the user can see what's not on offer for this
  // strategy (and why). Default selection comes from `timeframes.default`,
  // falling back to "1D" when the backend hasn't shipped the new field yet.
  const allTimeframes: ScoutTimeframe[] = ["1D", "4H", "1H", "15m", "5m", "1m"];
  const allowedTimeframes: ScoutTimeframe[] =
    indicatorsCfg?.timeframes?.allowed ?? ["1D", "4H"];
  const defaultTimeframe: ScoutTimeframe =
    indicatorsCfg?.timeframes?.default ?? "1D";

  const [timeframe, setTimeframe] = useState<ScoutTimeframe>(defaultTimeframe);

  // Once the indicators config arrives, snap the active chip to the strategy's
  // declared default. We only do this once per strategy mount; if the user
  // clicks a different chip we keep their choice.
  const tfInitialized = useRef(false);
  useEffect(() => {
    if (!tfInitialized.current && indicatorsCfg?.timeframes?.default) {
      setTimeframe(indicatorsCfg.timeframes.default);
      tfInitialized.current = true;
    }
  }, [indicatorsCfg?.timeframes?.default]);

  // Fetch description for display name
  const { data: descData } = useQuery({
    queryKey: ["strategy-desc", sid],
    queryFn: () => getStrategyDescription(sid),
    staleTime: Infinity,
    retry: 1,
  });

  // Compute the bars-endpoint timeframe token + the lookback `start` date for
  // the active chip. History depths are sized so the chart loads fast even on
  // intraday timeframes:
  //   1D  → 5y   |  4H → 1y   |  1H → 6mo
  //   15m → 1mo  |  5m → 2wk  |  1m → 3d
  const { barsTimeframe, startIso, tfLabel } = useMemo(() => {
    const map: Record<ScoutTimeframe, { bars: string; days: number; label: string }> = {
      "1D":  { bars: "1Day",  days: 365 * 5, label: "DAILY" },
      "4H":  { bars: "4Hour", days: 365,     label: "4-HOUR" },
      "1H":  { bars: "1Hour", days: 180,     label: "HOURLY" },
      "15m": { bars: "15Min", days: 30,      label: "15-MIN" },
      "5m":  { bars: "5Min",  days: 14,      label: "5-MIN" },
      "1m":  { bars: "1Min",  days: 3,       label: "1-MIN" },
    };
    const cfg = map[timeframe] ?? map["1D"];
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - cfg.days);
    return { barsTimeframe: cfg.bars, startIso: d.toISOString().slice(0, 10), tfLabel: cfg.label };
  }, [timeframe]);

  // Fetch bars with indicators — engine keys depend on strategy spec; the
  // timeframe + start window depend on the active chip.
  const { data: barsData, isLoading: barsLoading, isError: barsError } = useQuery({
    queryKey: ["scout-chart-bars", ticker, apiIndicators, barsTimeframe, startIso],
    queryFn: () => fetchBars(ticker, barsTimeframe, apiIndicators || undefined, startIso),
    staleTime: 300_000,
    enabled: !!ticker && !!indicatorsCfg,
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

  const crossovers = useMemo(
    () => computeCrossovers(bars, indicators, indicatorSpecs),
    [bars, indicators, indicatorSpecs],
  );

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

  // Load alerts for this ticker
  const { data: alertsData, refetch: refetchAlerts } = useQuery<PriceAlert[]>({
    queryKey: ["price-alerts", ticker],
    queryFn: () =>
      client
        .get<{ alerts: PriceAlert[] }>("/price-alerts", { params: { ticker } })
        .then((r) => r.data.alerts ?? []),
    enabled: !!ticker,
    staleTime: 30_000,
  });
  const armedAlerts: PriceAlert[] = (alertsData ?? []).filter((a) => a.status === "armed");

  const createAlertMutation = useMutation({
    mutationFn: (body: {
      ticker: string;
      price: number;
      direction: "above" | "below";
      message: string;
      notif_discord: boolean;
      workshop_chart_id?: number;
    }) => client.post<PriceAlert>("/price-alerts", body).then((r) => r.data),
    onSuccess: () => {
      refetchAlerts();
      setAlertTarget(null);
      toast.success("Alert armed");
    },
    onError: () => toast.error("Failed to arm alert"),
  });

  const cancelAlertMutation = useMutation({
    mutationFn: (alertId: number) => client.delete(`/price-alerts/${alertId}`),
    onSuccess: () => {
      refetchAlerts();
      toast.success("Alert cancelled");
    },
  });

  // Find current setup status — only meaningful for two-SMA crossover strategies.
  // For everything else we fall back to a price-only summary so the section
  // still renders something useful.
  const currentStatus = useMemo(() => {
    if (!bars.length) return null;
    const smaSpecs = indicatorSpecs
      .filter((s) => s.type === "sma")
      .map((s) => ({
        period: Number((s.params as any)?.period ?? 0),
        label: s.label,
      }))
      .filter((s) => s.period > 0)
      .sort((a, b) => a.period - b.period);
    const last = bars.length - 1;
    const currentPrice = bars[last]?.close;

    if (smaSpecs.length < 2) {
      // No crossover semantics — return minimal price status so the
      // header subtitle still renders.
      return {
        fastVal: null as number | null,
        slowVal: null as number | null,
        gap: 0,
        isActive: false,
        currentPrice,
        fastLabel: "",
        slowLabel: "",
        crossedAt: null as string | null,
        daysSince: null as number | null,
        status: "WAITING" as const,
      };
    }

    const fastKey = `SMA_${smaSpecs[0].period}`;
    const slowKey = `SMA_${smaSpecs[1].period}`;
    const fastArr = indicators[fastKey];
    const slowArr = indicators[slowKey];
    const fastVal = fastArr?.[last] ?? null;
    const slowVal = slowArr?.[last] ?? null;
    if (fastVal == null || slowVal == null) {
      return {
        fastVal: null, slowVal: null, gap: 0, isActive: false, currentPrice,
        fastLabel: smaSpecs[0].label, slowLabel: smaSpecs[1].label,
        crossedAt: null, daysSince: null, status: "WAITING" as const,
      };
    }
    const gap = fastVal - slowVal;
    const isActive = gap > 0;
    const lastUp = [...crossovers].reverse().find((c) => c.direction === "up");
    const daysSince = lastUp ? Math.round((Date.now() - lastUp.time * 1000) / 86400000) : null;
    return {
      fastVal, slowVal, gap, isActive, currentPrice,
      fastLabel: smaSpecs[0].label,
      slowLabel: smaSpecs[1].label,
      crossedAt: lastUp ? fmtDate(lastUp.time) : null,
      daysSince,
      status: isActive ? ("ACTIVE" as const) : ("WAITING" as const),
    };
  }, [bars, indicators, indicatorSpecs, crossovers]);

  // Past triggers moved to BacktestPanel (Commit 3) — multi-year history with
  // win rate, Sharpe, max DD, equity curve etc. Replaces the old 5-row table
  // that only knew about SMA crossovers.

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
                {currentStatus.fastVal != null && currentStatus.slowVal != null && (
                  <>
                    {" · "}
                    {currentStatus.fastLabel}: ${currentStatus.fastVal.toFixed(2)}
                    {" · "}
                    {currentStatus.slowLabel}: ${currentStatus.slowVal.toFixed(2)}
                  </>
                )}
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
          {/* Timeframe chip rail — all 6 chips render, but only `allowed`
              ones are clickable. Disabled chips stay visible so the user can
              see what's NOT on offer for this strategy. Style matches the
              BacktestPanel year-range chips. */}
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <span className="text-[10px] font-mono-t text-t-faint uppercase tracking-widest">
              // TIMEFRAME
            </span>
            <div className="flex items-center gap-1 flex-wrap">
              {allTimeframes.map((tf) => {
                const allowed = allowedTimeframes.includes(tf);
                const active = timeframe === tf;
                return (
                  <button
                    key={tf}
                    onClick={() => allowed && setTimeframe(tf)}
                    disabled={!allowed}
                    title={allowed ? `Switch to ${tf}` : `${tf} not supported by this strategy`}
                    className={cn(
                      "text-[10px] font-mono-t px-2 py-1 rounded border transition-colors",
                      active && allowed
                        ? "border-t-mid text-t-hi bg-t-bg2"
                        : allowed
                          ? "border-t-dim/40 text-t-muted hover:text-t-hi hover:border-t-dim"
                          : "border-t-dim/20 text-t-faint/50 cursor-not-allowed"
                    )}
                  >
                    {tf}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-[10px] font-mono-t text-t-faint uppercase tracking-widest">
              // PRICE CHART — {bars.length > 0
                ? `${bars.length} ${tfLabel} BARS (${fmtDate(bars[0].time)} → ${fmtDate(bars[bars.length - 1].time)})`
                : `${tfLabel}`}
            </span>
            <div className="flex gap-3 flex-wrap">
              {indicatorSpecs.map((ind, i) => (
                <div key={`${ind.type}_${i}`} className="flex items-center gap-1.5">
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
              indicatorSpecs={indicatorSpecs}
              crossoverMarkers={crossovers.map(c => ({ time: c.time, direction: c.direction }))}
              drawings={drawings}
            />
          )}

          {/* Price level annotations — lives inside chart card so it's always in-frame */}
          <DrawingToolbar
            drawings={drawings}
            onAdd={handleAddDrawing}
            onRemove={handleRemoveDrawing}
            armedAlerts={armedAlerts}
            onAlertClick={(d) => setAlertTarget(d)}
          />
        </div>

        {/* Setup checklist — per-strategy trigger-condition table */}
        <SetupChecklist ticker={ticker} strategyId={sid} />

        {/* Past triggers — multi-year backtest, stats card, equity curve, clickable rows */}
        <BacktestPanel ticker={ticker} strategyId={sid} />
      </div>

      {showSaveModal && (
        <SaveModal
          ticker={ticker}
          strategyId={sid}
          onClose={() => setShowSaveModal(false)}
          onSave={(name, notes) => saveMutation.mutate({ name, notes })}
        />
      )}
      {alertTarget && (
        <AlertModal
          drawing={alertTarget}
          currentPrice={currentStatus?.currentPrice ?? null}
          ticker={ticker}
          existingAlert={armedAlerts.find((a) => Math.abs(a.price - alertTarget.price) < 0.01) ?? null}
          onClose={() => setAlertTarget(null)}
          onSave={(direction, message, notifDiscord) =>
            createAlertMutation.mutate({ ticker, price: alertTarget.price, direction, message, notif_discord: notifDiscord })
          }
          onCancel={(alertId) => { cancelAlertMutation.mutate(alertId); setAlertTarget(null); }}
        />
      )}
    </div>
  );
}

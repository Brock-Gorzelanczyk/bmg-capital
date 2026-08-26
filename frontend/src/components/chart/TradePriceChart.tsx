/**
 * TradePriceChart — self-contained lightweight-charts chart for the trade
 * detail page. Renders entry / stop / target / exit price lines using the
 * library's native priceLine API, places entry/exit markers on candles, and
 * keeps a live "NOW" price line updated imperatively without re-mounting.
 */
import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  ColorType,
  LineStyle,
} from "lightweight-charts";
import type { IChartApi, ISeriesApi, IPriceLine, UTCTimestamp } from "lightweight-charts";
import type { Bar } from "@/types/market";

// Indicator overlay colors — matches Brock's Pine editor scripts on ~/Desktop/*_Confluence_Framework.pine
const OVERLAY_COLORS: Record<string, string> = {
  SMA_20: "#f39c12",  // orange — matches Pine
  SMA_50: "#9b59b6",  // purple — matches Pine
  SMA_200: "#3498db", // blue — matches Pine
  BB_20_upper: "rgba(243,156,18,0.6)",  // orange BB uppers/lowers
  BB_20_lower: "rgba(243,156,18,0.6)",
  BB_20_middle: "rgba(243,156,18,0.3)",
  EMA_20: "#fbbf24", EMA_50: "#60a5fa", EMA_200: "#a78bfa",
  VWAP: "#06b6d4",
};

function isOverlay(key: string): boolean {
  return key.startsWith("SMA_") || key.startsWith("EMA_")
    || key === "VWAP"
    || key.startsWith("BB_")
    || key.endsWith("_upper") || key.endsWith("_middle") || key.endsWith("_lower");
}

const toTime = (t: string) => Math.floor(new Date(t).getTime() / 1000) as UTCTimestamp;

function precisionForPrice(price: number): { precision: number; minMove: number } {
  if (price >= 1000)   return { precision: 2, minMove: 0.01 };
  if (price >= 1)      return { precision: 4, minMove: 0.0001 };
  if (price >= 0.01)   return { precision: 5, minMove: 0.00001 };
  if (price >= 0.0001) return { precision: 6, minMove: 0.000001 };
  return               { precision: 8, minMove: 0.00000001 };
}

export interface ConfluenceLevels {
  playATrigger?: number | null;
  playAStop?: number | null;
  playBTrigger?: number | null;
  playBStop?: number | null;
  invalidation?: number | null;
  target2?: number | null;
  // Insider cluster zone (green shaded region) — price range + optional ISO time window
  insiderZoneLow?: number | null;
  insiderZoneHigh?: number | null;
  insiderZoneLabel?: string | null;
  insiderZoneStart?: string | null;  // ISO timestamp — left edge of shaded rect
  insiderZoneEnd?: string | null;    // ISO timestamp — right edge of shaded rect
}

// Framework score badge (top-right of chart) — signals fired / total
export interface ScoreBadge {
  count: number;
  total: number;
  label?: string;
}

export interface TradePriceChartProps {
  bars: Bar[];
  entryPrice: number;
  entryTime: string | null;
  side: string;
  qty: number;
  symbol: string;
  stopLoss?: number | null;
  takeProfit?: number | null;
  exitPrice?: number | null;
  exitTime?: string | null;
  livePrice?: number | null;
  // Optional confluence framework overlays — Play A/B triggers, invalidation, insider zone
  confluenceLevels?: ConfluenceLevels;
  // Optional indicator arrays keyed by name (SMA_20, SMA_50, SMA_200, BB_20_upper/middle/lower, etc.)
  // Aligned 1:1 with bars.length
  indicators?: Record<string, (number | null)[]>;
  // Optional framework score badge (rendered top-right of chart)
  scoreBadge?: ScoreBadge;
}

export default function TradePriceChart({
  bars,
  entryPrice,
  entryTime,
  side,
  qty,
  symbol,
  stopLoss,
  takeProfit,
  exitPrice,
  exitTime,
  livePrice,
  confluenceLevels,
  indicators,
  scoreBadge,
}: TradePriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const insiderZoneRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const nowLineRef = useRef<IPriceLine | null>(null);
  const livePriceRef = useRef<number | null>(livePrice ?? null);
  const precisionRef = useRef<number>(2);

  // ── Create chart once ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || bars.length === 0) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#18181B" },
        textColor: "#a1a1aa",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      crosshair: { mode: 1 },
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.08)",
        scaleMargins: { top: 0.08, bottom: 0.15 },
      },
      timeScale: {
        borderColor: "rgba(255,255,255,0.08)",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 6,
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
      autoSize: true,
    });

    // Volume
    const vol = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    // Candles
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const candleData = bars.map((b) => ({
      time: toTime(b.t),
      open: b.o, high: b.h, low: b.l, close: b.c,
    }));
    candles.setData(candleData);
    vol.setData(bars.map((b) => ({
      time: toTime(b.t),
      value: b.v,
      color: b.c >= b.o ? "#22c55e28" : "#ef444428",
    })));

    // ── Indicator overlays (SMAs, Bollinger Bands, etc.) — matches Pine editor scripts ──
    if (indicators) {
      Object.entries(indicators).forEach(([key, values]) => {
        if (!isOverlay(key)) return;
        if (!values || !Array.isArray(values)) return;
        const color = OVERLAY_COLORS[key] ?? "#94a3b8";
        const isBBMid = key.endsWith("_middle");
        const isSMA200 = key === "SMA_200";
        const line = chart.addSeries(LineSeries, {
          color,
          lineWidth: isSMA200 ? 2 : 1,
          lineStyle: isBBMid ? LineStyle.Dotted : LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: false,
          title: key.replace("_", " "),
        });
        const n = Math.min(bars.length, values.length);
        const lineData = bars.slice(0, n)
          .map((b, i) => ({ time: toTime(b.t), value: values[i] as number }))
          .filter(d => d.value != null && !Number.isNaN(d.value));
        if (lineData.length > 0) line.setData(lineData);
      });
    }

    // Compute precision from the smallest price in the group so the axis
    // and pill labels show the right decimal depth for low-priced assets.
    const allPrices = [entryPrice, stopLoss, takeProfit, exitPrice]
      .filter((p): p is number => p != null && p > 0);
    const refPrice = allPrices.length ? Math.min(...allPrices) : entryPrice;
    const { precision, minMove } = precisionForPrice(refPrice);
    precisionRef.current = precision;
    candles.applyOptions({ priceFormat: { type: "price", precision, minMove } });

    // ── Price lines ─────────────────────────────────────────────────────────────

    // Entry — solid blue 2px
    candles.createPriceLine({
      price: entryPrice,
      color: "#3b82f6",
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: true,
      title: `ENTRY  $${entryPrice.toFixed(precision)}`,
    });

    // Stop loss — dashed red 2px
    if (stopLoss) {
      candles.createPriceLine({
        price: stopLoss,
        color: "#ef4444",
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `STOP  $${stopLoss.toFixed(precision)}`,
      });
    }

    // Take profit — dashed green 2px
    if (takeProfit) {
      candles.createPriceLine({
        price: takeProfit,
        color: "#22c55e",
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `TARGET  $${takeProfit.toFixed(precision)}`,
      });
    }

    // ── Confluence framework overlays (Play A/B triggers, invalidation, insider zone) ──
    if (confluenceLevels) {
      const cl = confluenceLevels;
      if (cl.playATrigger) {
        candles.createPriceLine({
          price: cl.playATrigger,
          color: "#f87171",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `PLAY A > $${cl.playATrigger.toFixed(precision)}`,
        });
      }
      if (cl.playAStop) {
        candles.createPriceLine({
          price: cl.playAStop,
          color: "#fb923c",
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: `PLAY A STOP $${cl.playAStop.toFixed(precision)}`,
        });
      }
      if (cl.playBTrigger) {
        candles.createPriceLine({
          price: cl.playBTrigger,
          color: "#4ade80",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `PLAY B ≤ $${cl.playBTrigger.toFixed(precision)}`,
        });
      }
      if (cl.playBStop) {
        candles.createPriceLine({
          price: cl.playBStop,
          color: "#a78bfa",
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: `PLAY B STOP $${cl.playBStop.toFixed(precision)}`,
        });
      }
      if (cl.invalidation) {
        candles.createPriceLine({
          price: cl.invalidation,
          color: "#dc2626",
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: `INVALIDATION $${cl.invalidation.toFixed(precision)}`,
        });
      }
      if (cl.target2) {
        candles.createPriceLine({
          price: cl.target2,
          color: "#16a34a",
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: `TARGET 2 $${cl.target2.toFixed(precision)}`,
        });
      }
      // Insider zone edge lines (the shaded green rect is rendered as an HTML overlay
      // below — the two thin lines here bookend the y-range on the axis)
      if (cl.insiderZoneLow && cl.insiderZoneHigh) {
        candles.createPriceLine({
          price: cl.insiderZoneHigh,
          color: "rgba(34, 197, 94, 0.6)",
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: false,
          title: "",
        });
        candles.createPriceLine({
          price: cl.insiderZoneLow,
          color: "rgba(34, 197, 94, 0.6)",
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: false,
          title: "",
        });
      }
    }

    // ── Insider zone shaded rectangle (HTML overlay tracking chart coords) ──
    const positionInsiderZone = () => {
      const el = insiderZoneRef.current;
      const cl = confluenceLevels;
      if (!el || !cl || !cl.insiderZoneLow || !cl.insiderZoneHigh) return;
      const ts = chart.timeScale();
      // Y coords from price
      const yHigh = candles.priceToCoordinate(cl.insiderZoneHigh);
      const yLow  = candles.priceToCoordinate(cl.insiderZoneLow);
      if (yHigh == null || yLow == null) { el.style.display = "none"; return; }
      // X coords: default = full visible width if no explicit window
      const chartW = containerRef.current?.clientWidth ?? 0;
      let x1 = 0, x2 = chartW;
      if (cl.insiderZoneStart && cl.insiderZoneEnd) {
        const t1 = toTime(cl.insiderZoneStart);
        const t2 = toTime(cl.insiderZoneEnd);
        const c1 = ts.timeToCoordinate(t1);
        const c2 = ts.timeToCoordinate(t2);
        if (c1 != null) x1 = c1;
        if (c2 != null) x2 = c2;
      }
      el.style.display = "block";
      el.style.left   = `${Math.min(x1, x2)}px`;
      el.style.width  = `${Math.max(2, Math.abs(x2 - x1))}px`;
      el.style.top    = `${Math.min(yHigh, yLow)}px`;
      el.style.height = `${Math.max(2, Math.abs(yHigh - yLow))}px`;
    };
    positionInsiderZone();
    chart.timeScale().subscribeVisibleTimeRangeChange(positionInsiderZone);
    chart.timeScale().subscribeVisibleLogicalRangeChange(positionInsiderZone);
    const resizeObs = new ResizeObserver(positionInsiderZone);
    if (containerRef.current) resizeObs.observe(containerRef.current);

    // Exit price (closed trade) — solid amber 2px
    if (exitPrice) {
      candles.createPriceLine({
        price: exitPrice,
        color: "#f59e0b",
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: `EXIT  $${exitPrice.toFixed(precision)}`,
      });
    }

    // Live NOW line — dashed cyan so it stands out from entry(blue)/stop(red)/target(green)
    const nowPriceInitial = livePriceRef.current ?? entryPrice;
    const nowPct = entryPrice > 0 ? ((nowPriceInitial - entryPrice) / entryPrice) * 100 : 0;
    const nowLine = candles.createPriceLine({
      price: nowPriceInitial,
      color: "#06b6d4",
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: livePriceRef.current != null,
      title: livePriceRef.current != null
        ? `NOW  $${nowPriceInitial.toFixed(precision)} (${nowPct >= 0 ? "+" : ""}${nowPct.toFixed(2)}%)`
        : "",
    });
    nowLineRef.current = nowLine;

    // ── Markers ─────────────────────────────────────────────────────────────────

    const isBuy = side === "buy";
    const unitLabel = symbol.includes("/") ? symbol.split("/")[0] : "shares";
    const qtyStr = qty.toFixed(symbol.includes("/") ? 6 : 4);

    const markers: {
      time: UTCTimestamp;
      position: "belowBar" | "aboveBar";
      color: string;
      shape: "arrowUp" | "arrowDown";
      text: string;
      size: number;
    }[] = [];

    // Entry marker
    if (entryTime) {
      const entryTs = Math.floor(new Date(entryTime).getTime() / 1000) as UTCTimestamp;
      // Find the matching candle (closest at or after entry time)
      const entryCandle = bars.find((b) => toTime(b.t) >= entryTs) ?? bars[bars.length - 1];
      if (entryCandle) {
        markers.push({
          time: toTime(entryCandle.t),
          position: isBuy ? "belowBar" : "aboveBar",
          color: isBuy ? "#22c55e" : "#ef4444",
          shape: isBuy ? "arrowUp" : "arrowDown",
          text: `${isBuy ? "BUY" : "SELL"} ${qtyStr} ${unitLabel}`,
          size: 2,
        });
      }
    }

    // Exit marker (closed trade)
    if (exitTime && exitPrice) {
      const exitTs = Math.floor(new Date(exitTime).getTime() / 1000) as UTCTimestamp;
      const exitCandle = bars.find((b) => toTime(b.t) >= exitTs) ?? bars[bars.length - 1];
      if (exitCandle) {
        markers.push({
          time: toTime(exitCandle.t),
          position: "aboveBar",
          color: "#f59e0b",
          shape: "arrowDown",
          text: `EXIT $${exitPrice.toFixed(precisionRef.current)}`,
          size: 2,
        });
      }
    }

    if (markers.length > 0) {
      markers.sort((a, b) => a.time - b.time);
      try { (candles as any).setMarkers(markers); } catch {}
    }

    // ── Scroll to show entry candle ───────────────────────────────────────────

    if (entryTime && bars.length > 0) {
      const entryTs = Math.floor(new Date(entryTime).getTime() / 1000) as UTCTimestamp;
      const lastTs = toTime(bars[bars.length - 1].t);
      // Show ~60 days of history ending at the last bar, centered on entry
      const from = Math.max(toTime(bars[0].t), entryTs - 60 * 86400) as UTCTimestamp;
      chart.timeScale().setVisibleRange({ from, to: lastTs });
    }

    chartRef.current = chart;
    candlesRef.current = candles;

    return () => {
      nowLineRef.current = null;
      candlesRef.current = null;
      chartRef.current = null;
      try { chart.timeScale().unsubscribeVisibleTimeRangeChange(positionInsiderZone); } catch {}
      try { chart.timeScale().unsubscribeVisibleLogicalRangeChange(positionInsiderZone); } catch {}
      try { resizeObs.disconnect(); } catch {}
      try { chart.remove(); } catch {}
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars]);

  // ── Update NOW line imperatively when livePrice ticks ────────────────────────
  useEffect(() => {
    livePriceRef.current = livePrice ?? null;
    const line = nowLineRef.current;
    if (!line || livePrice == null) return;
    const aboveEntry = livePrice >= entryPrice;
    const pct = entryPrice > 0 ? ((livePrice - entryPrice) / entryPrice) * 100 : 0;
    const prec = precisionRef.current;
    try {
      line.applyOptions({
        price: livePrice,
        color: "#06b6d4",
        axisLabelVisible: true,
        title: `NOW  $${livePrice.toFixed(prec)} (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)`,
      });
    } catch {}
  }, [livePrice, entryPrice]);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div ref={containerRef} className="w-full h-full" />

      {/* Insider cluster zone — semi-transparent green rectangle positioned via chart coords */}
      {confluenceLevels?.insiderZoneLow && confluenceLevels?.insiderZoneHigh && (
        <div
          ref={insiderZoneRef}
          style={{
            position: "absolute",
            display: "none",
            background: "rgba(34, 197, 94, 0.12)",
            border: "1px solid rgba(34, 197, 94, 0.35)",
            pointerEvents: "none",
            zIndex: 2,
          }}
        >
          <div style={{
            position: "absolute", top: 4, left: 6,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10,
            color: "rgba(74,222,128,0.9)",
            letterSpacing: "0.06em",
          }}>
            {confluenceLevels.insiderZoneLabel || "INSIDER CLUSTER"}
          </div>
        </div>
      )}

      {/* Framework score badge — top-right, TradingView-style */}
      {scoreBadge && (
        <div style={{
          position: "absolute",
          top: 10, right: 66,  // leave room for the price scale
          padding: "6px 10px",
          background: "rgba(15, 23, 15, 0.85)",
          border: `1px solid ${scoreBadge.count >= 3 ? "rgba(74,222,128,0.5)" : "rgba(148,163,184,0.35)"}`,
          borderRadius: 4,
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
          color: scoreBadge.count >= 3 ? "#4ade80" : "#94a3b8",
          letterSpacing: "0.06em",
          pointerEvents: "none",
          zIndex: 3,
        }}>
          {scoreBadge.label || "SCORE"} {scoreBadge.count}/{scoreBadge.total}
        </div>
      )}
    </div>
  );
}

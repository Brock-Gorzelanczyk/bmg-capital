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
  ColorType,
  LineStyle,
} from "lightweight-charts";
import type { IChartApi, ISeriesApi, IPriceLine, UTCTimestamp } from "lightweight-charts";
import type { Bar } from "@/types/market";

const toTime = (t: string) => Math.floor(new Date(t).getTime() / 1000) as UTCTimestamp;

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
}: TradePriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const nowLineRef = useRef<IPriceLine | null>(null);
  const livePriceRef = useRef<number | null>(livePrice ?? null);

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

    // ── Price lines ─────────────────────────────────────────────────────────────

    // Entry — solid blue 2px
    candles.createPriceLine({
      price: entryPrice,
      color: "#3b82f6",
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: true,
      title: `ENTRY  $${entryPrice.toFixed(2)}`,
    });

    // Stop loss — dashed red 2px
    if (stopLoss) {
      candles.createPriceLine({
        price: stopLoss,
        color: "#ef4444",
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `STOP  $${stopLoss.toFixed(2)}`,
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
        title: `TARGET  $${takeProfit.toFixed(2)}`,
      });
    }

    // Exit price (closed trade) — solid amber 2px
    if (exitPrice) {
      candles.createPriceLine({
        price: exitPrice,
        color: "#f59e0b",
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: `EXIT  $${exitPrice.toFixed(2)}`,
      });
    }

    // Live NOW line — created now, updated imperatively when livePrice changes
    const nowPriceInitial = livePriceRef.current ?? entryPrice;
    const nowAboveEntry = nowPriceInitial >= entryPrice;
    const nowPct = entryPrice > 0 ? ((nowPriceInitial - entryPrice) / entryPrice) * 100 : 0;
    const nowLine = candles.createPriceLine({
      price: nowPriceInitial,
      color: nowAboveEntry ? "#86efac" : "#fca5a5",
      lineWidth: 1,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: livePriceRef.current != null,
      title: livePriceRef.current != null
        ? `NOW  $${nowPriceInitial.toFixed(2)} (${nowPct >= 0 ? "+" : ""}${nowPct.toFixed(2)}%)`
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
          text: `EXIT $${exitPrice.toFixed(2)}`,
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
    try {
      line.applyOptions({
        price: livePrice,
        color: aboveEntry ? "#86efac" : "#fca5a5",
        axisLabelVisible: true,
        title: `NOW  $${livePrice.toFixed(2)} (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)`,
      });
    } catch {}
  }, [livePrice, entryPrice]);

  return <div ref={containerRef} className="w-full h-full" />;
}

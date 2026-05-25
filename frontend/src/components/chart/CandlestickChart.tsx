import { useEffect, useRef, useImperativeHandle, forwardRef, useState, useMemo } from "react";
import {
  createChart,
  CandlestickSeries,
  BarSeries,
  LineSeries,
  AreaSeries,
  HistogramSeries,
  ColorType,
  LineStyle,
} from "lightweight-charts";
import type { IChartApi, ISeriesApi, IPriceLine, UTCTimestamp } from "lightweight-charts";
import type { Bar } from "@/types/market";
import type { ChartType, DrawingTool, HoveredBar, Drawing } from "@/types/chart";

export interface ChartHandle {
  updateBar: (bar: Bar) => void;
}

export interface TradeLevels {
  entry?: number;
  stop?: number;
  target?: number;
  entryDate?: string;
  exitDate?: string;
  exitPrice?: number;
  exitReason?: string;
}

interface Props {
  bars: Bar[];
  indicators?: Record<string, (number | null)[]>;
  chartType: ChartType;
  activeTool: DrawingTool;
  drawings: Drawing[];
  tradeLevels?: TradeLevels;
  compareBars?: Bar[];
  compareSymbol?: string;
  onCrosshairMove: (bar: HoveredBar | null) => void;
  onAddDrawing: (d: Omit<Drawing, "id">) => void;
}

const TV = {
  bg: "#131722",
  grid: "#1e222d",
  text: "#d1d4dc",
  border: "#2a2e39",
  up: "#26a69a",
  down: "#ef5350",
  upVol: "#26a69a33",
  downVol: "#ef535033",
};

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
};

function isOverlay(key: string): boolean {
  return key.startsWith("SMA_") || key.startsWith("EMA_") || key.startsWith("DEMA_")
    || key === "VWAP" || key === "PSAR"
    || key.startsWith("ICHI_") || key.startsWith("DONCHIAN_") || key.startsWith("KELTNER_")
    || key.endsWith("_upper") || key.endsWith("_middle") || key.endsWith("_lower");
}

const toTime = (t: string) => Math.floor(new Date(t).getTime() / 1000) as UTCTimestamp;

function computeHA(bars: Bar[]): Bar[] {
  const out: Bar[] = [];
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const c = (b.o + b.h + b.l + b.c) / 4;
    const o = i === 0 ? (b.o + b.c) / 2 : (out[i - 1].o + out[i - 1].c) / 2;
    out.push({ ...b, o, h: Math.max(b.h, o, c), l: Math.min(b.l, o, c), c });
  }
  return out;
}

type AnyMain = ISeriesApi<"Candlestick"> | ISeriesApi<"Bar"> | ISeriesApi<"Line"> | ISeriesApi<"Area">;

const CandlestickChart = forwardRef<ChartHandle, Props>(
  ({ bars, indicators = {}, chartType, activeTool, drawings, tradeLevels, compareBars, compareSymbol, onCrosshairMove, onAddDrawing }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const mainSeriesRef = useRef<AnyMain | null>(null);
    const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const lineSeriesRef = useRef<Record<string, ISeriesApi<"Line">>>({});
    const priceLinesRef = useRef<Record<string, IPriceLine>>({});
    const tradeLevelLinesRef = useRef<Record<string, IPriceLine>>({});
    const trendSeriesRef = useRef<Record<string, ISeriesApi<"Line">>>({});
    const fibLinesRef = useRef<Record<string, IPriceLine[]>>({});
    const textLinesRef = useRef<Record<string, IPriceLine>>({});
    const compareSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const [overlayVersion, setOverlayVersion] = useState(0);

    // Stable refs for callbacks so chart subscriptions don't need re-registration
    const onCrosshairMoveRef = useRef(onCrosshairMove);
    const onAddDrawingRef = useRef(onAddDrawing);
    const toolRef = useRef(activeTool);
    useEffect(() => { onCrosshairMoveRef.current = onCrosshairMove; }, [onCrosshairMove]);
    useEffect(() => { onAddDrawingRef.current = onAddDrawing; }, [onAddDrawing]);
    useEffect(() => { toolRef.current = activeTool; }, [activeTool]);

    useImperativeHandle(ref, () => ({
      updateBar: (bar: Bar) => {
        if (!mainSeriesRef.current) return;
        const t = toTime(bar.t);
        const st = mainSeriesRef.current.seriesType();
        if (st === "Candlestick" || st === "Bar") {
          (mainSeriesRef.current as ISeriesApi<"Candlestick">).update({ time: t, open: bar.o, high: bar.h, low: bar.l, close: bar.c });
        } else {
          (mainSeriesRef.current as ISeriesApi<"Line">).update({ time: t, value: bar.c });
        }
        volSeriesRef.current?.update({ time: t, value: bar.v, color: bar.c >= bar.o ? TV.upVol : TV.downVol });
      },
    }));

    // ── Create chart (once on mount) ──────────────────────────────────────────
    useEffect(() => {
      if (!containerRef.current) return;

      const chart = createChart(containerRef.current, {
        layout: { background: { type: ColorType.Solid, color: TV.bg }, textColor: TV.text },
        grid: { vertLines: { color: TV.grid }, horzLines: { color: TV.grid } },
        crosshair: { mode: 1 },
        rightPriceScale: {
          borderColor: TV.border,
          // TradingView-style margins: 5% top breathing room, 12% bottom reserved for volume bars
          scaleMargins: { top: 0.05, bottom: 0.12 },
        },
        timeScale: {
          borderColor: TV.border,
          timeVisible: true,
          secondsVisible: false,
          fixLeftEdge: true,   // no blank space before first bar
          fixRightEdge: true,  // no blank space after last bar
          rightOffset: 5,      // 5 empty bars to the right of the last candle (TradingView default)
          lockVisibleTimeRangeOnResize: true,
        },
        autoSize: true,
      });

      const vol = chart.addSeries(HistogramSeries, {
        color: TV.upVol,
        priceFormat: { type: "volume" },
        priceScaleId: "vol",
        lastValueVisible: false,
        priceLineVisible: false,
      });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
      volSeriesRef.current = vol;
      chartRef.current = chart;

      chart.timeScale().subscribeVisibleLogicalRangeChange(() => setOverlayVersion((v) => v + 1));

      chart.subscribeCrosshairMove((param) => {
        if (!param.seriesData?.size || !param.point) {
          onCrosshairMoveRef.current(null);
          return;
        }
        const main = mainSeriesRef.current;
        if (!main) return;
        const d = param.seriesData.get(main as ISeriesApi<"Candlestick">);
        const vd = param.seriesData.get(vol);
        if (!d) return;
        const vol_ = (vd && "value" in vd) ? (vd as { value: number }).value : 0;
        const bar: HoveredBar = "open" in d
          ? { time: (d as { time: number }).time, open: (d as any).open, high: (d as any).high, low: (d as any).low, close: (d as any).close, volume: vol_ }
          : { time: (d as { time: number }).time, open: (d as any).value, high: (d as any).value, low: (d as any).value, close: (d as any).value, volume: vol_ };
        onCrosshairMoveRef.current(bar);
      });

      chart.subscribeClick((param) => {
        if (!param.point || !mainSeriesRef.current) return;
        const tool = toolRef.current;
        if (tool === "cursor" || tool === "eraser") return;
        const price = (mainSeriesRef.current as ISeriesApi<"Candlestick">).coordinateToPrice(param.point.y);
        if (price === null) return;
        if (tool === "hline") {
          onAddDrawingRef.current({ type: "hline", price, color: "#787b86" });
        } else if (tool === "trendline" || tool === "rect" || tool === "fib") {
          const time = chart.timeScale().coordinateToTime(param.point.x);
          if (time !== null) {
            const colors: Record<string, string> = { trendline: "#2196f3", rect: "#f59e0b", fib: "#9c27b0" };
            onAddDrawingRef.current({ type: tool, p1: { price, time: time as number }, color: colors[tool] });
          }
        } else if (tool === "text") {
          const time = chart.timeScale().coordinateToTime(param.point.x);
          if (time !== null) {
            onAddDrawingRef.current({ type: "text", p1: { price, time: time as number }, color: "#d1d4dc" });
          }
        }
      });

      return () => {
        chart.remove();
        chartRef.current = null;
        mainSeriesRef.current = null;
        volSeriesRef.current = null;
        lineSeriesRef.current = {};
        priceLinesRef.current = {};
        tradeLevelLinesRef.current = {};
        trendSeriesRef.current = {};
        fibLinesRef.current = {};
        textLinesRef.current = {};
        compareSeriesRef.current = null;
      };
    }, []);

    // ── Switch main series when chartType changes ─────────────────────────────
    useEffect(() => {
      if (!chartRef.current) return;
      if (mainSeriesRef.current) {
        try { chartRef.current.removeSeries(mainSeriesRef.current); } catch {}
        mainSeriesRef.current = null;
      }
      let s: AnyMain;
      switch (chartType) {
        case "candle":
        case "heikinashi":
          s = chartRef.current.addSeries(CandlestickSeries, {
            upColor: TV.up, downColor: TV.down,
            borderUpColor: TV.up, borderDownColor: TV.down,
            wickUpColor: TV.up, wickDownColor: TV.down,
          });
          break;
        case "bar":
          s = chartRef.current.addSeries(BarSeries, { upColor: TV.up, downColor: TV.down });
          break;
        case "line":
          s = chartRef.current.addSeries(LineSeries, { color: "#2196f3", lineWidth: 2, priceLineVisible: false, lastValueVisible: true });
          break;
        case "area":
          s = chartRef.current.addSeries(AreaSeries, {
            lineColor: "#2196f3", topColor: "#2196f344", bottomColor: "#2196f300",
            lineWidth: 2, priceLineVisible: false, lastValueVisible: true,
          });
          break;
        default:
          s = chartRef.current.addSeries(CandlestickSeries, { upColor: TV.up, downColor: TV.down, borderUpColor: TV.up, borderDownColor: TV.down, wickUpColor: TV.up, wickDownColor: TV.down });
      }
      mainSeriesRef.current = s;
    }, [chartType]);

    // ── Update bar data ───────────────────────────────────────────────────────
    useEffect(() => {
      if (!mainSeriesRef.current || !bars.length) return;
      const src = chartType === "heikinashi" ? computeHA(bars) : bars;
      const st = mainSeriesRef.current.seriesType();
      if (st === "Candlestick" || st === "Bar") {
        (mainSeriesRef.current as ISeriesApi<"Candlestick">).setData(
          src.map((b) => ({ time: toTime(b.t), open: b.o, high: b.h, low: b.l, close: b.c }))
        );
      } else {
        (mainSeriesRef.current as ISeriesApi<"Line">).setData(
          src.map((b) => ({ time: toTime(b.t), value: b.c }))
        );
      }
      volSeriesRef.current?.setData(
        bars.map((b) => ({ time: toTime(b.t), value: b.v, color: b.c >= b.o ? TV.upVol : TV.downVol }))
      );

      if (tradeLevels) {
        let from = Math.max(0, bars.length - 90);
        let to = bars.length + 3;
        if (tradeLevels.entryDate) {
          const entryTs = new Date(tradeLevels.entryDate).getTime() / 1000;
          const entryIdx = bars.findIndex((b) => toTime(b.t) >= entryTs);
          if (entryIdx > 0) {
            from = Math.max(0, entryIdx - 15);
            if (tradeLevels.exitDate) {
              const exitTs = new Date(tradeLevels.exitDate).getTime() / 1000;
              const exitIdx = bars.findIndex((b) => toTime(b.t) >= exitTs);
              if (exitIdx > 0) to = Math.min(bars.length + 3, exitIdx + 10);
            } else {
              to = Math.min(bars.length + 3, entryIdx + 30);
            }
          }
        }
        chartRef.current?.timeScale().setVisibleLogicalRange({ from, to });
      } else {
        chartRef.current?.timeScale().fitContent();
      }
    }, [bars, chartType, tradeLevels]);

    // ── Indicator overlays ────────────────────────────────────────────────────
    useEffect(() => {
      if (!chartRef.current || !bars.length) return;

      // Remove stale
      Object.keys(lineSeriesRef.current).forEach((k) => {
        if (!(k in indicators)) {
          try { chartRef.current!.removeSeries(lineSeriesRef.current[k]); } catch {}
          delete lineSeriesRef.current[k];
        }
      });

      Object.entries(indicators).forEach(([key, values]) => {
        if (!isOverlay(key)) return;
        const color = OVERLAY_COLORS[key] ?? "#94a3b8";
        const dashed = key.endsWith("_upper") || key.endsWith("_lower");
        if (!lineSeriesRef.current[key]) {
          lineSeriesRef.current[key] = chartRef.current!.addSeries(LineSeries, {
            color, lineWidth: 1,
            lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid,
            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
          });
        }
        const n = Math.min(bars.length, values.length);
        const data = bars.slice(0, n)
          .map((b, i) => ({ time: toTime(b.t), value: values[i] }))
          .filter((d): d is { time: ReturnType<typeof toTime>; value: number } => d.value != null);
        lineSeriesRef.current[key].setData(data);
      });
    }, [indicators, bars]);

    // ── Sync drawings ─────────────────────────────────────────────────────────
    useEffect(() => {
      if (!chartRef.current || !mainSeriesRef.current) return;
      const ids = new Set(drawings.map((d) => d.id));

      Object.keys(priceLinesRef.current).forEach((id) => {
        if (!ids.has(id)) {
          try {
            (mainSeriesRef.current as ISeriesApi<"Candlestick">).removePriceLine(priceLinesRef.current[id]);
          } catch {}
          delete priceLinesRef.current[id];
        }
      });

      Object.keys(trendSeriesRef.current).forEach((id) => {
        if (!ids.has(id)) {
          try { chartRef.current!.removeSeries(trendSeriesRef.current[id]); } catch {}
          delete trendSeriesRef.current[id];
        }
      });

      Object.keys(fibLinesRef.current).forEach((id) => {
        if (!ids.has(id)) {
          fibLinesRef.current[id].forEach((pl) => {
            try { (mainSeriesRef.current as ISeriesApi<"Candlestick">).removePriceLine(pl); } catch {}
          });
          delete fibLinesRef.current[id];
        }
      });

      Object.keys(textLinesRef.current).forEach((id) => {
        if (!ids.has(id)) {
          try { (mainSeriesRef.current as ISeriesApi<"Candlestick">).removePriceLine(textLinesRef.current[id]); } catch {}
          delete textLinesRef.current[id];
        }
      });

      drawings.forEach((d) => {
        if (d.type === "hline" && d.price != null && !priceLinesRef.current[d.id]) {
          priceLinesRef.current[d.id] = (mainSeriesRef.current as ISeriesApi<"Candlestick">).createPriceLine({
            price: d.price, color: d.color, lineWidth: 1,
            lineStyle: LineStyle.Solid, axisLabelVisible: true, title: "",
          });
        }
        if (d.type === "trendline" && d.p1 && d.p2 && !trendSeriesRef.current[d.id]) {
          const s = chartRef.current!.addSeries(LineSeries, {
            color: d.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
          });
          s.setData([
            { time: d.p1.time as UTCTimestamp, value: d.p1.price },
            { time: d.p2.time as UTCTimestamp, value: d.p2.price },
          ]);
          trendSeriesRef.current[d.id] = s;
        }
        if (d.type === "fib" && d.p1 && d.p2 && !fibLinesRef.current[d.id]) {
          const hi = Math.max(d.p1.price, d.p2.price);
          const lo = Math.min(d.p1.price, d.p2.price);
          const range = hi - lo;
          const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
          const FIB_COLORS = ["#ef5350", "#f59e0b", "#26a69a", "#2196f3", "#26a69a", "#f59e0b", "#ef5350"];
          fibLinesRef.current[d.id] = FIB_LEVELS.map((level, i) => {
            const price = hi - range * level;
            return (mainSeriesRef.current as ISeriesApi<"Candlestick">).createPriceLine({
              price, color: FIB_COLORS[i], lineWidth: 1,
              lineStyle: LineStyle.Dashed, axisLabelVisible: true,
              title: `Fib ${(level * 100).toFixed(1)}%`,
            });
          });
        }
        if (d.type === "text" && d.p1 && d.label && !textLinesRef.current[d.id]) {
          textLinesRef.current[d.id] = (mainSeriesRef.current as ISeriesApi<"Candlestick">).createPriceLine({
            price: d.p1.price, color: d.color, lineWidth: 1,
            lineStyle: LineStyle.Dotted, axisLabelVisible: true,
            title: d.label,
          });
        }
      });
    }, [drawings]);

    // ── Trade level lines (entry / stop / target) ─────────────────────────────
    useEffect(() => {
      if (!mainSeriesRef.current) return;
      const s = mainSeriesRef.current as ISeriesApi<"Candlestick">;

      // Remove old lines
      Object.values(tradeLevelLinesRef.current).forEach((line) => {
        try { s.removePriceLine(line); } catch {}
      });
      tradeLevelLinesRef.current = {};

      if (!tradeLevels) return;

      if (tradeLevels.entry) {
        tradeLevelLinesRef.current.entry = s.createPriceLine({
          price: tradeLevels.entry,
          color: "#3b82f6",
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: `Entry  $${tradeLevels.entry.toFixed(2)}`,
        });
      }
      if (tradeLevels.stop) {
        tradeLevelLinesRef.current.stop = s.createPriceLine({
          price: tradeLevels.stop,
          color: "#ef4444",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `Stop Loss  $${tradeLevels.stop.toFixed(2)}`,
        });
      }
      if (tradeLevels.target) {
        tradeLevelLinesRef.current.target = s.createPriceLine({
          price: tradeLevels.target,
          color: "#22c55e",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `Take Profit  $${tradeLevels.target.toFixed(2)}`,
        });
      }
      if (tradeLevels.exitPrice) {
        const reason = tradeLevels.exitReason;
        const exitLabel = reason === "target" ? "Take Profit" : reason === "stop" ? "Stop Loss" : reason === "time" ? "Time Exit" : "Exit";
        const exitColor = reason === "target" ? "#22c55e" : reason === "stop" ? "#ef4444" : "#f59e0b";
        tradeLevelLinesRef.current.exit = s.createPriceLine({
          price: tradeLevels.exitPrice,
          color: exitColor,
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: `${exitLabel}  $${tradeLevels.exitPrice.toFixed(2)}`,
        });
      }
    }, [tradeLevels, mainSeriesRef.current]); // eslint-disable-line react-hooks/exhaustive-deps

    // ── Compare overlay (normalized to main's starting price) ─────────────────
    useEffect(() => {
      if (!chartRef.current) return;
      if (!compareBars?.length || !bars.length) {
        if (compareSeriesRef.current) {
          try { chartRef.current.removeSeries(compareSeriesRef.current); } catch {}
          compareSeriesRef.current = null;
        }
        return;
      }

      const commonStart = Math.max(toTime(bars[0].t), toTime(compareBars[0].t));
      const mainRef = bars.find((b) => toTime(b.t) >= commonStart)?.c;
      const compareRef = compareBars.find((b) => toTime(b.t) >= commonStart)?.c;
      if (!mainRef || !compareRef) return;

      const normalized = compareBars
        .filter((b) => toTime(b.t) >= commonStart)
        .map((b) => ({ time: toTime(b.t), value: mainRef * (b.c / compareRef) }));

      if (!compareSeriesRef.current) {
        compareSeriesRef.current = chartRef.current.addSeries(LineSeries, {
          color: "#f59e0b",
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: false,
          title: compareSymbol ?? "",
        });
      }
      compareSeriesRef.current.setData(normalized);
    }, [compareBars, compareSymbol, bars]);

    const rectOverlays = useMemo(() => {
      if (!chartRef.current || !mainSeriesRef.current) return [];
      const tc = chartRef.current.timeScale();
      const ser = mainSeriesRef.current as ISeriesApi<"Candlestick">;
      return drawings
        .filter((d) => d.type === "rect" && d.p1 && d.p2)
        .flatMap((d) => {
          const x1 = tc.timeToCoordinate(d.p1!.time as UTCTimestamp);
          const x2 = tc.timeToCoordinate(d.p2!.time as UTCTimestamp);
          const y1 = ser.priceToCoordinate(d.p1!.price);
          const y2 = ser.priceToCoordinate(d.p2!.price);
          if (x1 === null || x2 === null || y1 === null || y2 === null) return [];
          return [{ id: d.id, x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1), color: d.color }];
        });
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [overlayVersion, drawings]);

    const cursor = activeTool === "cursor" ? "default" : activeTool === "eraser" ? "not-allowed" : "crosshair";

    return (
      <div className="w-full h-full relative">
        <div ref={containerRef} className="absolute inset-0" style={{ cursor }} />
        {rectOverlays.length > 0 && (
          <svg className="absolute inset-0 w-full h-full pointer-events-none overflow-visible">
            {rectOverlays.map((r) => (
              <rect
                key={r.id}
                x={r.x} y={r.y} width={r.w} height={r.h}
                fill={r.color + "22"} stroke={r.color} strokeWidth={1}
              />
            ))}
          </svg>
        )}
      </div>
    );
  }
);

CandlestickChart.displayName = "CandlestickChart";
export default CandlestickChart;

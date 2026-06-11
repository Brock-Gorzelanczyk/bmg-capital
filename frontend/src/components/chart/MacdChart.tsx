import { useEffect, useRef } from "react";
import { createChart, LineSeries, HistogramSeries, ColorType } from "lightweight-charts";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import type { Bar } from "@/types/market";
import ExplainButton from "@/components/explain/ExplainButton";

interface Props {
  bars: Bar[];
  macdLine: (number | null)[];
  macdSignal: (number | null)[];
  macdHist: (number | null)[];
  height?: number;
}

const toTime = (t: string) => Math.floor(new Date(t).getTime() / 1000) as UTCTimestamp;

export default function MacdChart({ bars, macdLine, macdSignal, macdHist, height = 100 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const histRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const lineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const signalRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#18181B" }, textColor: "#A1A1AA" },
      grid: { vertLines: { color: "rgba(255,255,255,0.04)" }, horzLines: { color: "rgba(255,255,255,0.04)" } },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: "#1f1f1f", scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: "#1f1f1f", visible: false },
      autoSize: true,
    });

    histRef.current = chart.addSeries(HistogramSeries, { color: "#4ade8028", priceLineVisible: false, lastValueVisible: false });
    lineRef.current = chart.addSeries(LineSeries, { color: "#ec4899", lineWidth: 1, priceLineVisible: false, lastValueVisible: true });
    signalRef.current = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1, priceLineVisible: false, lastValueVisible: true });
    chartRef.current = chart;

    return () => {
      chart.remove();
      chartRef.current = null; histRef.current = null; lineRef.current = null; signalRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!bars.length || !histRef.current || !lineRef.current || !signalRef.current) return;
    const n = Math.min(bars.length, macdHist.length, macdLine.length, macdSignal.length);

    histRef.current.setData(
      bars.slice(0, n)
        .map((b, i) => {
          const v = macdHist[i];
          return v != null ? { time: toTime(b.t), value: v, color: v >= 0 ? "#4ade8040" : "#FB718566" } : null;
        })
        .filter(Boolean) as { time: ReturnType<typeof toTime>; value: number; color: string }[]
    );

    lineRef.current.setData(
      bars.slice(0, n).map((b, i) => ({ time: toTime(b.t), value: macdLine[i] }))
        .filter((d): d is { time: ReturnType<typeof toTime>; value: number } => d.value != null)
    );

    signalRef.current.setData(
      bars.slice(0, n).map((b, i) => ({ time: toTime(b.t), value: macdSignal[i] }))
        .filter((d): d is { time: ReturnType<typeof toTime>; value: number } => d.value != null)
    );

    chartRef.current?.timeScale().fitContent();
  }, [bars, macdLine, macdSignal, macdHist]);

  return (
    <div className="border-t border-[var(--border-subtle)] shrink-0" style={{ height }}>
      <div className="px-2 py-0.5 text-[10px] text-[#555] font-medium flex items-center justify-between">
        <div className="flex gap-3 items-center">
          <span>MACD (12,26,9)</span>
          <span className="text-pink-400">— MACD</span>
          <span className="text-blue-400">— Signal</span>
        </div>
        <ExplainButton term="MACD" className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)]" size={11} />
      </div>
      <div ref={containerRef} style={{ height: height - 18, width: "100%" }} />
    </div>
  );
}

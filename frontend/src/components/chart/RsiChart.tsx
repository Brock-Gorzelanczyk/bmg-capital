import { useEffect, useRef } from "react";
import { createChart, LineSeries, ColorType } from "lightweight-charts";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import type { Bar } from "@/types/market";
import ExplainButton from "@/components/explain/ExplainButton";

interface Props {
  bars: Bar[];
  values: (number | null)[];
  height?: number;
}

const toTime = (t: string) => Math.floor(new Date(t).getTime() / 1000) as UTCTimestamp;

export default function RsiChart({ bars, values, height = 100 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#0a0a0a" }, textColor: "#d4d4d4" },
      grid: { vertLines: { color: "#111111" }, horzLines: { color: "#111111" } },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: "#1f1f1f", scaleMargins: { top: 0.05, bottom: 0.05 } },
      timeScale: { borderColor: "#1f1f1f", timeVisible: false, visible: false, fixLeftEdge: true, fixRightEdge: true },
      autoSize: true,
    });

    const series = chart.addSeries(LineSeries, {
      color: "#22c55e", lineWidth: 1, priceLineVisible: false, lastValueVisible: true,
    });
    series.createPriceLine({ price: 70, color: "#ef5350", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "OB" });
    series.createPriceLine({ price: 50, color: "#1f1f1f", lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
    series.createPriceLine({ price: 30, color: "#26a69a", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "OS" });

    chartRef.current = chart;
    seriesRef.current = series;
    return () => { chart.remove(); chartRef.current = null; seriesRef.current = null; };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || !bars.length) return;
    const n = Math.min(bars.length, values.length);
    const data = bars.slice(0, n)
      .map((b, i) => ({ time: toTime(b.t), value: values[i] }))
      .filter((d): d is { time: ReturnType<typeof toTime>; value: number } => d.value != null);
    seriesRef.current.setData(data);
    chartRef.current?.timeScale().fitContent();
  }, [bars, values]);

  return (
    <div className="border-t border-[#1f1f1f] shrink-0" style={{ height }}>
      <div className="px-2 py-0.5 text-[10px] text-[#555] font-medium flex items-center justify-between">
        <span>RSI (14)</span>
        <ExplainButton term="RSI (Relative Strength Index)" className="text-[#4a4e5b] hover:text-[#d1d4dc]" size={11} />
      </div>
      <div ref={containerRef} style={{ height: height - 18, width: "100%" }} />
    </div>
  );
}

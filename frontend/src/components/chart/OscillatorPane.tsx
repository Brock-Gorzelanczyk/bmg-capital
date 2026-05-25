import { useEffect, useRef } from "react";
import { createChart, LineSeries, ColorType, LineStyle } from "lightweight-charts";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import type { Bar } from "@/types/market";
import ExplainButton from "@/components/explain/ExplainButton";

interface LevelLine {
  price: number;
  color: string;
}

interface Props {
  bars: Bar[];
  line1: (number | null)[];
  color1: string;
  label1?: string;
  line2?: (number | null)[];
  color2?: string;
  label2?: string;
  levels?: LevelLine[];
  title: string;
  height?: number;
  explainTerm?: string;
}

const toTime = (t: string) => Math.floor(new Date(t).getTime() / 1000) as UTCTimestamp;

export default function OscillatorPane({
  bars, line1, color1, label1, line2, color2, label2,
  levels = [], title, height = 100, explainTerm,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const s1Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const s2Ref = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#0a0a0a" }, textColor: "#d4d4d4" },
      grid: { vertLines: { color: "#111111" }, horzLines: { color: "#111111" } },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: "#1f1f1f", scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: "#1f1f1f", visible: false, fixLeftEdge: true, fixRightEdge: true },
      autoSize: true,
    });

    const s1 = chart.addSeries(LineSeries, {
      color: color1, lineWidth: 1, priceLineVisible: false, lastValueVisible: true,
    });
    levels.forEach((l) =>
      s1.createPriceLine({
        price: l.price, color: l.color, lineWidth: 1,
        lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "",
      })
    );
    s1Ref.current = s1;

    if (color2) {
      s2Ref.current = chart.addSeries(LineSeries, {
        color: color2, lineWidth: 1, priceLineVisible: false, lastValueVisible: true,
      });
    }

    chartRef.current = chart;

    return () => {
      chart.remove();
      chartRef.current = null;
      s1Ref.current = null;
      s2Ref.current = null;
    };
  }, []);

  useEffect(() => {
    if (!bars.length || !s1Ref.current) return;
    const n1 = Math.min(bars.length, line1.length);
    s1Ref.current.setData(
      bars.slice(0, n1)
        .map((b, i) => ({ time: toTime(b.t), value: line1[i] }))
        .filter((d): d is { time: ReturnType<typeof toTime>; value: number } => d.value != null)
    );
    if (s2Ref.current && line2) {
      const n2 = Math.min(bars.length, line2.length);
      s2Ref.current.setData(
        bars.slice(0, n2)
          .map((b, i) => ({ time: toTime(b.t), value: line2[i] }))
          .filter((d): d is { time: ReturnType<typeof toTime>; value: number } => d.value != null)
      );
    }
    chartRef.current?.timeScale().fitContent();
  }, [bars, line1, line2]);

  return (
    <div className="border-t border-[#1f1f1f] shrink-0" style={{ height }}>
      <div className="px-2 py-0.5 text-[10px] text-[#555] font-medium flex items-center justify-between">
        <div className="flex gap-3 items-center">
          <span>{title}</span>
          {label1 && <span style={{ color: color1 }}>— {label1}</span>}
          {label2 && color2 && <span style={{ color: color2 }}>— {label2}</span>}
        </div>
        {explainTerm && (
          <ExplainButton term={explainTerm} className="text-[#4a4e5b] hover:text-[#d1d4dc]" size={11} />
        )}
      </div>
      <div ref={containerRef} style={{ height: height - 18, width: "100%" }} />
    </div>
  );
}

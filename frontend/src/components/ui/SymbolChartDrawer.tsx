import { useMemo } from "react";
import { X, ExternalLink } from "lucide-react";
import {
  ComposedChart,
  Area,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  CartesianGrid,
} from "recharts";
import { useBars } from "@/hooks/useBars";
import type { Bar as OHLCVBar } from "@/types/market";

// ─── Props ────────────────────────────────────────────────────────────────────

export interface SymbolChartDrawerProps {
  symbol: string | null;   // null = closed
  onClose: () => void;
  entryPrice?: number;     // for positions — mark on chart
  stopPrice?: number;      // for positions — mark on chart (red)
  targetPrice?: number;    // for positions — mark on chart (green)
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function threeMonthsAgoISO(): string {
  const d = new Date();
  d.setMonth(d.getMonth() - 3);
  return d.toISOString().slice(0, 10);
}

function fmtPrice(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(n: number): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function fmtVol(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

// ─── Stats computation ────────────────────────────────────────────────────────

interface Stats {
  lastPrice: number;
  change1d: number;
  high52w: number;
  low52w: number;
}

function computeStats(bars: OHLCVBar[]): Stats | null {
  if (!bars || bars.length === 0) return null;
  const last = bars[bars.length - 1];
  const prev = bars.length >= 2 ? bars[bars.length - 2] : null;
  const change1d = prev ? ((last.c - prev.c) / prev.c) * 100 : 0;
  const highs = bars.map((b) => b.h);
  const lows = bars.map((b) => b.l);
  return {
    lastPrice: last.c,
    change1d,
    high52w: Math.max(...highs),
    low52w: Math.min(...lows),
  };
}

// ─── Chart data shape ─────────────────────────────────────────────────────────

interface ChartPoint {
  date: string;
  close: number;
  volume: number;
}

function toChartData(bars: OHLCVBar[]): ChartPoint[] {
  return bars.map((b) => ({
    date: b.t.slice(5, 10), // "MM-DD"
    close: b.c,
    volume: b.v,
  }));
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function SymbolChartDrawer({
  symbol,
  onClose,
  entryPrice,
  stopPrice,
  targetPrice,
}: SymbolChartDrawerProps) {
  const isOpen = symbol !== null;
  const start = useMemo(() => threeMonthsAgoISO(), []);

  const { data, isLoading } = useBars(symbol ?? "", "1Day", undefined, start);

  const bars = data?.bars ?? [];
  const chartData = useMemo(() => toChartData(bars), [bars]);
  const stats = useMemo(() => computeStats(bars), [bars]);

  const closePrices = chartData.map((d) => d.close);
  const minClose = closePrices.length ? Math.min(...closePrices) : 0;
  const maxClose = closePrices.length ? Math.max(...closePrices) : 0;
  const priceDomain: [number, number] = [minClose * 0.995, maxClose * 1.005];

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-40"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Panel */}
      <div
        className={[
          "fixed top-0 right-0 h-full w-full sm:w-[420px]",
          "bg-[var(--bg-elevated)] border-l border-[var(--border-subtle)]",
          "z-50 flex flex-col shadow-2xl",
          "transition-transform duration-300",
          isOpen ? "translate-x-0" : "translate-x-full",
        ].join(" ")}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)] shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-white font-bold text-lg tracking-tight">
              {symbol ?? ""}
            </span>
            {stats && (
              <span
                className={[
                  "text-sm font-semibold",
                  stats.change1d >= 0 ? "text-[#26a69a]" : "text-[#ef5350]",
                ].join(" ")}
              >
                {fmtPct(stats.change1d)}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {symbol && (
              <a
                href={`/chart?symbol=${encodeURIComponent(symbol)}`}
                className="flex items-center gap-1 text-xs text-[var(--text-tertiary)] hover:text-[var(--accent-positive)] transition-colors"
              >
                Open full chart
                <ExternalLink size={12} />
              </a>
            )}
            <button
              onClick={onClose}
              className="text-[var(--text-tertiary)] hover:text-white transition-colors p-1"
              aria-label="Close chart"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {isLoading ? (
            <div className="space-y-3 animate-pulse">
              <div className="h-40 bg-[var(--bg-elevated-2)] rounded-xl" />
              <div className="h-16 bg-[var(--bg-elevated-2)] rounded-xl" />
              <div className="grid grid-cols-4 gap-2">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="h-14 bg-[var(--bg-elevated-2)] rounded-lg" />
                ))}
              </div>
            </div>
          ) : chartData.length === 0 ? (
            <div className="flex items-center justify-center h-40 text-[var(--text-tertiary)] text-sm">
              No chart data available
            </div>
          ) : (
            <>
              {/* Price area chart */}
              <div>
                <ResponsiveContainer width="100%" height={160}>
                  <ComposedChart data={chartData} margin={{ top: 4, right: 0, left: -20, bottom: 0 }}>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="rgba(255,255,255,0.04)"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 9, fill: "#71717a" }}
                      tickLine={false}
                      axisLine={false}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      domain={priceDomain}
                      tick={{ fontSize: 9, fill: "#71717a" }}
                      tickLine={false}
                      axisLine={false}
                      tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                      width={45}
                    />
                    <Tooltip
                      contentStyle={{
                        background: "#18181b",
                        border: "1px solid #3f3f46",
                        borderRadius: 8,
                        fontSize: 11,
                      }}
                      formatter={(v: number) => [`$${fmtPrice(v)}`, "Close"]}
                    />
                    <defs>
                      <linearGradient id="closeGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#26a69a" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#26a69a" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <Area
                      type="monotone"
                      dataKey="close"
                      stroke="#26a69a"
                      strokeWidth={2}
                      fill="url(#closeGrad)"
                      dot={false}
                      activeDot={{ r: 3 }}
                    />

                    {/* Reference lines for position levels */}
                    {entryPrice != null && (
                      <ReferenceLine
                        y={entryPrice}
                        stroke="#a78bfa"
                        strokeDasharray="4 3"
                        strokeWidth={1.5}
                        label={{ value: `Entry $${fmtPrice(entryPrice)}`, fontSize: 9, fill: "#a78bfa", position: "insideTopRight" }}
                      />
                    )}
                    {stopPrice != null && (
                      <ReferenceLine
                        y={stopPrice}
                        stroke="#ef5350"
                        strokeDasharray="4 3"
                        strokeWidth={1.5}
                        label={{ value: `Stop $${fmtPrice(stopPrice)}`, fontSize: 9, fill: "#ef5350", position: "insideBottomRight" }}
                      />
                    )}
                    {targetPrice != null && (
                      <ReferenceLine
                        y={targetPrice}
                        stroke="#26a69a"
                        strokeDasharray="4 3"
                        strokeWidth={1.5}
                        label={{ value: `Target $${fmtPrice(targetPrice)}`, fontSize: 9, fill: "#26a69a", position: "insideTopRight" }}
                      />
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
              </div>

              {/* Volume bar chart */}
              <div>
                <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">Volume</p>
                <ResponsiveContainer width="100%" height={60}>
                  <ComposedChart data={chartData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                    <XAxis dataKey="date" hide />
                    <YAxis
                      tick={{ fontSize: 8, fill: "#71717a" }}
                      tickLine={false}
                      axisLine={false}
                      tickFormatter={fmtVol}
                      width={35}
                    />
                    <Bar dataKey="volume" fill="#3f3f46" radius={[2, 2, 0, 0]} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>

              {/* Key stats */}
              {stats && (
                <div className="grid grid-cols-4 gap-2 pt-2 border-t border-[var(--border-subtle)]">
                  {[
                    { label: "Last", value: `$${fmtPrice(stats.lastPrice)}` },
                    {
                      label: "1D Chg",
                      value: fmtPct(stats.change1d),
                      color: stats.change1d >= 0 ? "text-[#26a69a]" : "text-[#ef5350]",
                    },
                    { label: "52W Hi", value: `$${fmtPrice(stats.high52w)}` },
                    { label: "52W Lo", value: `$${fmtPrice(stats.low52w)}` },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="bg-[var(--bg-elevated-2)] rounded-lg px-2 py-2">
                      <p className="text-[10px] text-[var(--text-tertiary)] mb-0.5">{label}</p>
                      <p className={["text-xs font-semibold text-[var(--text-primary)]", color ?? ""].join(" ")}>
                        {value}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}

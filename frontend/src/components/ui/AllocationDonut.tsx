import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { cn } from "@/lib/utils";

const SLICE_COLORS: Record<string, string> = {
  crypto:  "#9333EA",
  stocks:  "#10B981",
  options: "#F97316",
  quant:   "#6366F1",
  cash:    "#94A3B8",
};

const SLICE_LABELS: Record<string, string> = {
  crypto:  "Crypto",
  stocks:  "Stocks",
  options: "Options",
  quant:   "Quant",
  cash:    "Cash",
};

export interface AllocationSlice {
  key: string;
  value_cents: number;
}

export interface LiveAllocationSlice {
  key: string;
  label: string;
  dollars: number;
  pct: number;
  color: string;
  position_count: number;
}

interface Props {
  slices?: AllocationSlice[];
  liveSlices?: LiveAllocationSlice[];
  totalCents?: number;
  size?: number;
  compact?: boolean;
  updatedAt?: Date | null;
}

function fmtDollars(usd: number): string {
  if (usd >= 1_000_000) return `$${(usd / 1_000_000).toFixed(2)}M`;
  if (usd >= 1_000)     return `$${(usd / 1_000).toFixed(1)}k`;
  return `$${usd.toFixed(0)}`;
}

function fmt(cents: number): string {
  return fmtDollars(cents / 100);
}

function secsAgo(d: Date): string {
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  return `${Math.floor(s / 60)}m ago`;
}

export default function AllocationDonut({
  slices,
  liveSlices,
  totalCents,
  size = 140,
  compact = false,
  updatedAt,
}: Props) {
  // Build unified data array — prefer liveSlices when provided
  const data = liveSlices
    ? liveSlices.filter((s) => s.dollars > 0).map((s) => ({
        name: s.label,
        key: s.key,
        value: s.dollars,
        pct: s.pct,
        color: s.color,
        position_count: s.position_count,
        isLive: true,
      }))
    : (slices ?? []).filter((s) => s.value_cents > 0).map((s) => ({
        name: SLICE_LABELS[s.key] ?? s.key,
        key: s.key,
        value: s.value_cents / 100,
        pct: totalCents && totalCents > 0 ? (s.value_cents / totalCents) * 100 : 0,
        color: SLICE_COLORS[s.key] ?? "#6B7280",
        position_count: 0,
        isLive: false,
      }));

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-24 text-zinc-600 text-xs">
        No allocation data
      </div>
    );
  }

  const total = liveSlices
    ? liveSlices.reduce((acc, s) => acc + s.dollars, 0)
    : (totalCents ?? 0) / 100;

  return (
    <div className={cn("flex items-center gap-4", compact ? "gap-3" : "gap-5")}>
      {/* Donut */}
      <div style={{ width: size, height: size, flexShrink: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={size * 0.3}
              outerRadius={size * 0.46}
              paddingAngle={2}
              dataKey="value"
              strokeWidth={0}
            >
              {data.map((entry) => (
                <Cell key={entry.key} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip
              formatter={(value: number, name: string, props: any) => {
                const entry = props?.payload;
                const pct = entry?.pct != null ? entry.pct.toFixed(1) : ((value / (total || 1)) * 100).toFixed(1);
                const pos = entry?.position_count;
                const posLabel = pos != null && pos > 0 ? ` · ${pos} position${pos === 1 ? "" : "s"}` : "";
                return [`${fmtDollars(value)} (${pct}%)${posLabel}`, name];
              }}
              contentStyle={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, fontSize: 11 }}
              itemStyle={{ color: "#d4d4d8" }}
              labelStyle={{ display: "none" }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>

      {/* Legend + timestamp */}
      <div className="flex flex-col gap-1.5 min-w-0 flex-1">
        {data.map((entry) => {
          const pct = entry.pct.toFixed(1);
          const dollarsStr = fmtDollars(entry.value);
          return (
            <div key={entry.key} className="flex items-center gap-1.5 min-w-0">
              <span
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ background: entry.color }}
              />
              <span className={cn("text-zinc-400 truncate", compact ? "text-[10px]" : "text-xs")}>
                {entry.name}
              </span>
              <span className={cn("text-zinc-300 font-semibold tabular-nums flex-shrink-0", compact ? "text-[10px]" : "text-xs")}>
                {pct}%
              </span>
              {!compact && (
                <span className="text-zinc-500 tabular-nums text-xs ml-auto flex-shrink-0 font-mono-t pl-3">
                  {dollarsStr}
                </span>
              )}
            </div>
          );
        })}
        {updatedAt && !compact && (
          <p className="text-[10px] text-zinc-600 mt-1">Updated {secsAgo(updatedAt)}</p>
        )}
      </div>
    </div>
  );
}

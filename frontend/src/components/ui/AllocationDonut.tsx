import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { cn } from "@/lib/utils";

const SLICE_COLORS: Record<string, string> = {
  crypto:  "#9333EA",
  stocks:  "#10B981",
  options: "#F97316",
  quant:   "#6366F1",
  cash:    "#4B5563",
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

interface Props {
  slices: AllocationSlice[];
  totalCents: number;
  size?: number;
  compact?: boolean;
}

function fmt(cents: number): string {
  const usd = cents / 100;
  if (usd >= 1_000_000) return `$${(usd / 1_000_000).toFixed(2)}M`;
  if (usd >= 1_000)     return `$${(usd / 1_000).toFixed(1)}k`;
  return `$${usd.toFixed(0)}`;
}

export default function AllocationDonut({ slices, totalCents, size = 140, compact = false }: Props) {
  const data = slices.filter((s) => s.value_cents > 0).map((s) => ({
    name: SLICE_LABELS[s.key] ?? s.key,
    key: s.key,
    value: s.value_cents,
  }));

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-24 text-zinc-600 text-xs">
        No allocation data
      </div>
    );
  }

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
                <Cell key={entry.key} fill={SLICE_COLORS[entry.key] ?? "#6B7280"} />
              ))}
            </Pie>
            <Tooltip
              formatter={(value: number, name: string) => [
                `${fmt(value)} (${((value / totalCents) * 100).toFixed(1)}%)`,
                name,
              ]}
              contentStyle={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, fontSize: 11 }}
              itemStyle={{ color: "#d4d4d8" }}
              labelStyle={{ display: "none" }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div className="flex flex-col gap-1.5 min-w-0">
        {data.map((entry) => {
          const pct = ((entry.value / totalCents) * 100).toFixed(1);
          return (
            <div key={entry.key} className="flex items-center gap-1.5 min-w-0">
              <span
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ background: SLICE_COLORS[entry.key] ?? "#6B7280" }}
              />
              <span className={cn("text-zinc-400 truncate", compact ? "text-[10px]" : "text-xs")}>
                {entry.name}
              </span>
              <span className={cn("text-zinc-300 font-semibold tabular-nums ml-auto pl-2 flex-shrink-0", compact ? "text-[10px]" : "text-xs")}>
                {pct}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

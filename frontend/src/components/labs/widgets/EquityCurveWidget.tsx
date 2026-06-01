import { useQuery } from "@tanstack/react-query";
import type { IDockviewPanelProps } from "dockview";
import { getEquity } from "@/api/strategy";

interface EquityPoint {
  date: string;
  portfolio_value: number;
}

const fmt$ = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 0, maximumFractionDigits: 0 });

export default function EquityCurveWidget(_props: IDockviewPanelProps) {
  const { data, isLoading, error } = useQuery<{ equity: EquityPoint[]; baseline: number }>({
    queryKey: ["strategy-equity"],
    queryFn: getEquity,
    staleTime: 30_000,
  });

  const points: EquityPoint[] = data?.equity ?? [];
  const baseline = data?.baseline ?? 100_000;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full bg-[var(--bg-elevated)] text-[var(--text-tertiary)] text-xs">
        Loading chart…
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full bg-[var(--bg-elevated)] text-red-400 text-xs">
        Failed to load equity data
      </div>
    );
  }

  if (points.length < 2) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-[var(--bg-elevated)] gap-1 text-[var(--text-tertiary)]">
        <span className="text-2xl">📈</span>
        <span className="text-xs">Not enough data yet</span>
        <span className="text-[10px] opacity-60">Need at least 2 snapshots</span>
      </div>
    );
  }

  const values = points.map((p) => p.portfolio_value);
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = maxVal - minVal || 1;

  const W = 400;
  const H = 120;
  const PAD = { top: 8, right: 8, bottom: 20, left: 50 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;

  const toX = (i: number) => PAD.left + (i / (points.length - 1)) * chartW;
  const toY = (v: number) => PAD.top + (1 - (v - minVal) / range) * chartH;

  const pathD = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${toX(i)} ${toY(p.portfolio_value)}`)
    .join(" ");

  const fillD = `${pathD} L ${toX(points.length - 1)} ${H - PAD.bottom} L ${PAD.left} ${H - PAD.bottom} Z`;

  const lastVal = values[values.length - 1];
  const isPositive = lastVal >= baseline;
  const accentColor = isPositive ? "var(--accent-positive)" : "var(--accent-negative)";
  const accentHex = isPositive ? "#22c55e" : "#ef4444";

  const pctReturn = ((lastVal - baseline) / baseline) * 100;

  // Label every ~30% width worth of points
  const labelStep = Math.max(1, Math.floor(points.length / 4));
  const labelPoints = points.filter((_, i) => i === 0 || i === points.length - 1 || i % labelStep === 0);

  return (
    <div className="flex flex-col h-full bg-[var(--bg-elevated)] text-[var(--text-primary)]">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-subtle)]">
        <span className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">
          Equity Curve
        </span>
        <span
          style={{ color: accentColor }}
          className="text-xs font-mono font-bold"
        >
          {pctReturn >= 0 ? "+" : ""}{pctReturn.toFixed(2)}% · {fmt$(lastVal)}
        </span>
      </div>

      {/* SVG chart */}
      <div className="flex-1 flex items-center justify-center px-2 pb-2 overflow-hidden">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          className="w-full h-full"
          style={{ maxHeight: 200 }}
        >
          <defs>
            <linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={accentHex} stopOpacity="0.25" />
              <stop offset="100%" stopColor={accentHex} stopOpacity="0.02" />
            </linearGradient>
          </defs>

          {/* Fill */}
          <path d={fillD} fill="url(#equity-fill)" />

          {/* Line */}
          <path
            d={pathD}
            fill="none"
            stroke={accentHex}
            strokeWidth="1.5"
            strokeLinejoin="round"
          />

          {/* Baseline */}
          <line
            x1={PAD.left}
            y1={toY(baseline)}
            x2={W - PAD.right}
            y2={toY(baseline)}
            stroke="#555"
            strokeWidth="0.5"
            strokeDasharray="4,4"
          />

          {/* Y-axis labels */}
          {[minVal, (minVal + maxVal) / 2, maxVal].map((v) => (
            <text
              key={v}
              x={PAD.left - 4}
              y={toY(v) + 3}
              textAnchor="end"
              fontSize="7"
              fill="#666"
            >
              {fmt$(v)}
            </text>
          ))}

          {/* X-axis labels */}
          {labelPoints.map((p) => {
            const i = points.indexOf(p);
            return (
              <text
                key={p.date}
                x={toX(i)}
                y={H - 4}
                textAnchor="middle"
                fontSize="6"
                fill="#555"
              >
                {p.date.slice(5)}
              </text>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

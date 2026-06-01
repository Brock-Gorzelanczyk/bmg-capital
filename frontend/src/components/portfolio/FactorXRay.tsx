import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Info, ChevronDown, ChevronUp, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import client from "@/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FactorScore {
  name: string;
  score: number;
  label: "High" | "Moderate" | "Low";
}

interface FactorExposureData {
  factors: FactorScore[];
  insight: string;
  top_factors: string[];
  concentration_pct: number;
}

// ---------------------------------------------------------------------------
// Factor explanations
// ---------------------------------------------------------------------------

const FACTOR_DESCRIPTIONS: Record<string, string> = {
  "Value":
    "How cheaply-valued your portfolio is. High Value = low P/E sectors (Energy, Financials). Low Value = expensive growth names like Tech.",
  "Momentum":
    "The percentage of your positions that are currently winning (positive gain). High Momentum = most positions up.",
  "Quality":
    "Exposure to 'quality' sectors — Healthcare, Technology, and Financials — known for strong balance sheets and earnings durability.",
  "Low-Vol":
    "How low-beta your portfolio is. High score = defensive names like Utilities and Consumer Staples. Low score = volatile sectors like Tech and Energy.",
  "USD-Beta":
    "Sensitivity to a rising US dollar. High score = heavy in global exporters (Tech, Energy, Consumer Staples). A strong USD hurts their overseas revenue.",
  "Crypto-Beta":
    "Exposure to crypto-correlated names. Standard equity portfolios score near 0 here.",
  "Tech-Growth":
    "Portfolio weight in Technology and Communication Services — high-multiple, growth-oriented sectors.",
  "Concentration":
    "How concentrated your portfolio is. Computed via HHI (sum of squared weights). High = a few positions dominate your risk.",
};

const FACTOR_COLORS: Record<string, string> = {
  High:     "#EF4444",
  Moderate: "#F59E0B",
  Low:      "#22C55E",
};

// ---------------------------------------------------------------------------
// SVG Radar Chart
// ---------------------------------------------------------------------------

interface RadarChartProps {
  factors: FactorScore[];
  size?: number;
}

function RadarChart({ factors, size = 260 }: RadarChartProps) {
  if (factors.length === 0) return null;

  const cx = size / 2;
  const cy = size / 2;
  const maxRadius = size / 2 - 36;
  const n = factors.length;

  // Helper: angle for axis i (start at top, go clockwise)
  function axisAngle(i: number) {
    return (i / n) * 2 * Math.PI - Math.PI / 2;
  }

  // Point on axis at a given fraction (0–1)
  function axisPoint(i: number, frac: number) {
    const angle = axisAngle(i);
    return {
      x: cx + frac * maxRadius * Math.cos(angle),
      y: cy + frac * maxRadius * Math.sin(angle),
    };
  }

  // Grid rings at 25%, 50%, 75%, 100%
  const rings = [0.25, 0.5, 0.75, 1.0];

  // Build grid ring polygons
  function ringPath(frac: number) {
    const pts = factors.map((_, i) => axisPoint(i, frac));
    return pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ") + "Z";
  }

  // Data polygon
  const dataPts = factors.map((f, i) => axisPoint(i, f.score / 100));
  const dataPath =
    dataPts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ") + "Z";

  // Axis tip labels — push slightly beyond maxRadius
  const LABEL_OFFSET = 1.18;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="shrink-0 overflow-visible"
      aria-label="Factor exposure radar chart"
    >
      {/* Grid rings */}
      {rings.map((frac, ri) => (
        <path
          key={ri}
          d={ringPath(frac)}
          fill="none"
          stroke="var(--border-subtle)"
          strokeWidth={frac === 1.0 ? 1.5 : 1}
          opacity={0.6}
        />
      ))}

      {/* Axes */}
      {factors.map((_, i) => {
        const tip = axisPoint(i, 1.0);
        return (
          <line
            key={i}
            x1={cx} y1={cy}
            x2={tip.x.toFixed(2)} y2={tip.y.toFixed(2)}
            stroke="var(--border-subtle)"
            strokeWidth={1}
            opacity={0.5}
          />
        );
      })}

      {/* Filled data polygon */}
      <path
        d={dataPath}
        fill="rgba(59,130,246,0.18)"
        stroke="#3B82F6"
        strokeWidth={2}
        strokeLinejoin="round"
      />

      {/* Data points */}
      {dataPts.map((p, i) => (
        <circle
          key={i}
          cx={p.x.toFixed(2)}
          cy={p.y.toFixed(2)}
          r={3}
          fill="#3B82F6"
        />
      ))}

      {/* Axis tip labels */}
      {factors.map((f, i) => {
        const angle = axisAngle(i);
        const lx = cx + LABEL_OFFSET * maxRadius * Math.cos(angle);
        const ly = cy + LABEL_OFFSET * maxRadius * Math.sin(angle);

        // Anchor: left side → start, right side → end, center → middle
        const anchor =
          Math.cos(angle) > 0.3
            ? "start"
            : Math.cos(angle) < -0.3
            ? "end"
            : "middle";

        const baseline =
          Math.sin(angle) > 0.3
            ? "hanging"
            : Math.sin(angle) < -0.3
            ? "auto"
            : "middle";

        return (
          <text
            key={i}
            x={lx.toFixed(2)}
            y={ly.toFixed(2)}
            textAnchor={anchor}
            dominantBaseline={baseline}
            fontSize={9.5}
            fontFamily="Inter, sans-serif"
            fontWeight={600}
            fill={f.label === "High" ? "#EF4444" : f.label === "Moderate" ? "#F59E0B" : "var(--text-secondary)"}
          >
            {f.name}
          </text>
        );
      })}

      {/* Score tick at each axis tip */}
      {factors.map((f, i) => {
        const angle = axisAngle(i);
        const lx = cx + (LABEL_OFFSET + 0.12) * maxRadius * Math.cos(angle);
        const ly = cy + (LABEL_OFFSET + 0.12) * maxRadius * Math.sin(angle);
        const anchor =
          Math.cos(angle) > 0.3
            ? "start"
            : Math.cos(angle) < -0.3
            ? "end"
            : "middle";
        return (
          <text
            key={`score-${i}`}
            x={lx.toFixed(2)}
            y={ly.toFixed(2)}
            textAnchor={anchor}
            dominantBaseline="middle"
            fontSize={8}
            fontFamily="JetBrains Mono, monospace"
            fill="var(--text-tertiary)"
          >
            {f.score.toFixed(0)}
          </text>
        );
      })}

      {/* Center label */}
      <text
        x={cx}
        y={cy}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={9}
        fill="var(--text-tertiary)"
        fontFamily="Inter, sans-serif"
      >
        Factor
      </text>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Factor Badge row
// ---------------------------------------------------------------------------

function FactorRow({ factor, expanded, onToggle }: {
  factor: FactorScore;
  expanded: boolean;
  onToggle: () => void;
}) {
  const color = FACTOR_COLORS[factor.label];
  const barWidth = factor.score;

  return (
    <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-[var(--bg-elevated-2)]/40 transition-colors cursor-pointer text-left"
      >
        {/* Bar */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-semibold text-[var(--text-primary)]">{factor.name}</span>
            <div className="flex items-center gap-1.5">
              <span
                className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                style={{ color, backgroundColor: color + "22" }}
              >
                {factor.label}
              </span>
              <span className="font-mono text-xs text-[var(--text-secondary)]">
                {factor.score.toFixed(0)}/100
              </span>
            </div>
          </div>
          <div className="h-1.5 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{ width: `${barWidth}%`, backgroundColor: color }}
            />
          </div>
        </div>
        <Info size={13} className="text-[var(--text-tertiary)] shrink-0" />
        {expanded
          ? <ChevronUp size={12} className="text-[var(--text-tertiary)] shrink-0" />
          : <ChevronDown size={12} className="text-[var(--text-tertiary)] shrink-0" />
        }
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-1 bg-[var(--bg-elevated-2)]/20 border-t border-[var(--border-subtle)]/60">
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
            {FACTOR_DESCRIPTIONS[factor.name] ?? "No description available."}
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface FactorXRayProps {
  portfolioId: number;
}

export default function FactorXRay({ portfolioId }: FactorXRayProps) {
  const [expandedFactor, setExpandedFactor] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery<FactorExposureData>({
    queryKey: ["factor-exposure", portfolioId],
    queryFn: async () => {
      const res = await client.get<FactorExposureData>(
        `/portfolio/${portfolioId}/factor-exposure`
      );
      return res.data;
    },
    staleTime: 60_000,
    enabled: portfolioId > 0,
  });

  if (isLoading) {
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-10 rounded-lg bg-[var(--bg-elevated-2)] animate-pulse" />
        ))}
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="px-4 py-8 text-center text-[var(--text-tertiary)] text-sm">
        Factor exposure unavailable — add positions to your portfolio first.
      </div>
    );
  }

  if (!data.factors || data.factors.length === 0) {
    return (
      <div className="px-4 py-8 text-center text-[var(--text-tertiary)] text-sm">
        No positions to analyze.
      </div>
    );
  }

  return (
    <div className="px-4 py-5 space-y-5">
      {/* Radar + insight row */}
      <div className="flex flex-col md:flex-row gap-6 items-start">
        {/* Radar */}
        <div className="flex justify-center w-full md:w-auto">
          <RadarChart factors={data.factors ?? []} size={260} />
        </div>

        {/* Right side: insight + top factors */}
        <div className="flex-1 space-y-4">
          {/* Insight card */}
          <div className="bg-[var(--bg-elevated-2)] border border-[#3B82F6]/30 rounded-xl p-4">
            <div className="flex items-start gap-2.5">
              <Zap size={16} className="text-[#3B82F6] shrink-0 mt-0.5" />
              <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
                {data.insight}
              </p>
            </div>
          </div>

          {/* Top factors badges */}
          {(data.top_factors ?? []).length > 0 && (
            <div>
              <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-2">
                Your top 2 factors
              </p>
              <div className="flex flex-wrap gap-2">
                {(data.top_factors ?? []).map((f) => {
                  const match = data.factors.find((x) => x.name === f);
                  const color = match ? FACTOR_COLORS[match.label] : "#3B82F6";
                  return (
                    <span
                      key={f}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border"
                      style={{
                        color,
                        backgroundColor: color + "18",
                        borderColor: color + "40",
                      }}
                    >
                      <span
                        className="w-1.5 h-1.5 rounded-full"
                        style={{ backgroundColor: color }}
                      />
                      {f}
                    </span>
                  );
                })}
              </div>
            </div>
          )}

          {/* Concentration summary */}
          <div className="text-xs text-[var(--text-tertiary)]">
            Portfolio concentration score:{" "}
            <span
              className={cn(
                "font-mono font-semibold",
                data.concentration_pct > 60
                  ? "text-[#EF4444]"
                  : data.concentration_pct > 30
                  ? "text-[#F59E0B]"
                  : "text-[#22C55E]"
              )}
            >
              {data.concentration_pct.toFixed(1)}/100
            </span>
            {data.concentration_pct > 50 && (
              <span className="ml-1 text-[#EF4444]">(highly concentrated)</span>
            )}
          </div>
        </div>
      </div>

      {/* Factor breakdown list */}
      <div>
        <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-3">
          Factor breakdown — tap any row for explanation
        </p>
        <div className="space-y-2">
          {(data.factors ?? []).map((f) => (
            <FactorRow
              key={f.name}
              factor={f}
              expanded={expandedFactor === f.name}
              onToggle={() =>
                setExpandedFactor((prev) => (prev === f.name ? null : f.name))
              }
            />
          ))}
        </div>
      </div>
    </div>
  );
}

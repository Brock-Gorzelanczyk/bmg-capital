import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getRiskParity } from "@/api/portfolio";
import type { RiskParityAllocation } from "@/api/portfolio";
import { formatCurrency, cn } from "@/lib/utils";
import { TrendingUp, TrendingDown, Flame, Snowflake, HelpCircle, ArrowRight } from "lucide-react";

// ── Types & Constants ─────────────────────────────────────────────────────────

type Regime = "growth" | "recession" | "inflation-rising" | "inflation-falling";

interface RegimeOption {
  id: Regime;
  label: string;
  description: string;
  icon: React.ReactNode;
  accent: string;
  bg: string;
  border: string;
}

const REGIMES: RegimeOption[] = [
  {
    id: "growth",
    label: "Growth",
    description: "Economy expanding, earnings rising, risk-on sentiment",
    icon: <TrendingUp size={20} />,
    accent: "text-green-400",
    bg: "bg-green-400/5",
    border: "border-green-400/30",
  },
  {
    id: "recession",
    label: "Recession",
    description: "Contraction, falling earnings, defensive positioning",
    icon: <TrendingDown size={20} />,
    accent: "text-red-400",
    bg: "bg-red-400/5",
    border: "border-red-400/30",
  },
  {
    id: "inflation-rising",
    label: "Inflation Rising",
    description: "CPI accelerating, real assets and commodities outperform",
    icon: <Flame size={20} />,
    accent: "text-orange-400",
    bg: "bg-orange-400/5",
    border: "border-orange-400/30",
  },
  {
    id: "inflation-falling",
    label: "Inflation Falling",
    description: "Disinflation/deflation, bonds and equities rally",
    icon: <Snowflake size={20} />,
    accent: "text-blue-400",
    bg: "bg-blue-400/5",
    border: "border-blue-400/30",
  },
];

// ── Donut Chart (pure SVG) ─────────────────────────────────────────────────────

function DonutChart({ allocations }: { allocations: RiskParityAllocation[] }) {
  const size = 200;
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 16;
  const innerR = r * 0.52;

  const total = allocations.reduce((a, s) => a + s.normalized_pct, 0);
  let angle = -Math.PI / 2;

  const paths = allocations.map((s) => {
    const frac = s.normalized_pct / total;
    const sweep = frac * 2 * Math.PI;
    const x1 = cx + r * Math.cos(angle);
    const y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(angle + sweep);
    const y2 = cy + r * Math.sin(angle + sweep);
    const ix1 = cx + innerR * Math.cos(angle);
    const iy1 = cy + innerR * Math.sin(angle);
    const ix2 = cx + innerR * Math.cos(angle + sweep);
    const iy2 = cy + innerR * Math.sin(angle + sweep);
    const large = sweep > Math.PI ? 1 : 0;
    const d = `M${ix1.toFixed(2)},${iy1.toFixed(2)} L${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 ${large},1 ${x2.toFixed(2)},${y2.toFixed(2)} L${ix2.toFixed(2)},${iy2.toFixed(2)} A${innerR},${innerR} 0 ${large},0 ${ix1.toFixed(2)},${iy1.toFixed(2)} Z`;
    angle += sweep;
    return { ...s, d };
  });

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      {paths.map((s) => (
        <path key={s.sleeve} d={s.d} fill={s.color} opacity={0.9} />
      ))}
      <text x={cx} y={cy - 6} textAnchor="middle" fill="var(--text-primary)" fontSize={13} fontWeight="bold" fontFamily="JetBrains Mono, monospace">
        All-Weather
      </text>
      <text x={cx} y={cy + 10} textAnchor="middle" fill="var(--text-tertiary)" fontSize={10} fontFamily="Inter, sans-serif">
        Risk Parity
      </text>
    </svg>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function RiskParityAllocator() {
  const navigate = useNavigate();
  const [regime, setRegime] = useState<Regime>("growth");
  const [capitalInput, setCapitalInput] = useState<string>("10000");

  const capital = parseFloat(capitalInput) || 0;

  const { data, isLoading, error } = useQuery({
    queryKey: ["risk-parity", capital, regime],
    queryFn: () => getRiskParity(capital, regime),
    enabled: capital > 0,
    staleTime: 60_000,
  });

  const allocations = data?.allocations ?? [];

  function handleImplement() {
    // Pre-fill paper trading with the top equity allocation
    const top = allocations.find((a) => a.sleeve === "equities");
    if (top) {
      navigate(`/paper?symbol=${top.ticker}&side=buy`);
    } else {
      navigate("/paper");
    }
  }

  return (
    <div className="px-4 py-5 space-y-6">

      {/* Explainer */}
      <div className="flex items-start gap-3 bg-[#0E7490]/10 border border-[#0E7490]/20 rounded-xl px-4 py-3">
        <HelpCircle size={15} className="text-cyan-400 shrink-0 mt-0.5" />
        <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
          <span className="font-semibold text-cyan-400">Why does regime matter?</span>{" "}
          Bridgewater's All-Weather portfolio rebalances <em>risk</em>—not dollars—based on the
          economic environment. Each sleeve is sized to contribute equal volatility so the
          portfolio performs in all four economic seasons.
        </p>
      </div>

      {/* Capital input */}
      <div>
        <label className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider block mb-2">
          Capital to Allocate
        </label>
        <div className="relative max-w-xs">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]">$</span>
          <input
            type="number"
            min={0}
            value={capitalInput}
            onChange={(e) => setCapitalInput(e.target.value)}
            className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-xl pl-7 pr-4 py-2.5 text-sm font-mono text-[var(--text-primary)] focus:outline-none focus:border-blue-500"
            placeholder="10000"
          />
        </div>
      </div>

      {/* Regime selector */}
      <div>
        <label className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider block mb-3">
          Economic Regime
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {REGIMES.map((r) => (
            <button
              key={r.id}
              onClick={() => setRegime(r.id)}
              className={cn(
                "flex items-start gap-3 p-4 rounded-xl border text-left transition-all cursor-pointer",
                regime === r.id
                  ? `${r.bg} ${r.border} ring-1 ring-inset ${r.border}`
                  : "bg-[var(--bg-elevated-2)] border-[var(--border-subtle)] hover:border-[var(--border-emphasis)]"
              )}
            >
              <span className={cn("shrink-0 mt-0.5", regime === r.id ? r.accent : "text-[var(--text-tertiary)]")}>
                {r.icon}
              </span>
              <div>
                <div className={cn("text-sm font-semibold", regime === r.id ? r.accent : "text-[var(--text-secondary)]")}>
                  {r.label}
                </div>
                <div className="text-xs text-[var(--text-tertiary)] mt-0.5 leading-snug">
                  {r.description}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Results */}
      {capital > 0 && (
        <>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-10 animate-pulse bg-[var(--bg-elevated-2)] rounded-lg" />
              ))}
            </div>
          ) : error ? (
            <div className="text-sm text-[var(--accent-negative)] bg-red-500/5 border border-red-500/20 rounded-xl px-4 py-3">
              Failed to load allocation. Please try again.
            </div>
          ) : allocations.length > 0 ? (
            <>
              {/* Donut + legend */}
              <div>
                <h3 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-4">
                  Allocation Result
                </h3>
                <div className="flex flex-wrap gap-8 items-center">
                  <DonutChart allocations={allocations} />
                  <div className="flex-1 min-w-[200px] space-y-2.5">
                    {allocations.map((a) => (
                      <div key={a.sleeve} className="flex items-center gap-2.5">
                        <span
                          className="w-2.5 h-2.5 rounded-full shrink-0"
                          style={{ backgroundColor: a.color }}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-medium text-[var(--text-primary)]">{a.label}</span>
                            <span className="font-mono text-sm font-semibold text-[var(--text-primary)]">
                              {formatCurrency(a.dollar_amount)}
                            </span>
                          </div>
                          <div className="flex items-center justify-between mt-0.5">
                            <span className="text-[10px] font-mono text-[var(--text-tertiary)]">{a.ticker}</span>
                            <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
                              {a.normalized_pct.toFixed(1)}%
                            </span>
                          </div>
                          <div className="mt-1 h-1 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full"
                              style={{ width: `${a.normalized_pct}%`, backgroundColor: a.color }}
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Regime explanation card */}
              {data?.regime_explanation && (
                <div className="bg-[#0E7490]/8 border border-[#0E7490]/25 rounded-xl px-4 py-4">
                  <div className="text-xs font-semibold text-cyan-400 uppercase tracking-wider mb-2">
                    Why this allocation?
                  </div>
                  <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
                    {data.regime_explanation}
                  </p>
                </div>
              )}

              {/* One-tap implement */}
              <button
                onClick={handleImplement}
                className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm py-3 rounded-xl transition-colors cursor-pointer"
              >
                One-tap Implement in Paper Trading
                <ArrowRight size={15} />
              </button>
            </>
          ) : null}
        </>
      )}
    </div>
  );
}

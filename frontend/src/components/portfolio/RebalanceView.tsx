import { useState, useMemo, useCallback } from "react";
import type { PaperPosition } from "@/api/paper";
import { formatCurrency, cn } from "@/lib/utils";
import { AlertTriangle, CheckCircle2, TrendingUp, TrendingDown } from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface TargetAlloc {
  [symbol: string]: number; // 0-100 pct
}

interface Props {
  positions: PaperPosition[];
  portfolioId?: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function driftColor(drift: number): string {
  if (drift < 5) return "text-[var(--accent-positive)]";
  if (drift < 15) return "text-[#F59E0B]";
  return "text-[var(--accent-negative)]";
}

function driftBg(drift: number): string {
  if (drift < 5) return "bg-green-500/10 border-green-500/20";
  if (drift < 15) return "bg-amber-500/10 border-amber-500/20";
  return "bg-red-500/10 border-red-500/20";
}

function driftLabel(drift: number): string {
  if (drift < 5) return "On track";
  if (drift < 15) return "Moderate drift";
  return "High drift";
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function RebalanceView({ positions, portfolioId }: Props) {
  const storageKey = `bmg_target_alloc_${portfolioId ?? "default"}`;

  // Load saved allocations from localStorage
  const [targets, setTargets] = useState<TargetAlloc>(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) return JSON.parse(saved) as TargetAlloc;
    } catch { /* ignore */ }
    // Default: equal weight
    if (positions.length === 0) return {};
    const equal = Math.floor(100 / positions.length);
    const alloc: TargetAlloc = {};
    positions.forEach((p, i) => {
      alloc[p.symbol] = i === 0 ? 100 - equal * (positions.length - 1) : equal;
    });
    return alloc;
  });

  const [depositAmount, setDepositAmount] = useState<string>("1000");

  const totalValue = useMemo(
    () => positions.reduce((a, p) => a + p.market_value, 0),
    [positions]
  );

  const targetSum = useMemo(
    () => Object.values(targets).reduce((a, v) => a + v, 0),
    [targets]
  );

  const remaining = 100 - targetSum;

  // Per-position data
  const posData = useMemo(() => {
    return positions.map((p) => {
      const actual_pct = totalValue > 0 ? (p.market_value / totalValue) * 100 : 0;
      const target_pct = targets[p.symbol] ?? 0;
      const drift = actual_pct - target_pct;
      return { ...p, actual_pct, target_pct, drift };
    });
  }, [positions, targets, totalValue]);

  // Overall drift score: sum(|actual - target|) / 2
  const driftScore = useMemo(() => {
    if (posData.length === 0) return 0;
    const sum = posData.reduce((a, p) => a + Math.abs(p.drift), 0);
    return sum / 2;
  }, [posData]);

  // Buy recommendations for deposit
  const deposit = parseFloat(depositAmount) || 0;
  const buyRecs = useMemo(() => {
    const newTotal = totalValue + deposit;
    return posData
      .map((p) => {
        const target_value = (p.target_pct / 100) * newTotal;
        const buy = Math.max(0, target_value - p.market_value);
        return { symbol: p.symbol, buy_amount: buy };
      })
      .filter((r) => r.buy_amount > 0.01);
  }, [posData, totalValue, deposit]);

  // Rebalance trade suggestions (buy underweight, sell overweight)
  const rebalanceTrades = useMemo(() => {
    return posData.map((p) => {
      const target_value = (p.target_pct / 100) * totalValue;
      const diff = target_value - p.market_value;
      return { symbol: p.symbol, diff, action: diff > 0 ? "buy" : "sell" as "buy" | "sell" };
    }).filter((t) => Math.abs(t.diff) > 1);
  }, [posData, totalValue]);

  const handleSlider = useCallback((symbol: string, value: number) => {
    setTargets((prev) => {
      const updated = { ...prev, [symbol]: value };
      try { localStorage.setItem(storageKey, JSON.stringify(updated)); } catch { /* ignore */ }
      return updated;
    });
  }, [storageKey]);

  if (positions.length === 0) {
    return (
      <div className="flex items-center justify-center py-16 text-[var(--text-tertiary)] text-sm">
        No positions to rebalance
      </div>
    );
  }

  return (
    <div className="px-4 py-5 space-y-6">

      {/* Drift Score */}
      <div className={cn("flex items-center gap-3 p-4 rounded-xl border", driftBg(driftScore))}>
        <div className={cn("text-2xl font-bold font-mono", driftColor(driftScore))}>
          {driftScore.toFixed(1)}%
        </div>
        <div>
          <div className={cn("text-sm font-semibold", driftColor(driftScore))}>
            Portfolio Drift — {driftLabel(driftScore)}
          </div>
          <div className="text-xs text-[var(--text-tertiary)] mt-0.5">
            {driftScore < 5
              ? "Your portfolio is well-aligned with your targets."
              : driftScore < 15
              ? "Some positions have drifted from target — consider rebalancing."
              : "Significant drift detected. Rebalancing is recommended."}
          </div>
        </div>
      </div>

      {/* Target Allocation Setup */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">
            Target Allocation
          </h3>
          <span className={cn(
            "text-xs font-mono px-2 py-0.5 rounded-full border",
            Math.abs(remaining) < 0.5
              ? "text-green-400 bg-green-400/10 border-green-400/20"
              : "text-amber-400 bg-amber-400/10 border-amber-400/20"
          )}>
            {remaining >= 0 ? `${remaining.toFixed(0)}% remaining` : `${Math.abs(remaining).toFixed(0)}% over`}
          </span>
        </div>

        <div className="space-y-4">
          {posData.map((p) => (
            <div key={p.symbol}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-mono font-bold text-sm text-[var(--text-primary)]">{p.symbol}</span>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[var(--text-tertiary)]">
                    Actual: {p.actual_pct.toFixed(1)}%
                  </span>
                  <span className="text-xs font-mono text-[var(--text-primary)]">
                    Target: {p.target_pct.toFixed(0)}%
                  </span>
                </div>
              </div>

              {/* Stacked bar: actual (blue) vs target outline */}
              <div className="relative h-3 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden mb-1.5">
                {/* Target bar (outlined) */}
                <div
                  className="absolute inset-y-0 left-0 border-r-2 border-[#64748B] bg-[#64748B]/10"
                  style={{ width: `${Math.min(p.target_pct, 100)}%` }}
                />
                {/* Actual bar */}
                <div
                  className={cn(
                    "absolute inset-y-0 left-0 rounded-full",
                    p.drift > 2 ? "bg-amber-500" : p.drift < -2 ? "bg-blue-500" : "bg-[var(--accent-positive)]"
                  )}
                  style={{ width: `${Math.min(p.actual_pct, 100)}%` }}
                />
              </div>

              {/* Drift indicator */}
              {Math.abs(p.drift) > 1 && (
                <div className={cn(
                  "text-[10px] flex items-center gap-1",
                  p.drift > 0 ? "text-amber-400" : "text-blue-400"
                )}>
                  {p.drift > 0
                    ? <><TrendingUp size={10} /> {p.drift.toFixed(1)}% overweight</>
                    : <><TrendingDown size={10} /> {Math.abs(p.drift).toFixed(1)}% underweight</>
                  }
                </div>
              )}

              {/* Slider */}
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                value={p.target_pct}
                onChange={(e) => handleSlider(p.symbol, parseInt(e.target.value, 10))}
                className="w-full mt-1 h-1 accent-blue-500 cursor-pointer"
              />
            </div>
          ))}
        </div>
      </div>

      {/* Where should new cash go? */}
      <div>
        <h3 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-3">
          Where Should New Cash Go?
        </h3>
        <div className="flex items-center gap-3 mb-4">
          <label className="text-xs text-[var(--text-tertiary)]">Deposit amount:</label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-sm">$</span>
            <input
              type="number"
              min={0}
              value={depositAmount}
              onChange={(e) => setDepositAmount(e.target.value)}
              className="bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg pl-7 pr-3 py-1.5 text-sm font-mono text-[var(--text-primary)] w-32 focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>

        {deposit > 0 && buyRecs.length > 0 ? (
          <div className="space-y-2">
            {buyRecs.map((rec) => (
              <div key={rec.symbol} className="flex items-center justify-between bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2.5">
                <span className="font-mono font-bold text-sm text-[var(--text-primary)]">{rec.symbol}</span>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[var(--text-tertiary)]">Buy</span>
                  <span className="font-mono text-sm font-semibold text-[var(--accent-positive)]">
                    {formatCurrency(rec.buy_amount)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-[var(--text-tertiary)] text-center py-4">
            {deposit <= 0 ? "Enter a deposit amount above" : "Portfolio is already balanced — no buys needed"}
          </div>
        )}
      </div>

      {/* Rebalance Recommendations */}
      <div>
        <h3 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-3">
          Rebalance Recommendations
        </h3>

        {rebalanceTrades.length === 0 ? (
          <div className="flex items-center gap-2 text-green-400 text-sm bg-green-400/5 border border-green-400/20 rounded-lg px-4 py-3">
            <CheckCircle2 size={14} />
            Portfolio is balanced — no trades needed
          </div>
        ) : (
          <div className="space-y-2">
            {rebalanceTrades.map((t) => (
              <div
                key={t.symbol}
                className={cn(
                  "flex items-center justify-between rounded-lg px-3 py-2.5 border",
                  t.action === "buy"
                    ? "bg-green-500/5 border-green-500/20"
                    : "bg-red-500/5 border-red-500/20"
                )}
              >
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "text-[10px] font-bold uppercase px-1.5 py-0.5 rounded",
                    t.action === "buy"
                      ? "bg-green-500/20 text-green-400"
                      : "bg-red-500/20 text-red-400"
                  )}>
                    {t.action}
                  </span>
                  <span className="font-mono font-bold text-sm text-[var(--text-primary)]">{t.symbol}</span>
                </div>
                <span className={cn(
                  "font-mono text-sm font-semibold",
                  t.action === "buy" ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"
                )}>
                  {t.action === "buy" ? "+" : "-"}{formatCurrency(Math.abs(t.diff))}
                </span>
              </div>
            ))}
            <p className="text-[10px] text-[var(--text-tertiary)] mt-2 flex items-center gap-1">
              <AlertTriangle size={10} />
              These are recommendations only — no trades will be executed automatically.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

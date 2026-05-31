import { useState, useEffect } from "react";
import { ShieldAlert, AlertTriangle, Info } from "lucide-react";
import { formatCurrency, cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DrawdownBudgetProps {
  /** Current portfolio value */
  portfolioValue: number;
  /** Peak portfolio value (for equity-curve drawdown). Falls back to gain_pct approach if not provided. */
  peakValue?: number;
  /** Overall gain/loss amount (used when peak is unavailable) */
  totalPnl?: number;
  /** Starting balance (used to infer peak when no equity curve) */
  startingBalance?: number;
}

// ── Local storage key ─────────────────────────────────────────────────────────

const LS_KEY = "bmg_drawdown_budget";

function loadBudget(): number {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) {
      const v = parseFloat(raw);
      if (!isNaN(v) && v >= 5 && v <= 40) return v;
    }
  } catch {
    // ignore
  }
  return 15; // default 15%
}

function saveBudget(value: number) {
  try {
    localStorage.setItem(LS_KEY, String(value));
  } catch {
    // ignore
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function DrawdownBudget({
  portfolioValue,
  peakValue,
  totalPnl,
  startingBalance,
}: DrawdownBudgetProps) {
  const [maxDrawdown, setMaxDrawdown] = useState<number>(loadBudget);
  const [showInfo, setShowInfo] = useState(false);

  // Persist slider value
  useEffect(() => {
    saveBudget(maxDrawdown);
  }, [maxDrawdown]);

  // ── Compute current drawdown from peak ────────────────────────────────────

  let currentDrawdownPct = 0;

  if (peakValue && peakValue > 0 && portfolioValue > 0) {
    // Equity-curve approach: true peak-to-trough drawdown
    currentDrawdownPct = Math.max(0, ((peakValue - portfolioValue) / peakValue) * 100);
  } else if (startingBalance && startingBalance > 0 && portfolioValue > 0) {
    // Fallback: drawdown from starting balance (if down from start)
    const loss = startingBalance - portfolioValue;
    if (loss > 0) {
      currentDrawdownPct = (loss / startingBalance) * 100;
    }
  } else if (totalPnl !== undefined && portfolioValue > 0) {
    // Fallback: use total P&L to infer drawdown
    if (totalPnl < 0) {
      const impliedPeak = portfolioValue - totalPnl;
      currentDrawdownPct = Math.max(0, ((-totalPnl) / impliedPeak) * 100);
    }
  }

  // ── Budget utilization ────────────────────────────────────────────────────

  const budgetUsedPct = maxDrawdown > 0 ? (currentDrawdownPct / maxDrawdown) * 100 : 0;
  const capped = Math.min(budgetUsedPct, 100);

  // ── Color thresholds ──────────────────────────────────────────────────────

  const barColor =
    capped < 50 ? "#22C55E" :
    capped < 75 ? "#F59E0B" :
    "#EF4444";

  const statusLabel =
    capped < 50 ? "On track" :
    capped < 75 ? "Caution" :
    "De-risk zone";

  // ── 1-day VaR (simplified: 2% daily vol assumption at 95th percentile) ───
  // VaR ≈ portfolio_value × 0.02 × 1.645 (95th percentile z-score, simplified to 2% × ~1 for readability)
  const dailyVaR = portfolioValue * 0.02;

  const isDeRiskZone = capped >= 75;

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
            style={{ backgroundColor: `${barColor}20`, border: `1px solid ${barColor}40` }}
          >
            <ShieldAlert size={14} style={{ color: barColor }} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Drawdown Risk Budget</h3>
            <p className="text-[11px] text-[var(--text-tertiary)]">Annual drawdown allowance</p>
          </div>
        </div>

        {/* Info tooltip */}
        <div className="relative">
          <button
            onMouseEnter={() => setShowInfo(true)}
            onMouseLeave={() => setShowInfo(false)}
            onFocus={() => setShowInfo(true)}
            onBlur={() => setShowInfo(false)}
            className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
          >
            <Info size={13} />
          </button>
          {showInfo && (
            <div className="absolute right-0 bottom-full mb-2 w-56 bg-[#1E293B] border border-[var(--border-emphasis)] rounded-xl p-3 text-xs text-[var(--text-secondary)] shadow-xl z-20 leading-relaxed">
              Tracks how much of your self-imposed annual drawdown limit has been consumed. Set your tolerance with the slider below.
            </div>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <div>
        <div className="flex items-center justify-between mb-1.5 text-xs">
          <span className="text-[var(--text-tertiary)]">
            Used{" "}
            <span className="font-mono font-semibold" style={{ color: barColor }}>
              {currentDrawdownPct.toFixed(1)}%
            </span>
            {" "}of{" "}
            <span className="font-mono font-semibold text-[var(--text-secondary)]">
              {maxDrawdown}%
            </span>{" "}
            budget
          </span>
          <span
            className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
            style={{
              backgroundColor: `${barColor}20`,
              color: barColor,
              border: `1px solid ${barColor}30`,
            }}
          >
            {statusLabel}
          </span>
        </div>

        <div className="h-3 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${capped}%`, backgroundColor: barColor }}
          />
        </div>

        <div className="flex justify-between text-[10px] text-[var(--text-tertiary)] mt-1">
          <span>0%</span>
          <span className="text-amber-500/70">50%</span>
          <span className="text-red-500/70">75%</span>
          <span>{maxDrawdown}%</span>
        </div>
      </div>

      {/* Max drawdown slider */}
      <div>
        <label className="flex items-center justify-between text-xs text-[var(--text-tertiary)] mb-2">
          <span>Max acceptable annual drawdown</span>
          <span className="font-mono font-bold text-[var(--text-primary)]">{maxDrawdown}%</span>
        </label>
        <input
          type="range"
          min={5}
          max={40}
          step={1}
          value={maxDrawdown}
          onChange={(e) => setMaxDrawdown(parseInt(e.target.value))}
          className="w-full h-1.5 rounded-full appearance-none cursor-pointer accent-[#3B82F6] bg-[var(--bg-elevated-2)]"
        />
        <div className="flex justify-between text-[10px] text-[var(--text-tertiary)] mt-0.5">
          <span>5% (conservative)</span>
          <span>40% (aggressive)</span>
        </div>
      </div>

      {/* VaR estimate */}
      <div className="bg-[var(--bg-elevated-2)] rounded-xl px-3 py-2.5">
        <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">
          Estimated 1-day VaR (95%)
        </div>
        <div className="font-mono font-semibold text-[var(--text-primary)] text-sm">
          {formatCurrency(dailyVaR)}
        </div>
        <p className="text-[10px] text-[var(--text-tertiary)] mt-0.5 leading-relaxed">
          On a bad day, you could lose up to this amount.{" "}
          <span className="text-[#475569]">(Simplified 2% daily vol estimate — rough approximation only)</span>
        </p>
      </div>

      {/* De-risk recommendation */}
      {isDeRiskZone && (
        <div className="flex items-start gap-2.5 bg-red-500/10 border border-red-500/20 rounded-xl px-3 py-3">
          <AlertTriangle size={14} className="text-red-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-semibold text-red-300 mb-0.5">De-risk Recommendation</p>
            <p className="text-[11px] text-red-400/80 leading-relaxed">
              Your portfolio has used{" "}
              <span className="font-bold">{capped.toFixed(0)}%</span> of your annual risk budget.
              Consider reducing exposure or hedging open positions to protect remaining capital.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

import { useState, useEffect } from "react";
import { ShieldAlert, AlertTriangle, Info } from "lucide-react";
import { formatCurrency } from "@/lib/utils";

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

  // budgetUsedPct: 0–100+ where 100 = budget fully consumed
  const budgetUsedPct = maxDrawdown > 0 ? (currentDrawdownPct / maxDrawdown) * 100 : 0;
  const exceeded = budgetUsedPct > 100;
  // Bar fill capped at 100% of the budget range
  const barFill = Math.min(budgetUsedPct, 100);

  // ── Color thresholds (based on % of budget used) ─────────────────────────

  const barColor =
    exceeded       ? "#EF4444" :
    budgetUsedPct >= 80 ? "#EF4444" :
    budgetUsedPct >= 50 ? "#F59E0B" :
    "#22C55E";

  // ── Badge ─────────────────────────────────────────────────────────────────

  const badgeLabel =
    exceeded            ? "EXCEEDED" :
    budgetUsedPct >= 80 ? "Near limit" :
    budgetUsedPct >= 50 ? "Approaching" :
    "On track";

  // ── 1-day VaR (simplified: 2% daily vol assumption at 95th percentile) ───
  // VaR ≈ portfolio_value × 0.02 × 1.645 (95th percentile z-score, simplified to 2% × ~1 for readability)
  const dailyVaR = portfolioValue * 0.02;

  // ── Banner visibility ─────────────────────────────────────────────────────
  // Hide when <50% used; show at 50%+
  const showBanner = budgetUsedPct >= 50;

  const bannerTitle =
    exceeded            ? "Budget Exceeded" :
    budgetUsedPct >= 80 ? "Near Limit" :
    "Approaching Limit";

  // Tick positions: 25%, 50%, 75%, 100% of budget
  const tick25  = (maxDrawdown * 0.25).toFixed(1);
  const tick50  = (maxDrawdown * 0.50).toFixed(1);
  const tick75  = (maxDrawdown * 0.75).toFixed(1);
  const tick100 = maxDrawdown.toFixed(1);

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
        {/* Primary label — single source of truth for the drawdown figure */}
        <div className="flex items-center justify-between mb-1.5 text-xs">
          <span className="text-[var(--text-tertiary)]">
            {exceeded ? (
              <>
                <span className="font-mono font-semibold text-red-400">
                  Drawdown EXCEEDED —{" "}
                  <span style={{ color: barColor }}>{currentDrawdownPct.toFixed(1)}%</span>
                </span>
                {" "}
                <span className="text-[var(--text-tertiary)]">vs</span>
                {" "}
                <span className="font-mono font-semibold text-[var(--text-secondary)]">
                  {maxDrawdown}% budget
                </span>
              </>
            ) : (
              <>
                {"Drawdown "}
                <span className="font-mono font-semibold" style={{ color: barColor }}>
                  {currentDrawdownPct.toFixed(1)}%
                </span>
                {" / "}
                <span className="font-mono font-semibold text-[var(--text-secondary)]">
                  {maxDrawdown}% budget
                </span>
              </>
            )}
          </span>
          <span
            className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
            style={{
              backgroundColor: `${barColor}20`,
              color: barColor,
              border: `1px solid ${barColor}30`,
            }}
          >
            {badgeLabel}
          </span>
        </div>

        {/* Bar + optional overflow indicator */}
        <div className="flex items-center gap-1">
          <div className="flex-1 h-3 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{ width: `${barFill}%`, backgroundColor: barColor }}
            />
          </div>
          {exceeded && (
            <div
              className="h-3 w-3 rounded-sm shrink-0 animate-pulse"
              style={{ backgroundColor: "#EF4444" }}
              title={`${currentDrawdownPct.toFixed(1)}% drawdown exceeds ${maxDrawdown}% budget`}
            />
          )}
        </div>

        {/* Tick marks at 25 / 50 / 75 / 100% of budget */}
        <div className="flex justify-between text-[10px] text-[var(--text-tertiary)] mt-1">
          <span>0%</span>
          <span className="text-[var(--text-tertiary)]/70">{tick25}%</span>
          <span className="text-amber-500/70">{tick50}%</span>
          <span className="text-red-500/70">{tick75}%</span>
          <span className="text-right">{tick100}%</span>
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

      {/* Banner — shown only at 50%+ utilization, single message, no duplicate % */}
      {showBanner && (
        <div
          className="flex items-start gap-2.5 rounded-xl px-3 py-3"
          style={{
            backgroundColor: `${barColor}10`,
            border: `1px solid ${barColor}30`,
          }}
        >
          <AlertTriangle size={14} style={{ color: barColor }} className="shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-semibold mb-0.5" style={{ color: barColor }}>
              {bannerTitle}
            </p>
            <p className="text-[11px] leading-relaxed" style={{ color: `${barColor}CC` }}>
              {exceeded
                ? `Your drawdown of ${currentDrawdownPct.toFixed(1)}% has exceeded the ${maxDrawdown}% budget. Consider reducing exposure or hedging to protect remaining capital.`
                : budgetUsedPct >= 80
                ? `You are near your ${maxDrawdown}% annual drawdown limit. Consider reducing exposure or hedging open positions.`
                : `You have used over half of your ${maxDrawdown}% annual drawdown allowance. Monitor positions closely.`}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

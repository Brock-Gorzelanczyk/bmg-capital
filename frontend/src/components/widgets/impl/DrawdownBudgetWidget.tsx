import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert, AlertTriangle, Info } from "lucide-react";
import { getAccount } from "@/api/paper";
import { formatCurrency, cn } from "@/lib/utils";

const LS_KEY = "bmg_drawdown_budget";

function loadBudget(): number {
  try {
    const v = parseFloat(localStorage.getItem(LS_KEY) ?? "");
    if (!isNaN(v) && v >= 5 && v <= 40) return v;
  } catch {}
  return 15;
}

export default function DrawdownBudgetWidget() {
  const { data: account, isLoading } = useQuery({
    queryKey: ["paper-account"],
    queryFn: getAccount,
    staleTime: 30_000,
    retry: false,
  });

  const [maxDrawdown, setMaxDrawdown] = useState<number>(loadBudget);
  const [showInfo, setShowInfo] = useState(false);

  useEffect(() => {
    try { localStorage.setItem(LS_KEY, String(maxDrawdown)); } catch {}
  }, [maxDrawdown]);

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-10 bg-[var(--bg-elevated-2)] animate-pulse rounded-lg" />
        ))}
      </div>
    );
  }

  const portfolioValue = account?.equity ?? 0;
  const totalPnl = account?.total_pnl;
  const startingBalance = account?.starting_balance;

  let currentDrawdownPct = 0;
  if (startingBalance && startingBalance > 0 && portfolioValue > 0) {
    const loss = startingBalance - portfolioValue;
    if (loss > 0) currentDrawdownPct = (loss / startingBalance) * 100;
  } else if (totalPnl !== undefined && portfolioValue > 0 && totalPnl < 0) {
    const impliedPeak = portfolioValue - totalPnl;
    currentDrawdownPct = Math.max(0, (-totalPnl / impliedPeak) * 100);
  }

  const budgetUsedPct = maxDrawdown > 0 ? (currentDrawdownPct / maxDrawdown) * 100 : 0;
  const capped = Math.min(budgetUsedPct, 100);

  const barColor = capped < 50 ? "#22C55E" : capped < 75 ? "#F59E0B" : "#EF4444";
  const statusLabel = capped < 50 ? "On track" : capped < 75 ? "Caution" : "De-risk zone";
  const dailyVaR = portfolioValue * 0.02;
  const isDeRiskZone = capped >= 75;

  return (
    <div className="h-full overflow-auto space-y-4">
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
            <p className="text-xs font-semibold text-[var(--text-primary)]">Annual drawdown allowance</p>
            <p className="text-[10px] text-[var(--text-tertiary)]">Paper portfolio risk budget</p>
          </div>
        </div>
        <div className="relative">
          <button
            onMouseEnter={() => setShowInfo(true)}
            onMouseLeave={() => setShowInfo(false)}
            className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
          >
            <Info size={13} />
          </button>
          {showInfo && (
            <div className="absolute right-0 bottom-full mb-2 w-52 bg-[#1E293B] border border-[var(--border-emphasis)] rounded-xl p-3 text-xs text-[var(--text-secondary)] shadow-xl z-20 leading-relaxed">
              Tracks how much of your self-imposed annual drawdown limit has been consumed. Set your tolerance with the slider.
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
            </span>
          </span>
          <span
            className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
            style={{ backgroundColor: `${barColor}20`, color: barColor, border: `1px solid ${barColor}30` }}
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

      {/* Slider */}
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

      {/* VaR */}
      <div className="bg-[var(--bg-elevated-2)] rounded-xl px-3 py-2.5">
        <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">
          Estimated 1-day VaR (95%)
        </div>
        <div className="font-mono font-semibold text-[var(--text-primary)] text-sm">
          {formatCurrency(dailyVaR)}
        </div>
        <p className="text-[10px] text-[var(--text-tertiary)] mt-0.5 leading-relaxed">
          On a bad day you could lose up to this amount.{" "}
          <span className="text-[#475569]">(2% daily vol estimate)</span>
        </p>
      </div>

      {/* De-risk alert */}
      {isDeRiskZone && (
        <div className="flex items-start gap-2.5 bg-red-500/10 border border-red-500/20 rounded-xl px-3 py-3">
          <AlertTriangle size={14} className="text-red-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-semibold text-red-300 mb-0.5">De-risk Recommendation</p>
            <p className="text-[11px] text-red-400/80 leading-relaxed">
              You've used <span className="font-bold">{capped.toFixed(0)}%</span> of your annual risk budget. Consider reducing exposure.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

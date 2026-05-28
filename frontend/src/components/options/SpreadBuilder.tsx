import { Trash2, ArrowUp, ArrowDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { identifyStrategy } from "@/types/options";
import type { OptionsLeg } from "@/types/options";

interface Props {
  legs: OptionsLeg[];
  onRemoveLeg: (idx: number) => void;
  onToggleSide: (idx: number) => void;
  onSetQty: (idx: number, qty: number) => void;
}

function fmt(n: number) {
  return n.toFixed(2);
}

export default function SpreadBuilder({ legs, onRemoveLeg, onToggleSide, onSetQty }: Props) {
  const strategy = identifyStrategy(legs);

  // Net premium (positive = credit, negative = debit)
  const netPremium = legs.reduce((sum, leg) => {
    const mid = (leg.contract.bid + leg.contract.ask) / 2;
    return sum + (leg.side === "sell" ? mid : -mid) * leg.qty * 100;
  }, 0);

  // Max gain/loss helpers (simple approximation for common spreads)
  let maxGain: number | null = null;
  let maxLoss: number | null = null;

  const callLegs = legs.filter((l) => l.contract.optionType === "call");
  const putLegs = legs.filter((l) => l.contract.optionType === "put");
  const buyLegs = legs.filter((l) => l.side === "buy");
  const sellLegs = legs.filter((l) => l.side === "sell");

  if (legs.length === 1) {
    const { side, contract, qty } = legs[0];
    const mid = (contract.bid + contract.ask) / 2;
    if (side === "buy") {
      maxLoss = mid * qty * 100;
      maxGain = null; // unlimited for long call/put
    } else {
      maxGain = mid * qty * 100;
      maxLoss = null; // unlimited for short call; defined for short put
    }
  } else if (legs.length === 2 && callLegs.length === 2 && buyLegs.length === 1 && sellLegs.length === 1) {
    // Vertical spread
    const buy = buyLegs[0];
    const sell = sellLegs[0];
    const strikeWidth = Math.abs(buy.contract.strike - sell.contract.strike);
    const credit = (sell.contract.bid + sell.contract.ask) / 2 - (buy.contract.bid + buy.contract.ask) / 2;
    if (credit > 0) {
      maxGain = credit * 100;
      maxLoss = (strikeWidth - credit) * 100;
    } else {
      maxGain = (strikeWidth + credit) * 100;
      maxLoss = -credit * 100;
    }
  } else if (legs.length === 2 && putLegs.length === 2 && buyLegs.length === 1 && sellLegs.length === 1) {
    const buy = buyLegs[0];
    const sell = sellLegs[0];
    const strikeWidth = Math.abs(buy.contract.strike - sell.contract.strike);
    const credit = (sell.contract.bid + sell.contract.ask) / 2 - (buy.contract.bid + buy.contract.ask) / 2;
    if (credit > 0) {
      maxGain = credit * 100;
      maxLoss = (strikeWidth - credit) * 100;
    } else {
      maxGain = (strikeWidth + credit) * 100;
      maxLoss = -credit * 100;
    }
  }

  return (
    <div className="space-y-3">
      {/* Strategy label */}
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Spread Builder</span>
        {strategy !== "—" && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-[#334155] text-[var(--text-secondary)] font-medium">
            {strategy}
          </span>
        )}
      </div>

      {/* Legs */}
      {legs.length === 0 ? (
        <p className="text-[var(--text-tertiary)] text-xs text-center py-4">
          Click B/S in the chain to add legs
        </p>
      ) : (
        <div className="space-y-1.5">
          {legs.map((leg, idx) => {
            const { contract, side, qty } = leg;
            const mid = (contract.bid + contract.ask) / 2;
            return (
              <div
                key={`${contract.symbol}-${side}-${idx}`}
                className="flex items-center gap-2 bg-[var(--bg-elevated-2)] rounded-lg px-3 py-2"
              >
                {/* Side toggle */}
                <button
                  onClick={() => onToggleSide(idx)}
                  className={cn(
                    "text-[10px] font-bold px-1.5 py-0.5 rounded w-8 text-center transition-colors",
                    side === "buy"
                      ? "bg-emerald-900 text-[var(--accent-positive)] hover:bg-emerald-800"
                      : "bg-rose-900 text-[var(--accent-negative)] hover:bg-rose-800"
                  )}
                >
                  {side === "buy" ? "BUY" : "SELL"}
                </button>

                {/* Contract info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className={cn(
                      "text-[10px] font-semibold uppercase",
                      contract.optionType === "call" ? "text-sky-400" : "text-orange-400"
                    )}>
                      {contract.optionType}
                    </span>
                    <span className="text-[var(--text-secondary)] text-xs font-mono">${contract.strike}</span>
                    <span className="text-[var(--text-tertiary)] text-[10px]">{contract.expiration}</span>
                  </div>
                  <div className="text-[var(--text-tertiary)] text-[10px]">
                    ${fmt(contract.bid)} / ${fmt(contract.ask)} · mid ${fmt(mid)}
                  </div>
                </div>

                {/* Qty */}
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => onSetQty(idx, Math.max(1, qty - 1))}
                    className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] w-5 h-5 flex items-center justify-center"
                  >
                    <ArrowDown size={11} />
                  </button>
                  <span className="text-[var(--text-secondary)] text-xs w-4 text-center">{qty}</span>
                  <button
                    onClick={() => onSetQty(idx, qty + 1)}
                    className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] w-5 h-5 flex items-center justify-center"
                  >
                    <ArrowUp size={11} />
                  </button>
                </div>

                {/* Remove */}
                <button
                  onClick={() => onRemoveLeg(idx)}
                  className="text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] transition-colors"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* Summary */}
      {legs.length > 0 && (
        <div className="grid grid-cols-3 gap-2 pt-2 border-t border-[var(--border-emphasis)]">
          <div className="text-center">
            <div className="text-[10px] text-[var(--text-tertiary)] mb-0.5">Net Premium</div>
            <div className={cn(
              "text-sm font-bold font-mono",
              netPremium > 0 ? "text-[var(--accent-positive)]" : netPremium < 0 ? "text-[var(--accent-negative)]" : "text-[var(--text-secondary)]"
            )}>
              {netPremium > 0 ? "+" : ""}{netPremium < 0 ? "-" : ""}${Math.abs(netPremium).toFixed(2)}
            </div>
            <div className="text-[9px] text-[var(--text-tertiary)]">{netPremium > 0 ? "credit" : "debit"}</div>
          </div>
          <div className="text-center">
            <div className="text-[10px] text-[var(--text-tertiary)] mb-0.5">Max Gain</div>
            <div className="text-sm font-bold font-mono text-[var(--accent-positive)]">
              {maxGain === null ? "∞" : `$${maxGain.toFixed(0)}`}
            </div>
          </div>
          <div className="text-center">
            <div className="text-[10px] text-[var(--text-tertiary)] mb-0.5">Max Loss</div>
            <div className="text-sm font-bold font-mono text-[var(--accent-negative)]">
              {maxLoss === null ? "∞" : `$${maxLoss.toFixed(0)}`}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

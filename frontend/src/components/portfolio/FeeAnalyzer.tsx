import { useMemo } from "react";
import { AlertTriangle, TrendingDown, ArrowRight, CheckCircle } from "lucide-react";
import { formatCurrency, cn } from "@/lib/utils";
import type { PaperPosition } from "@/api/paper";

// ---------------------------------------------------------------------------
// Expense ratio lookup for common ETFs
// ---------------------------------------------------------------------------

interface EtfInfo {
  er: number;       // expense ratio as decimal (e.g. 0.0945 = 0.0945%)
  name: string;
  lowFeeAlt: string;
  altEr: number;
}

const ETF_EXPENSE_RATIOS: Record<string, EtfInfo> = {
  SPY:  { er: 0.0945, name: "SPDR S&P 500",    lowFeeAlt: "VOO",  altEr: 0.03  },
  QQQ:  { er: 0.20,   name: "Invesco QQQ",      lowFeeAlt: "QQQM", altEr: 0.15  },
  IWM:  { er: 0.19,   name: "iShares R2000",    lowFeeAlt: "SCHA", altEr: 0.04  },
  GLD:  { er: 0.40,   name: "SPDR Gold",        lowFeeAlt: "IAU",  altEr: 0.25  },
  TLT:  { er: 0.15,   name: "iShares 20Y Tsy",  lowFeeAlt: "VGLT", altEr: 0.04  },
  XLK:  { er: 0.10,   name: "Tech SPDR",        lowFeeAlt: "VGT",  altEr: 0.10  },
  VTI:  { er: 0.03,   name: "Vanguard Total",   lowFeeAlt: "VTI",  altEr: 0.03  },
  VOO:  { er: 0.03,   name: "Vanguard S&P 500", lowFeeAlt: "VOO",  altEr: 0.03  },
  ARKK: { er: 0.75,   name: "ARK Innovation",   lowFeeAlt: "QQQM", altEr: 0.15  },
  SCHD: { er: 0.06,   name: "Schwab Dividend",  lowFeeAlt: "SCHD", altEr: 0.06  },
};

// ---------------------------------------------------------------------------
// FV-based 30-year projected fee drag
// Assumes 7% annual growth; compares FV with current ER vs FV with 0% ER.
// ---------------------------------------------------------------------------
const GROWTH_RATE = 0.07;
const YEARS = 30;

function fv30(presentValue: number): number {
  return presentValue * Math.pow(1 + GROWTH_RATE, YEARS);
}

function feeDragFv(presentValue: number, erPct: number): number {
  // FV without fees minus FV with annual fee drag
  const erDecimal = erPct / 100;
  const fvWithFees = presentValue * Math.pow(1 + GROWTH_RATE - erDecimal, YEARS);
  const fvNoFees = fv30(presentValue);
  return fvNoFees - fvWithFees;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AnalyzedPosition {
  symbol: string;
  market_value: number;
  er: number;
  name: string;
  annualFee: number;
  feeDrag30yr: number;
  isHighFee: boolean;
  hasCheaperAlt: boolean;
  altSymbol: string;
  altEr: number;
  altAnnualFee: number;
  altFeeDrag30yr: number;
  annualSavings: number;
  savings30yr: number;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface FeeAnalyzerProps {
  positions: PaperPosition[];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function FeeAnalyzer({ positions }: FeeAnalyzerProps) {
  const analyzed = useMemo<AnalyzedPosition[]>(() => {
    return positions
      .filter((p) => ETF_EXPENSE_RATIOS[p.symbol])
      .map((p) => {
        const info = ETF_EXPENSE_RATIOS[p.symbol]!;
        const mv = p.market_value;
        const annualFee = mv * (info.er / 100);
        const feeDrag = feeDragFv(mv, info.er);
        const altAnnualFee = mv * (info.altEr / 100);
        const altFeeDrag = feeDragFv(mv, info.altEr);
        return {
          symbol: p.symbol,
          market_value: mv,
          er: info.er,
          name: info.name,
          annualFee,
          feeDrag30yr: feeDrag,
          isHighFee: info.er > 0.5,
          hasCheaperAlt: info.altEr < info.er,
          altSymbol: info.lowFeeAlt,
          altEr: info.altEr,
          altAnnualFee,
          altFeeDrag30yr: altFeeDrag,
          annualSavings: annualFee - altAnnualFee,
          savings30yr: feeDrag - altFeeDrag,
        };
      });
  }, [positions]);

  const totalAnnualFees = analyzed.reduce((a, r) => a + r.annualFee, 0);
  const totalFeeDrag30yr = analyzed.reduce((a, r) => a + r.feeDrag30yr, 0);
  const totalAnnualSavings = analyzed.reduce((a, r) => a + r.annualSavings, 0);
  const totalSavings30yr = analyzed.reduce((a, r) => a + r.savings30yr, 0);
  const etfCount = analyzed.length;

  if (etfCount === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-3 text-center px-4">
        <CheckCircle size={32} className="text-[var(--text-tertiary)]" />
        <p className="text-[var(--text-secondary)] font-medium">No ETFs with known expense ratios in this portfolio</p>
        <p className="text-xs text-[var(--text-tertiary)]">
          Fee analysis covers: {Object.keys(ETF_EXPENSE_RATIOS).join(", ")}
        </p>
      </div>
    );
  }

  return (
    <div className="px-4 py-5 space-y-5">
      {/* ── Summary Card ───────────────────────────────────────────────── */}
      <div className="bg-[var(--bg-elevated-2)] rounded-xl p-4 space-y-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-[var(--text-secondary)]">
          <TrendingDown size={14} className="text-red-400" />
          Fee Impact Summary
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-0.5">
              Annual fees ({etfCount} fund{etfCount !== 1 ? "s" : ""})
            </div>
            <div className="text-2xl font-mono font-bold text-[var(--text-primary)]">
              {formatCurrency(totalAnnualFees)}
            </div>
            <div className="text-xs text-[var(--text-tertiary)]">per year in expense ratios</div>
          </div>

          <div>
            <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-0.5">
              30-year fee drag
            </div>
            <div className="text-2xl font-mono font-bold text-red-400">
              {formatCurrency(totalFeeDrag30yr)}
            </div>
            <div className="text-xs text-[var(--text-tertiary)]">compounded at 7% growth</div>
          </div>

          {totalAnnualSavings > 0 && (
            <div>
              <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-0.5">
                Switching saves you
              </div>
              <div className="text-2xl font-mono font-bold text-[var(--accent-positive)]">
                {formatCurrency(totalAnnualSavings)}/yr
              </div>
              <div className="text-xs text-[var(--text-tertiary)]">
                {formatCurrency(totalSavings30yr)} over 30 years
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Per-ETF rows ────────────────────────────────────────────────── */}
      <div className="space-y-3">
        {analyzed.map((row) => (
          <div
            key={row.symbol}
            className={cn(
              "rounded-xl border p-4",
              row.isHighFee
                ? "border-red-500/30 bg-red-500/5"
                : "border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]"
            )}
          >
            <div className="flex items-start justify-between gap-3 flex-wrap">
              {/* Left: symbol + name */}
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono font-bold text-[var(--text-primary)]">{row.symbol}</span>
                  {row.isHighFee && (
                    <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded-full bg-red-500/15 text-red-400 border border-red-500/25">
                      <AlertTriangle size={9} /> High Fee
                    </span>
                  )}
                </div>
                <div className="text-xs text-[var(--text-tertiary)] mt-0.5">{row.name}</div>
              </div>

              {/* Right: stats */}
              <div className="flex items-center gap-6 flex-wrap text-right">
                <div>
                  <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">Expense ratio</div>
                  <div className="font-mono text-sm font-semibold text-[var(--text-primary)]">{row.er.toFixed(2)}%</div>
                </div>
                <div>
                  <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">Annual fee</div>
                  <div className="font-mono text-sm text-red-400 font-medium">{formatCurrency(row.annualFee)}</div>
                </div>
                <div>
                  <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">30-yr drag</div>
                  <div className="font-mono text-sm text-red-400 font-medium">{formatCurrency(row.feeDrag30yr)}</div>
                </div>
              </div>
            </div>

            {/* Lower-fee alternative */}
            {row.hasCheaperAlt && (
              <div className="mt-3 pt-3 border-t border-[var(--border-subtle)]/60">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[11px] text-[var(--text-tertiary)]">Lower-fee alternative:</span>
                  <div className="flex items-center gap-2 text-xs">
                    <span className="font-mono font-bold text-[var(--accent-positive)]">{row.altSymbol}</span>
                    <span className="text-[var(--text-tertiary)]">{row.altEr.toFixed(2)}% ER</span>
                    <ArrowRight size={11} className="text-[var(--text-tertiary)]" />
                    <span className="text-[var(--accent-positive)] font-medium">
                      saves {formatCurrency(row.annualSavings)}/yr
                    </span>
                    <span className="text-[var(--text-tertiary)]">
                      ({formatCurrency(row.savings30yr)} over 30 yrs)
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      <p className="text-[10px] text-[var(--text-tertiary)] pb-1">
        30-year projections assume 7% annual growth before fees. Expense ratios are approximate and subject to change.
        Always verify current ER on the fund provider's website.
      </p>
    </div>
  );
}

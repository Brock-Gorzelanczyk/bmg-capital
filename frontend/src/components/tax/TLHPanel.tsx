import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  TrendingDown,
  ArrowRight,
  CheckCircle2,
  Info,
  RefreshCw,
} from "lucide-react";
import { getTLHOpportunities } from "@/api/tlh";
import type { TLHOpportunity } from "@/api/tlh";
import { cn } from "@/lib/utils";

function fmt(n: number, decimals = 2): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

function OpportunityCard({ opp }: { opp: TLHOpportunity }) {
  const navigate = useNavigate();

  function handleHarvest() {
    // Navigate to paper trading with pre-filled sell order
    navigate(`/paper?action=sell&symbol=${opp.symbol}&shares=${opp.shares}`);
  }

  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-4 space-y-3">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-base font-bold text-[var(--text-primary)]">{opp.symbol}</span>
            <span className="text-xs text-[var(--text-tertiary)]">{opp.shares.toLocaleString()} shares</span>
          </div>
          <p className="text-xs text-[var(--text-tertiary)] mt-0.5">
            Avg cost {fmt(opp.average_cost)} &bull; Current {fmt(opp.current_price)}
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-base font-bold text-red-400">{fmt(opp.loss_dollars)}</p>
          <p className="text-xs text-red-400 font-medium">{opp.loss_pct.toFixed(2)}%</p>
        </div>
      </div>

      {/* Wash-sale warning */}
      {opp.wash_sale_risk && (
        <div className="flex items-start gap-2 bg-amber-500/10 border border-amber-500/25 rounded-lg px-3 py-2">
          <AlertTriangle size={14} className="text-amber-400 mt-0.5 shrink-0" />
          <p className="text-xs text-amber-300">
            Wash-sale risk: you purchased {opp.symbol} within the last 30 days.
            Selling now may disallow the loss deduction.
          </p>
        </div>
      )}

      {/* Suggested replacement */}
      {opp.suggested_replacement && (
        <div className="flex items-start gap-2 bg-blue-500/8 border border-blue-500/20 rounded-lg px-3 py-2">
          <ArrowRight size={14} className="text-blue-400 mt-0.5 shrink-0" />
          <p className="text-xs text-blue-300">{opp.suggested_replacement}</p>
        </div>
      )}

      {/* Harvest button */}
      <button
        onClick={handleHarvest}
        className="w-full flex items-center justify-center gap-2 py-2 px-4 rounded-lg bg-red-500/10 border border-red-500/25 text-red-400 text-sm font-medium hover:bg-red-500/20 transition-colors cursor-pointer"
      >
        <TrendingDown size={14} />
        Harvest this loss
      </button>
    </div>
  );
}

export default function TLHPanel() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["tlh-opportunities"],
    queryFn: getTLHOpportunities,
    staleTime: 5 * 60 * 1000,
  });

  return (
    <section className="space-y-4">
      {/* Section header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-[var(--text-primary)]">
            Tax-Loss Harvesting
          </h2>
          <p className="text-xs text-[var(--text-tertiary)] mt-0.5">
            Identify positions where realising losses can offset capital gains
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors cursor-pointer"
          title="Refresh"
        >
          <RefreshCw size={14} className={cn(isLoading && "animate-spin")} />
        </button>
      </div>

      {/* Summary strip */}
      {data && (
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 text-center">
            <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">
              Harvestable Loss
            </p>
            <p className="text-base font-bold text-red-400">
              {fmt(data.total_harvestable_loss)}
            </p>
          </div>
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 text-center">
            <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">
              Est. Tax Saved
            </p>
            <p className="text-base font-bold text-emerald-400">
              {fmt(data.estimated_tax_savings_24pct)}
            </p>
          </div>
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 text-center">
            <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">
              YTD Harvested
            </p>
            <p className="text-base font-bold text-emerald-400">
              {fmt(data.year_to_date_harvested)}
            </p>
          </div>
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-8 flex items-center justify-center gap-2 text-[var(--text-tertiary)]">
          <RefreshCw size={14} className="animate-spin" />
          <span className="text-sm">Scanning positions…</span>
        </div>
      )}

      {/* Error */}
      {error && !isLoading && (
        <div className="rounded-xl border border-red-900/40 bg-red-500/5 p-4 text-sm text-red-400">
          Failed to load TLH data. Please try refreshing.
        </div>
      )}

      {/* Opportunity cards */}
      {data && data.opportunities.length > 0 && (
        <div className="space-y-3">
          {data.opportunities.map((opp) => (
            <OpportunityCard key={`${opp.portfolio_id}-${opp.symbol}`} opp={opp} />
          ))}
        </div>
      )}

      {/* No opportunities empty state */}
      {data && data.opportunities.length === 0 && (
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6 text-center space-y-2">
          <CheckCircle2 size={24} className="text-emerald-400 mx-auto" />
          <p className="text-sm font-medium text-[var(--text-primary)]">
            No harvesting opportunities right now.
          </p>
          <p className="text-xs text-[var(--text-tertiary)] max-w-xs mx-auto">
            Your losers are less than 5% down. Check back during market volatility
            for harvesting opportunities.
          </p>
        </div>
      )}

      {/* Wash-sale education */}
      <div className="flex items-start gap-2.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-4">
        <Info size={14} className="text-[var(--text-tertiary)] mt-0.5 shrink-0" />
        <p className="text-xs text-[var(--text-tertiary)] leading-relaxed">
          <span className="font-semibold text-[var(--text-secondary)]">Wash-sale rule: </span>
          The wash-sale rule prevents claiming a loss if you buy a substantially
          identical security within 30 days before or after the sale. Use the suggested
          replacement securities to maintain market exposure during the 31-day window.
          Estimated tax savings use a 24% marginal rate — consult your tax advisor.
        </p>
      </div>
    </section>
  );
}

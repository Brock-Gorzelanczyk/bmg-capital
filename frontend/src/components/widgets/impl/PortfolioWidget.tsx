import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Briefcase } from "lucide-react";
import { getPortfolios } from "@/api/portfolio";
import { useMarketStore } from "@/store";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import { Card, CardLabel } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import SectorPill from "@/components/ui/SectorPill";

export default function PortfolioWidget() {
  const navigate = useNavigate();
  const quotes = useMarketStore((s) => s.quotes);
  const { data: rawPortfolios, isLoading } = useQuery({ queryKey: ["portfolios"], queryFn: getPortfolios, staleTime: 30_000 });
  const portfolios: any[] = Array.isArray(rawPortfolios) ? rawPortfolios : [];

  if (isLoading) return (
    <Card className="h-full">
      <Skeleton height={14} className="w-24 mb-4" />
      <Skeleton height={32} className="w-36 mb-4" />
      <div className="space-y-2.5">{[1,2,3,4].map((i) => <Skeleton key={i} height={36} />)}</div>
    </Card>
  );

  const allPositions = portfolios.flatMap((p: any) => Array.isArray(p.positions) ? p.positions : []);
  const totalValue = allPositions.reduce((s, p) => s + p.shares * (quotes[p.symbol]?.price ?? 0), 0);
  const totalCost = allPositions.reduce((s, p) => s + p.cost_basis, 0);
  const totalGain = totalValue - totalCost;
  const gainPct = totalCost > 0 ? (totalGain / totalCost) * 100 : 0;
  const isPos = totalGain >= 0;
  const topHoldings = [...allPositions]
    .sort((a, b) => b.shares * (quotes[b.symbol]?.price ?? 0) - a.shares * (quotes[a.symbol]?.price ?? 0))
    .slice(0, 4);

  return (
    <Card glow className="h-full overflow-auto">
      <div className="flex items-center justify-between mb-4">
        <CardLabel className="mb-0 flex items-center gap-1.5"><Briefcase size={12} /> Portfolio</CardLabel>
        <button onClick={() => navigate("/portfolio")} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-xs flex items-center gap-1 transition-colors cursor-pointer">
          View all <ArrowRight size={11} />
        </button>
      </div>
      {allPositions.length === 0 ? (
        <div className="py-6 text-center text-[var(--text-tertiary)] text-sm">
          No positions yet.{" "}
          <button onClick={() => navigate("/portfolio")} className="text-[var(--text-primary)] hover:underline cursor-pointer">Add one →</button>
        </div>
      ) : (
        <>
          <div className="mb-4 pb-4 border-b border-[var(--border-subtle)]">
            <div className="text-2xl font-semibold text-[var(--text-primary)] font-mono">{formatCurrency(totalValue)}</div>
            {totalCost > 0 && (
              <div className="flex items-center gap-2 mt-1.5">
                <span className={cn("text-xs font-semibold px-2 py-0.5 rounded-full", isPos ? "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)]" : "bg-[var(--accent-negative-bg)] text-[var(--accent-negative)]")}>
                  {isPos ? "+" : ""}{formatPercent(gainPct)}
                </span>
                <span className={cn("text-xs font-mono", isPos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                  {isPos ? "+" : ""}{formatCurrency(totalGain)}
                </span>
              </div>
            )}
          </div>
          <div className="space-y-1">
            {topHoldings.map((pos) => {
              const price = quotes[pos.symbol]?.price ?? 0;
              const mv = pos.shares * price;
              const pnl = mv - pos.cost_basis;
              const isPosRow = pnl >= 0;
              return (
                <div key={pos.symbol} className="flex items-center justify-between cursor-pointer hover:bg-[var(--bg-elevated-2)]/50 -mx-2 px-2 py-1.5 rounded transition-colors" onClick={() => navigate(`/chart?symbol=${pos.symbol}`)}>
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-[var(--text-primary)] text-sm">{pos.symbol}</span>
                    <SectorPill symbol={pos.symbol} />
                  </div>
                  <div className="text-right">
                    <div className="text-sm text-[var(--text-primary)] font-mono">{price > 0 ? formatCurrency(mv) : "—"}</div>
                    {price > 0 && <div className={cn("text-xs font-mono", isPosRow ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>{formatPercent((pnl / pos.cost_basis) * 100)}</div>}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </Card>
  );
}

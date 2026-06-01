import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { LineChart, AlertCircle } from "lucide-react";
import { getMarketOverview } from "@/api/market";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import { SkeletonCard } from "@/components/ui/Skeleton";

const INDEX_NAMES: Record<string, string> = {
  SPY: "S&P 500", QQQ: "NASDAQ 100", DIA: "Dow Jones", IWM: "Russell 2000",
  VXX: "Volatility", GLD: "Gold", TLT: "10Y Treasury",
};

// Sanity bounds — ETF prices outside these ranges signal bad data
const PRICE_BOUNDS: Record<string, [number, number]> = {
  SPY: [200, 1200], QQQ: [150, 1000], DIA: [200, 1000], IWM: [100, 500],
};
function isBadPrice(symbol: string, price: number): boolean {
  const [lo, hi] = PRICE_BOUNDS[symbol] ?? [1, 1e6];
  return !price || price < lo || price > hi;
}

export default function MarketIndicesWidget() {
  const navigate = useNavigate();
  const { data: rawIndices, isLoading } = useQuery({
    queryKey: ["market-overview"],
    queryFn: getMarketOverview,
    refetchInterval: 60_000,
  });
  const indices: any[] = Array.isArray(rawIndices) ? rawIndices : [];

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 h-full content-start">
        {[1, 2, 3, 4].map((i) => <SkeletonCard key={i} />)}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 h-full content-start auto-rows-min">
      {indices.map((idx: any) => {
        const bad = isBadPrice(idx.symbol, idx.price);
        const isPos = idx.change_pct >= 0;
        const accentColor = bad ? "var(--border-emphasis)" : isPos ? "var(--accent-positive)" : "var(--accent-negative)";
        return (
          <div
            key={idx.symbol}
            onClick={() => navigate(`/chart?symbol=${idx.symbol}`)}
            className="relative rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated-2)] p-4 flex flex-col gap-1.5 hover:border-[var(--border-emphasis)] transition-colors cursor-pointer group card-glow overflow-hidden"
            style={{ borderTop: `2px solid ${accentColor}` }}
          >
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest truncate">
                {INDEX_NAMES[idx.symbol] ?? idx.symbol}
              </span>
              {bad
                ? <AlertCircle size={11} className="text-[var(--text-tertiary)] shrink-0" aria-label="Price data unavailable" />
                : <LineChart size={11} className="text-[var(--text-tertiary)] group-hover:text-[var(--accent-positive)] transition-colors shrink-0" />
              }
            </div>
            <div className="text-lg font-semibold text-[var(--text-primary)] font-mono">
              {bad ? "—" : formatCurrency(idx.price)}
            </div>
            {bad ? (
              <span className="text-xs text-[var(--text-tertiary)]">Data unavailable</span>
            ) : (
              <span className={cn(
                "text-xs font-semibold px-2 py-0.5 rounded-full w-fit",
                isPos ? "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)]" : "bg-[var(--accent-negative-bg)] text-[var(--accent-negative)]"
              )}>
                {formatPercent(idx.change_pct)}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

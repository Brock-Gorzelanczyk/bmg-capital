import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp, TrendingDown, Zap } from "lucide-react";
import { cn, formatCurrency, formatPercent } from "@/lib/utils";
import { getMarketOverview } from "@/api/market";

const SECTOR_ETFS = [
  { symbol: "XLK", name: "Technology" },
  { symbol: "XLF", name: "Financials" },
  { symbol: "XLV", name: "Healthcare" },
  { symbol: "XLE", name: "Energy" },
  { symbol: "XLI", name: "Industrials" },
  { symbol: "XLC", name: "Comm. Svcs" },
  { symbol: "XLY", name: "Cons. Discret." },
  { symbol: "XLP", name: "Cons. Staples" },
  { symbol: "XLB", name: "Materials" },
  { symbol: "XLRE", name: "Real Estate" },
  { symbol: "XLU", name: "Utilities" },
];

const NAMES: Record<string, string> = Object.fromEntries(SECTOR_ETFS.map((s) => [s.symbol, s.name]));

export default function TopMoversWidget() {
  const navigate = useNavigate();

  const { data: rawData = [], isLoading } = useQuery({
    queryKey: ["market-overview"],
    queryFn: getMarketOverview,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const sorted = [...rawData].sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct));
  const gainers = sorted.filter((x) => x.change_pct > 0).slice(0, 4);
  const losers  = sorted.filter((x) => x.change_pct < 0).slice(0, 4);

  if (isLoading) {
    return (
      <div className="space-y-1.5">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-9 bg-[var(--bg-elevated-2)] animate-pulse rounded-lg" />
        ))}
      </div>
    );
  }

  const Row = ({ item, accent }: { item: any; accent: "pos" | "neg" }) => {
    const isUp = item.change_pct >= 0;
    const name = NAMES[item.symbol] ?? item.symbol;
    return (
      <button
        onClick={() => navigate(`/chart?symbol=${item.symbol}`)}
        className="w-full flex items-center justify-between px-2.5 py-2 rounded-lg hover:bg-[var(--bg-elevated-2)] transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <div className={cn(
            "w-6 h-6 rounded-md flex items-center justify-center shrink-0",
            isUp ? "bg-[var(--accent-positive-bg)]" : "bg-[var(--accent-negative-bg)]"
          )}>
            {isUp
              ? <TrendingUp size={11} className="text-[var(--accent-positive)]" />
              : <TrendingDown size={11} className="text-[var(--accent-negative)]" />
            }
          </div>
          <div className="min-w-0 text-left">
            <div className="font-mono font-bold text-sm text-[var(--text-primary)]">{item.symbol}</div>
            <div className="text-[10px] text-[var(--text-tertiary)] truncate">{name}</div>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="font-mono text-sm text-[var(--text-primary)]">{formatCurrency(item.price)}</div>
          <div className={cn(
            "text-xs font-semibold font-mono",
            isUp ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"
          )}>
            {isUp ? "+" : ""}{formatPercent(item.change_pct)}
          </div>
        </div>
      </button>
    );
  };

  return (
    <div className="h-full overflow-auto space-y-3">
      {gainers.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 px-2 mb-1">
            <TrendingUp size={11} className="text-[var(--accent-positive)]" />
            <span className="text-[10px] font-semibold text-[var(--accent-positive)] uppercase tracking-widest">Top Gainers</span>
          </div>
          {gainers.map((item) => <Row key={item.symbol} item={item} accent="pos" />)}
        </div>
      )}
      {losers.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 px-2 mb-1">
            <TrendingDown size={11} className="text-[var(--accent-negative)]" />
            <span className="text-[10px] font-semibold text-[var(--accent-negative)] uppercase tracking-widest">Top Losers</span>
          </div>
          {losers.map((item) => <Row key={item.symbol} item={item} accent="neg" />)}
        </div>
      )}
      {gainers.length === 0 && losers.length === 0 && (
        <div className="h-full flex flex-col items-center justify-center gap-2">
          <Zap size={24} className="text-[var(--border-emphasis)]" />
          <p className="text-sm text-[var(--text-tertiary)]">No data yet</p>
        </div>
      )}
    </div>
  );
}

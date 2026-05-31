import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BookMarked, TrendingUp, TrendingDown } from "lucide-react";
import { getWatchlists, getSnapshot } from "@/api/watchlist";
import { cn, formatCurrency, formatPercent } from "@/lib/utils";

export default function WatchlistTableWidget() {
  const navigate = useNavigate();

  const { data: watchlists = [] } = useQuery({
    queryKey: ["watchlists"],
    queryFn: getWatchlists,
    staleTime: 60_000,
  });

  const firstList = watchlists[0];

  const { data: snapshots = [], isLoading } = useQuery({
    queryKey: ["watchlist-snapshot", firstList?.id],
    queryFn: () => getSnapshot(firstList!.id),
    enabled: !!firstList?.id,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  if (!firstList) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-2 text-center px-4">
        <BookMarked size={24} className="text-[var(--border-emphasis)]" />
        <p className="text-sm text-[var(--text-tertiary)]">No watchlist yet</p>
        <button
          onClick={() => navigate("/watchlist")}
          className="text-xs text-[var(--accent-positive)] hover:underline"
        >
          Create one →
        </button>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-1 pt-1">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-8 bg-[var(--bg-elevated-2)] animate-pulse rounded-lg" />
        ))}
      </div>
    );
  }

  if (snapshots.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-2 text-center px-4">
        <BookMarked size={24} className="text-[var(--border-emphasis)]" />
        <p className="text-sm text-[var(--text-tertiary)]">Watchlist is empty</p>
        <button
          onClick={() => navigate("/watchlist")}
          className="text-xs text-[var(--accent-positive)] hover:underline"
        >
          Add symbols →
        </button>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto">
      <div className="flex items-center justify-between px-2 pb-2">
        <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">
          {firstList.name}
        </span>
        <button
          onClick={() => navigate("/watchlist")}
          className="text-[10px] text-[var(--accent-positive)] hover:underline"
        >
          Manage →
        </button>
      </div>
      <div className="space-y-px">
        {snapshots.map((snap) => {
          const isUp = snap.change_pct >= 0;
          return (
            <button
              key={snap.symbol}
              onClick={() => navigate(`/chart?symbol=${snap.symbol}`)}
              className="w-full flex items-center justify-between px-2 py-2 rounded-lg hover:bg-[var(--bg-elevated-2)] transition-colors group text-left"
            >
              <div className="flex items-center gap-2 min-w-0">
                <div className="w-6 h-6 rounded-md bg-[var(--bg-elevated-2)] flex items-center justify-center shrink-0">
                  {isUp
                    ? <TrendingUp size={11} className="text-[var(--accent-positive)]" />
                    : <TrendingDown size={11} className="text-[var(--accent-negative)]" />
                  }
                </div>
                <span className="font-mono font-bold text-sm text-[var(--text-primary)]">{snap.symbol}</span>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <span className="font-mono text-sm text-[var(--text-primary)]">{formatCurrency(snap.price)}</span>
                <span className={cn(
                  "text-xs font-semibold font-mono w-16 text-right",
                  isUp ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"
                )}>
                  {isUp ? "+" : ""}{formatPercent(snap.change_pct)}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

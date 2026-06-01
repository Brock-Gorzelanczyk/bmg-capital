import { useQuery } from "@tanstack/react-query";
import type { IDockviewPanelProps } from "dockview";
import { cn } from "@/lib/utils";
import client from "@/api/client";

const DEFAULT_SYMBOLS = ["AAPL", "NVDA", "TSLA", "SPY", "QQQ"];

interface QuoteData {
  symbol: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
}

async function fetchQuotes(symbols: string[]): Promise<QuoteData[]> {
  try {
    const res = await client.get(`/market/quotes?symbols=${symbols.join(",")}`);
    return res.data;
  } catch {
    // If quotes endpoint isn't available, return placeholder
    return symbols.map((s) => ({ symbol: s, price: null, change: null, change_pct: null }));
  }
}

export default function WatchlistWidget(_props: IDockviewPanelProps) {
  const { data = [], isLoading } = useQuery<QuoteData[]>({
    queryKey: ["watchlist-widget-quotes", DEFAULT_SYMBOLS.join(",")],
    queryFn: () => fetchQuotes(DEFAULT_SYMBOLS),
    staleTime: 30_000,
    retry: false,
  });

  // Merge with defaults to ensure all symbols appear
  const rows: QuoteData[] = DEFAULT_SYMBOLS.map((sym) => {
    const found = data.find((q) => q.symbol === sym);
    return found ?? { symbol: sym, price: null, change: null, change_pct: null };
  });

  const fmt$ = (n: number) =>
    n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

  return (
    <div className="flex flex-col h-full bg-[var(--bg-elevated)] text-[var(--text-primary)]">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-subtle)]">
        <span className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">
          Watchlist
        </span>
        <span className="text-[10px] text-[var(--text-tertiary)]">{DEFAULT_SYMBOLS.length} symbols</span>
      </div>

      {/* Rows */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-full text-[var(--text-tertiary)] text-xs">
            Loading…
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[var(--border-subtle)]">
                <th className="px-3 py-2 text-left text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">
                  Symbol
                </th>
                <th className="px-3 py-2 text-right text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">
                  Price
                </th>
                <th className="px-3 py-2 text-right text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">
                  Change
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((q) => (
                <tr
                  key={q.symbol}
                  className="border-b border-[var(--border-subtle)]/40 hover:bg-white/5 transition-colors"
                >
                  <td className="px-3 py-2.5 font-mono font-bold text-[var(--text-primary)]">
                    {q.symbol}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-right text-[var(--text-secondary)]">
                    {q.price != null ? fmt$(q.price) : "—"}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-2.5 font-mono font-semibold text-right",
                      q.change_pct == null && "text-[var(--text-tertiary)]",
                      q.change_pct != null && q.change_pct >= 0 && "text-[var(--accent-positive)]",
                      q.change_pct != null && q.change_pct < 0 && "text-[var(--accent-negative)]"
                    )}
                  >
                    {q.change_pct != null
                      ? `${q.change_pct >= 0 ? "+" : ""}${q.change_pct.toFixed(2)}%`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

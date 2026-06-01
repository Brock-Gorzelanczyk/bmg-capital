import { useQuery } from "@tanstack/react-query";
import type { IDockviewPanelProps } from "dockview";
import { cn } from "@/lib/utils";
import { getLatestRecap, type DailyRecap } from "@/api/recap";

const fmtPct = (n: number | null) =>
  n == null ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;

export default function DailyRecapWidget(_props: IDockviewPanelProps) {
  const { data, isLoading, error } = useQuery<DailyRecap | null>({
    queryKey: ["latest-recap-widget"],
    queryFn: getLatestRecap,
    staleTime: 5 * 60_000,
    retry: false,
  });

  return (
    <div className="flex flex-col h-full bg-[var(--bg-elevated)] text-[var(--text-primary)]">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2">
          <span className="text-base leading-none">☀️</span>
          <span className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">
            Daily Recap
          </span>
        </div>
        {data?.recap_date && (
          <span className="text-[10px] text-[var(--text-tertiary)]">{data.recap_date}</span>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto px-3 py-2">
        {isLoading && (
          <div className="flex items-center justify-center h-full text-[var(--text-tertiary)] text-xs">
            Loading brief…
          </div>
        )}

        {(error || (!isLoading && !data)) && (
          <div className="flex flex-col items-center justify-center h-full gap-1 text-[var(--text-tertiary)]">
            <span className="text-2xl">☀️</span>
            <span className="text-xs text-center leading-relaxed">
              Morning brief not available — check API key
            </span>
          </div>
        )}

        {!isLoading && data && (
          <div className="space-y-4">
            {/* Market summary */}
            {data.market_summary && (
              <div>
                <div className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-1.5">
                  Market
                </div>
                <div className="grid grid-cols-4 gap-2">
                  {(
                    [
                      { label: "SPY", val: data.market_summary.spy },
                      { label: "QQQ", val: data.market_summary.qqq },
                      { label: "IWM", val: data.market_summary.iwm },
                      { label: "VIX", val: data.market_summary.vix },
                    ] as { label: string; val: number | null }[]
                  ).map(({ label, val }) => (
                    <div
                      key={label}
                      className="bg-[var(--bg-elevated-2)] rounded-lg p-2 text-center"
                    >
                      <div className="text-[9px] text-[var(--text-tertiary)] uppercase">{label}</div>
                      <div
                        className={cn(
                          "text-xs font-mono font-bold mt-0.5",
                          val == null
                            ? "text-[var(--text-tertiary)]"
                            : val >= 0
                            ? "text-[var(--accent-positive)]"
                            : "text-[var(--accent-negative)]"
                        )}
                      >
                        {fmtPct(val)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Strategy summary */}
            {data.strategy_summary && (
              <div>
                <div className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-1.5">
                  Strategy
                </div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div className="bg-[var(--bg-elevated-2)] rounded-lg p-2">
                    <div className="text-[9px] text-[var(--text-tertiary)]">Entries</div>
                    <div className="text-sm font-bold text-emerald-400">
                      {data.strategy_summary.new_entries}
                    </div>
                  </div>
                  <div className="bg-[var(--bg-elevated-2)] rounded-lg p-2">
                    <div className="text-[9px] text-[var(--text-tertiary)]">Exits</div>
                    <div className="text-sm font-bold text-[var(--text-primary)]">
                      {data.strategy_summary.exits}
                    </div>
                  </div>
                  <div className="bg-[var(--bg-elevated-2)] rounded-lg p-2">
                    <div className="text-[9px] text-[var(--text-tertiary)]">Open</div>
                    <div className="text-sm font-bold text-blue-400">
                      {data.strategy_summary.open_positions}
                    </div>
                  </div>
                </div>
                <div
                  className={cn(
                    "mt-2 rounded-lg p-2 text-center text-xs font-mono font-bold",
                    data.strategy_summary.day_pnl_pct >= 0
                      ? "bg-emerald-500/10 text-emerald-400"
                      : "bg-red-500/10 text-red-400"
                  )}
                >
                  Day P&L: {fmtPct(data.strategy_summary.day_pnl_pct)}
                </div>
              </div>
            )}

            {/* Top setups */}
            {data.top_setups && data.top_setups.length > 0 && (
              <div>
                <div className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-1.5">
                  Top Setups
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {data.top_setups.map((s, i) => (
                    <span
                      key={i}
                      className="px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-300 text-[10px] font-mono"
                    >
                      {s.symbol}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Narrative */}
            {data.narrative && (
              <div>
                <div className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-1.5">
                  AI Brief
                </div>
                <div className="text-xs text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap">
                  {data.narrative}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { IDockviewPanelProps } from "dockview";
import { cn } from "@/lib/utils";
import client from "@/api/client";
import type { PaperAccount } from "@/api/paper";

type SortKey = "symbol" | "qty" | "avg_cost" | "current_price" | "day_pnl" | "unrealized_pnl_pct";

const fmt$ = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

const fmtPct = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;

export default function PositionBlotterWidget(_props: IDockviewPanelProps) {
  const [sortKey, setSortKey] = useState<SortKey>("symbol");
  const [sortDir, setSortDir] = useState<1 | -1>(1);

  const { data, isLoading, error } = useQuery<PaperAccount>({
    queryKey: ["paper-account-widget"],
    queryFn: () => client.get("/paper/account").then((r) => r.data),
    staleTime: 30_000,
  });

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 1 ? -1 : 1));
    } else {
      setSortKey(key);
      setSortDir(1);
    }
  }

  const positions = [...(data?.positions ?? [])].sort((a, b) => {
    const aVal = a[sortKey] ?? 0;
    const bVal = b[sortKey] ?? 0;
    if (typeof aVal === "string") return sortDir * aVal.localeCompare(bVal as string);
    return sortDir * ((aVal as number) - (bVal as number));
  });

  const TH = ({ col, label }: { col: SortKey; label: string }) => (
    <th
      onClick={() => handleSort(col)}
      className="px-3 py-2 text-left text-[10px] uppercase tracking-wider text-[var(--text-tertiary)] cursor-pointer hover:text-[var(--text-secondary)] select-none whitespace-nowrap"
    >
      {label}
      {sortKey === col && <span className="ml-1">{sortDir === 1 ? "↑" : "↓"}</span>}
    </th>
  );

  return (
    <div className="flex flex-col h-full bg-[var(--bg-elevated)] text-[var(--text-primary)]">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-subtle)]">
        <span className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">
          Open Positions
        </span>
        {data && (
          <span className="text-[10px] text-[var(--text-tertiary)]">
            {positions.length} position{positions.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto">
        {isLoading && (
          <div className="flex items-center justify-center h-full text-[var(--text-tertiary)] text-xs">
            Loading positions…
          </div>
        )}
        {error && (
          <div className="flex items-center justify-center h-full text-red-400 text-xs">
            Failed to load positions
          </div>
        )}
        {!isLoading && !error && positions.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-1 text-[var(--text-tertiary)]">
            <span className="text-2xl">📋</span>
            <span className="text-xs">No open positions</span>
          </div>
        )}
        {!isLoading && positions.length > 0 && (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-[var(--bg-elevated)]">
              <tr className="border-b border-[var(--border-subtle)]">
                <TH col="symbol" label="Symbol" />
                <TH col="qty" label="Shares" />
                <TH col="avg_cost" label="Avg Cost" />
                <TH col="current_price" label="Current" />
                <TH col="day_pnl" label="Day P&L" />
                <TH col="unrealized_pnl_pct" label="Total Return" />
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr
                  key={p.id}
                  className="border-b border-[var(--border-subtle)]/40 hover:bg-white/5 transition-colors"
                >
                  <td className="px-3 py-2 font-mono font-bold text-[var(--text-primary)]">
                    {p.symbol}
                  </td>
                  <td className="px-3 py-2 font-mono text-[var(--text-secondary)]">{p.qty}</td>
                  <td className="px-3 py-2 font-mono text-[var(--text-secondary)]">
                    {fmt$(p.avg_cost)}
                  </td>
                  <td className="px-3 py-2 font-mono text-[var(--text-primary)]">
                    {fmt$(p.current_price)}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-2 font-mono font-semibold",
                      p.day_pnl >= 0
                        ? "text-[var(--accent-positive)]"
                        : "text-[var(--accent-negative)]"
                    )}
                  >
                    {fmtPct(p.day_pnl_pct)}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-2 font-mono font-semibold",
                      p.unrealized_pnl_pct >= 0
                        ? "text-[var(--accent-positive)]"
                        : "text-[var(--accent-negative)]"
                    )}
                  >
                    {fmtPct(p.unrealized_pnl_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer summary */}
      {data && (
        <div className="flex items-center justify-between px-3 py-2 border-t border-[var(--border-subtle)] text-[10px] text-[var(--text-tertiary)]">
          <span>Equity: <span className="text-[var(--text-primary)] font-mono">{fmt$(data.equity)}</span></span>
          <span className={cn("font-mono font-semibold", data.day_pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
            Day: {fmtPct(data.day_pnl_pct)}
          </span>
        </div>
      )}
    </div>
  );
}

import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import {
  getCrossBotPositions,
  getBots,
  getOpenPositions,
  getStrategyLabPortfolio,
  type CrossBotPosition,
} from "@/api/bots";
import { cn } from "@/lib/utils";
import AllocationDonut from "@/components/ui/AllocationDonut";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatPnl(val: number): string {
  const abs = Math.abs(val);
  const sign = val >= 0 ? "+" : "-";
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(2)}`;
}

// ─── Summary card ─────────────────────────────────────────────────────────────

function SummaryCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-4 flex-1 min-w-[140px]">
      <p className="text-zinc-500 text-xs mb-1">{label}</p>
      <p className="text-white text-xl font-bold">{value}</p>
      {sub && <p className="text-zinc-600 text-xs mt-0.5">{sub}</p>}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function NetPortfolio() {
  const navigate = useNavigate();

  const { data: rawPositions, isLoading: posLoading } = useQuery({
    queryKey: ["cross-bot-positions"],
    queryFn: getCrossBotPositions,
    retry: 0,
    staleTime: 30_000,
  });
  const positions: CrossBotPosition[] = Array.isArray(rawPositions) ? rawPositions : [];

  const { data: botsData } = useQuery({
    queryKey: ["bots-v2"],
    queryFn: getBots,
    retry: 1,
    staleTime: 30_000,
  });

  // Open positions with live current_value_usd per position — used for the donut
  const { data: openPosData } = useQuery({
    queryKey: ["open-positions"],
    queryFn: getOpenPositions,
    refetchInterval: 30_000,
    staleTime: 25_000,
    retry: 0,
  });

  // Total portfolio value for Cash calculation
  const { data: portfolioAgg } = useQuery({
    queryKey: ["strategy-lab-portfolio"],
    queryFn: getStrategyLabPortfolio,
    staleTime: 60_000,
    retry: 0,
  });

  const bots = botsData?.bots ?? [];
  const activeBots = bots.filter((b) => b.allocation?.enabled).length;

  const totalPnl = positions.reduce((sum: number, p: CrossBotPosition) => sum + (p.pnl ?? 0), 0);
  const totalExposure = positions.reduce(
    (sum: number, p: CrossBotPosition) => sum + (p.exposure_pct ?? 0),
    0
  );
  const openPositions = positions.length;

  // ── Allocation donut: sum current_value_usd by asset_class ──────────────────
  const totalCents = portfolioAgg?.total_value_cents ?? 0;
  const deployedByClass: Record<string, number> = {};
  for (const pos of openPosData?.positions ?? []) {
    const cls = pos.asset_class ?? "other";
    deployedByClass[cls] = (deployedByClass[cls] ?? 0) + Math.round((pos.current_value_usd ?? 0) * 100);
  }
  const totalDeployedCents = Object.values(deployedByClass).reduce((s, v) => s + v, 0);
  const cashCents = Math.max(0, totalCents - totalDeployedCents);

  const donutSlices = [
    ...Object.entries(deployedByClass)
      .filter(([, v]) => v > 0)
      .map(([key, value_cents]) => ({ key, value_cents })),
    ...(cashCents > 0 ? [{ key: "cash", value_cents: cashCents }] : []),
  ];

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate("/strategy")}
          className="flex items-center gap-1.5 text-zinc-500 hover:text-white text-sm transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Strategy Lab
        </button>
      </div>

      <div>
        <h1 className="text-2xl font-bold text-white">Portfolio View</h1>
        <p className="text-zinc-500 text-sm mt-1">
          Consolidated paper-trading positions across all active bots.
        </p>
      </div>

      {/* Paper banner */}
      <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 flex items-center gap-3">
        <span className="text-amber-400 text-sm font-semibold">Paper trading only.</span>
        <span className="text-amber-300 text-xs">
          Live trading coming soon — paper trading only until RIA registration.
        </span>
      </div>

      {/* Allocation donut — full-width, above the table */}
      {totalCents > 0 && donutSlices.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
          <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-4">Capital Allocation</p>
          <AllocationDonut slices={donutSlices} totalCents={totalCents} size={160} />
        </div>
      )}

      {/* Summary cards */}
      {posLoading ? (
        <div className="flex flex-wrap gap-4 animate-pulse">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex-1 min-w-[140px] h-20 bg-zinc-900 border border-zinc-800 rounded-2xl" />
          ))}
        </div>
      ) : positions.length === 0 ? (
        <div className="flex items-center justify-center py-16 text-zinc-500 text-sm text-center">
          No open positions. Bots scan continuously — check back shortly.
        </div>
      ) : (
        <div className="flex flex-wrap gap-4">
          <SummaryCard label="Total Paper P&L" value={formatPnl(totalPnl)} sub="all bots combined" />
          <SummaryCard label="Total Exposure" value={`${totalExposure.toFixed(1)}%`} sub="weighted across portfolio" />
          <SummaryCard label="Open Positions" value={String(openPositions)} sub="across all bots" />
          <SummaryCard label="Bots Active" value={String(activeBots)} sub={`of ${bots.length} total`} />
        </div>
      )}

      {/* Exposure by symbol table */}
      {positions.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
          <h2 className="text-sm font-semibold text-zinc-300 mb-4">Exposure by Symbol</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-zinc-600 border-b border-zinc-800">
                  <th className="text-left pb-2 font-medium">Symbol</th>
                  <th className="text-right pb-2 font-medium">Total Qty</th>
                  <th className="text-left pb-2 font-medium">Bots Holding</th>
                  <th className="text-right pb-2 font-medium">Exposure %</th>
                  <th className="text-right pb-2 font-medium">P&L</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p: CrossBotPosition) => (
                  <tr
                    key={p.symbol}
                    className="border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/20 transition-colors"
                  >
                    <td className="py-2.5 font-semibold text-white">{p.symbol}</td>
                    <td className="py-2.5 text-right text-zinc-300">{p.total_qty}</td>
                    <td className="py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {(p.bots_holding ?? []).map((b) => (
                          <span
                            key={b}
                            className="text-xs px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700"
                          >
                            {b.replace(/_/g, " ")}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="py-2.5 text-right text-zinc-300">{p.exposure_pct?.toFixed(1)}%</td>
                    <td className={cn("py-2.5 text-right font-semibold text-xs", (p.pnl ?? 0) >= 0 ? "text-lime-400" : "text-red-400")}>
                      {formatPnl(p.pnl ?? 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Return link */}
      <div className="flex justify-center pt-4">
        <button
          onClick={() => navigate("/strategy")}
          className="text-zinc-500 hover:text-white text-sm underline underline-offset-4 transition-colors"
        >
          Back to Command Center
        </button>
      </div>

      <p className="text-xs text-center text-zinc-600">
        Paper trading. Not investment advice. Not a registered investment adviser.
      </p>
    </div>
  );
}

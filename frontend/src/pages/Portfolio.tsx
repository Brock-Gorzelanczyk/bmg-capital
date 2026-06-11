import { useQuery } from "@tanstack/react-query";
import { TrendingUp, TrendingDown, Layers, Activity } from "lucide-react";
import { getStrategyLabPortfolio, getPortfolios, getOpenPositions } from "@/api/bots";
import { cn, formatCurrency, formatPercent } from "@/lib/utils";
import AllocationDonut from "@/components/ui/AllocationDonut";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtUsd(cents: number) {
  return formatCurrency(cents / 100);
}

function fmtPct(pct: number) {
  return formatPercent(pct / 100);
}

const ASSET_LABELS: Record<string, string> = {
  stocks:  "Equities",
  crypto:  "Digital Assets",
  options: "Derivatives",
};

const ASSET_COLORS: Record<string, string> = {
  stocks:  "bg-blue-500/10 text-blue-400 border-blue-500/20",
  crypto:  "bg-t-green/10 text-t-green border-t-mid",
  options: "bg-purple-500/10 text-purple-400 border-purple-500/20",
};

// ─── Sub-components ──────────────────────────────────────────────────────────

function StatCard({ label, value, sub, positive }: {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean;
}) {
  return (
    <div className="bg-t-bg1 border border-t-dim rounded-xl p-4 card-hover">
      <p className="text-xs text-t-muted mb-1">{label}</p>
      <p className={cn("text-xl font-bold font-mono-t tabular-nums", positive === undefined ? "text-t-hi" : positive ? "text-t-green" : "text-t-red")}>
        {value}
      </p>
      {sub && <p className="text-xs text-t-muted mt-0.5">{sub}</p>}
    </div>
  );
}

function BotRow({ bot }: { bot: any }) {
  const val = bot.portfolio_value_cents ?? 0;
  const pnl = bot.today_pnl_cents ?? 0;
  const ret30 = bot.return_30d_pct ?? 0;
  const allTime = bot.all_time_return_pct ?? 0;
  const pos = val >= 0;
  const retPos = ret30 >= 0;

  return (
    <div className="flex items-center justify-between py-3 border-b border-t-dim/50 last:border-0">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-t-hi truncate">
          {bot.display_name ?? bot.name ?? bot.profile_name}
        </p>
        <p className="text-xs text-t-muted">
          {bot.open_positions_count ?? 0} open · {bot.watchlist_count ?? 0} watching
        </p>
      </div>
      <div className="text-right ml-4">
        <p className="text-sm font-semibold font-mono-t tabular-nums text-t-hi">{fmtUsd(val)}</p>
        <p className={cn("text-xs font-mono-t tabular-nums", retPos ? "text-t-green" : "text-t-red")}>
          {retPos ? "+" : ""}{ret30.toFixed(2)}% 30d
        </p>
      </div>
      <div className="text-right ml-6 w-20">
        <p className={cn("text-sm font-medium font-mono-t tabular-nums", pnl >= 0 ? "text-t-green" : "text-t-red")}>
          {pnl >= 0 ? "+" : ""}{fmtUsd(pnl)}
        </p>
        <p className="text-xs text-t-muted">today</p>
      </div>
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function Portfolio() {
  const { data: agg, isLoading: aggLoading } = useQuery({
    queryKey: ["strategy-lab-portfolio"],
    queryFn: getStrategyLabPortfolio,
    staleTime: 30_000,
  });

  const { data: portfoliosData, isLoading: portsLoading } = useQuery({
    queryKey: ["bots-portfolios"],
    queryFn: getPortfolios,
    staleTime: 30_000,
  });

  const { data: openPosData } = useQuery({
    queryKey: ["open-positions"],
    queryFn: getOpenPositions,
    staleTime: 30_000,
    retry: 0,
  });

  const loading = aggLoading || portsLoading;
  const totalValue = agg?.total_value_cents ?? 0;
  const todayPnl = agg?.today_pnl_cents ?? 0;
  const todayPct = agg?.today_pnl_pct ?? 0;
  const ret30 = agg?.return_30d_pct ?? 0;
  const retAll = agg?.return_all_time_pct ?? 0;
  const openPos = agg?.total_open_positions ?? 0;
  const isUp = todayPnl >= 0;

  const portfolios = portfoliosData?.portfolios ?? [];

  return (
    <div className="min-h-screen bg-t-bg0 text-t-hi animate-page-in">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-10">

        {/* Header */}
        <div className="mb-8">
          <p className="text-xs text-t-muted uppercase tracking-widest mb-1">BMG Capital · Portfolio</p>
          <div className="flex items-end gap-4 flex-wrap">
            <div>
              <p className="text-5xl font-bold tracking-tight font-mono-t tabular-nums">
                {loading ? <span className="text-t-dim">$—</span> : fmtUsd(totalValue)}
              </p>
              <div className="flex items-center gap-3 mt-2 flex-wrap">
                <span className={cn("flex items-center gap-1 text-lg font-semibold font-mono-t tabular-nums", isUp ? "text-t-green" : "text-t-red")}>
                  {isUp ? <TrendingUp size={18} /> : <TrendingDown size={18} />}
                  {isUp ? "+" : ""}{fmtUsd(todayPnl)}
                  <span className="text-sm font-normal font-mono-t tabular-nums">({todayPct >= 0 ? "+" : ""}{todayPct.toFixed(2)}% today)</span>
                </span>
                <span className="text-t-muted">·</span>
                <span className={cn("text-sm font-mono-t tabular-nums", ret30 >= 0 ? "text-t-green/70" : "text-t-red/70")}>
                  {ret30 >= 0 ? "+" : ""}{ret30.toFixed(2)}% 30d
                </span>
                <span className={cn("text-sm font-mono-t tabular-nums", retAll >= 0 ? "text-t-green/70" : "text-t-red/70")}>
                  {retAll >= 0 ? "+" : ""}{retAll.toFixed(2)}% all-time
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Allocation donut — deployed by asset class vs cash */}
        {totalValue > 0 && (() => {
          const byClass: Record<string, number> = {};
          for (const pos of openPosData?.positions ?? []) {
            const cls = pos.asset_class ?? "other";
            byClass[cls] = (byClass[cls] ?? 0) + Math.round((pos.current_value_usd ?? 0) * 100);
          }
          const deployedCents = Object.values(byClass).reduce((s, v) => s + v, 0);
          const cashCents = Math.max(0, totalValue - deployedCents);
          const slices = [
            ...Object.entries(byClass).filter(([, v]) => v > 0).map(([key, value_cents]) => ({ key, value_cents })),
            ...(cashCents > 0 ? [{ key: "cash", value_cents: cashCents }] : []),
          ];
          if (slices.length === 0) return null;
          return (
            <div className="bg-t-bg1 border border-t-dim rounded-2xl p-5 mb-8">
              <p className="text-xs font-semibold text-t-muted uppercase tracking-wider mb-4">Capital Allocation</p>
              <AllocationDonut totalCents={totalValue} slices={slices} size={160} />
            </div>
          );
        })()}

        {/* Stat cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
          <StatCard
            label="Today P&L"
            value={`${isUp ? "+" : ""}${fmtUsd(todayPnl)}`}
            sub={`${todayPct >= 0 ? "+" : ""}${todayPct.toFixed(2)}%`}
            positive={isUp}
          />
          <StatCard
            label="30d Return"
            value={`${ret30 >= 0 ? "+" : ""}${ret30.toFixed(2)}%`}
            positive={ret30 >= 0}
          />
          <StatCard
            label="Open Positions"
            value={String(openPos)}
            sub="across all bots"
          />
          <StatCard
            label="All-Time Return"
            value={`${retAll >= 0 ? "+" : ""}${retAll.toFixed(2)}%`}
            positive={retAll >= 0}
          />
        </div>

        {/* Per-portfolio breakdown */}
        {portfolios.map((port: any) => (
          <div key={port.id} className="mb-6 bg-t-bg1 border border-t-dim rounded-2xl overflow-hidden card-hover">
            <div className="flex items-center justify-between px-5 py-4 border-b border-t-dim">
              <div className="flex items-center gap-3">
                <span className="text-xl">{port.emoji || "📊"}</span>
                <div>
                  <p className="text-sm font-semibold text-t-hi">{port.name}</p>
                  <span className={cn("text-xs px-2 py-0.5 rounded-full border", ASSET_COLORS[port.asset_class] ?? "bg-t-bg2 text-t-mid2")}>
                    {ASSET_LABELS[port.asset_class] ?? port.asset_class}
                  </span>
                </div>
              </div>
              <div className="text-right">
                <p className="text-sm font-bold font-mono-t tabular-nums text-t-hi">
                  {fmtUsd(port.portfolio_value_cents ?? 0)}
                </p>
                <p className={cn("text-xs font-mono-t tabular-nums", (port.return_30d_pct ?? 0) >= 0 ? "text-t-green" : "text-t-red")}>
                  {(port.return_30d_pct ?? 0) >= 0 ? "+" : ""}{(port.return_30d_pct ?? 0).toFixed(2)}% 30d
                </p>
              </div>
            </div>

            <div className="px-5 py-2">
              {(port.bots ?? []).length === 0 ? (
                <p className="py-4 text-sm text-t-muted text-center">No bots configured</p>
              ) : (
                (port.bots ?? []).map((bot: any, i: number) => {
                  const b = bot?.profile ? { ...bot.profile, ...bot.stats, ...bot.allocation } : bot;
                  return <BotRow key={b.id ?? i} bot={b} />;
                })
              )}
            </div>
          </div>
        ))}

        {portfolios.length === 0 && !loading && (
          <div className="bg-t-bg1 border border-t-dim rounded-2xl p-10 text-center">
            <Layers className="mx-auto mb-3 text-t-dim" size={32} />
            <p className="text-t-mid2 text-sm">No portfolios set up yet.</p>
            <p className="text-t-muted text-xs mt-1">Go to Strategy Lab → Bots to configure your allocation.</p>
          </div>
        )}

        {/* Leaderboard */}
        {(agg?.leaderboard ?? []).length > 0 && (
          <div className="mt-6 bg-t-bg1 border border-t-dim rounded-2xl overflow-hidden">
            <div className="flex items-center gap-2 px-5 py-4 border-b border-t-dim">
              <Activity size={16} className="text-t-muted" />
              <p className="text-sm font-semibold text-t-hi">Bot Leaderboard · 30d</p>
            </div>
            <div className="px-5 py-2">
              {(agg?.leaderboard ?? []).slice(0, 8).map((e: any, i: number) => (
                <div key={e.profile} className="flex items-center justify-between py-2.5 border-b border-t-dim/50 last:border-0">
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-t-muted w-4 text-right">{i + 1}</span>
                    <span className="text-sm text-t-hi">{e.name ?? e.profile}</span>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className={cn("text-sm font-mono-t tabular-nums font-medium", (e.return_30d_pct ?? 0) >= 0 ? "text-t-green" : "text-t-red")}>
                      {(e.return_30d_pct ?? 0) >= 0 ? "+" : ""}{(e.return_30d_pct ?? 0).toFixed(2)}%
                    </span>
                    <span className="text-xs text-t-muted font-mono-t tabular-nums w-20 text-right">
                      {fmtUsd(e.portfolio_value_cents ?? 0)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

      </div>
    </div>
  );
}

import { TrendingUp, TrendingDown, Layers, Activity } from "lucide-react";
import { usePortfolioSnapshot } from "@/hooks/usePortfolioSnapshot";
import { botStatusBadge, BADGE_CLASSES } from "@/lib/botStatus";
import { cn, formatCurrency, formatPercent } from "@/lib/utils";
import AllocationDonut from "@/components/ui/AllocationDonut";
import type { BotSnap, SleeveSnap } from "@/api/portfolioSnapshot";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtUsd(cents: number) {
  return formatCurrency(cents / 100);
}

function fmtPct(pct: number) {
  return formatPercent(pct / 100);
}

const SLEEVE_META: Record<string, { label: string; emoji: string; colorClass: string }> = {
  stocks:  { label: "Equities",       emoji: "📈", colorClass: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
  crypto:  { label: "Digital Assets", emoji: "🪙", colorClass: "bg-t-green/10 text-t-green border-t-mid" },
  options: { label: "Derivatives",    emoji: "⚡", colorClass: "bg-purple-500/10 text-purple-400 border-purple-500/20" },
  quant:   { label: "Quant",          emoji: "∑",  colorClass: "bg-violet-500/10 text-violet-400 border-violet-500/20" },
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

function BotRow({ bot }: { bot: BotSnap }) {
  const badge = botStatusBadge(bot);
  const retPos = bot.return_30d_pct >= 0;
  const pnlPos = bot.today_pnl_cents >= 0;

  return (
    <div className="flex items-center justify-between py-3 border-b border-t-dim/50 last:border-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-t-hi truncate">{bot.display_name}</p>
          <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded-full border", BADGE_CLASSES[badge.variant])}>
            {badge.text}
          </span>
        </div>
        <p className="text-xs text-t-muted">
          {bot.open_positions} open
        </p>
      </div>
      <div className="text-right ml-4">
        <p className="text-sm font-semibold font-mono-t tabular-nums text-t-hi">{fmtUsd(bot.current_value_cents)}</p>
        <p className={cn("text-xs font-mono-t tabular-nums", retPos ? "text-t-green" : "text-t-red")}>
          {retPos ? "+" : ""}{bot.return_30d_pct.toFixed(2)}% 30d
        </p>
      </div>
      <div className="text-right ml-6 w-20">
        <p className={cn("text-sm font-medium font-mono-t tabular-nums", pnlPos ? "text-t-green" : "text-t-red")}>
          {pnlPos ? "+" : ""}{fmtUsd(bot.today_pnl_cents)}
        </p>
        <p className="text-xs text-t-muted">today</p>
      </div>
    </div>
  );
}

function SleeveCard({ sleeveKey, sleeve, bots }: { sleeveKey: string; sleeve: SleeveSnap; bots: BotSnap[] }) {
  const meta = SLEEVE_META[sleeveKey] ?? { label: sleeveKey, emoji: "📊", colorClass: "bg-t-bg2 text-t-mid2" };
  const ret30 = sleeve.return_30d_pct;
  const todayPnl = sleeve.today_pnl_cents;

  return (
    <div className="mb-6 bg-t-bg1 border border-t-dim rounded-2xl overflow-hidden card-hover">
      <div className="flex items-center justify-between px-5 py-4 border-b border-t-dim">
        <div className="flex items-center gap-3">
          <span className="text-xl">{meta.emoji}</span>
          <div>
            <p className="text-sm font-semibold text-t-hi">{meta.label}</p>
            <span className={cn("text-xs px-2 py-0.5 rounded-full border", meta.colorClass)}>
              {sleeve.active_bots}/{sleeve.total_bots} active
            </span>
          </div>
        </div>
        <div className="text-right">
          <p className="text-sm font-bold font-mono-t tabular-nums text-t-hi">
            {fmtUsd(sleeve.current_value_cents + (sleeve.reserved_capital_cents ?? 0))}
          </p>
          <p className={cn("text-xs font-mono-t tabular-nums", ret30 >= 0 ? "text-t-green" : "text-t-red")}>
            {ret30 >= 0 ? "+" : ""}{ret30.toFixed(2)}% 30d
          </p>
          <p className={cn("text-xs font-mono-t tabular-nums", todayPnl >= 0 ? "text-t-green" : "text-t-red")}>
            {todayPnl >= 0 ? "+" : ""}{fmtUsd(todayPnl)} today
          </p>
        </div>
      </div>
      <div className="px-5 py-2">
        {bots.length === 0 ? (
          <p className="py-4 text-sm text-t-muted text-center">
            {sleeve.reserved_capital_cents > 0
              ? `0 dedicated bots · ${fmtUsd(sleeve.reserved_capital_cents)} reserved for future ${sleeveKey} bots`
              : "No bots configured"}
          </p>
        ) : (
          bots.map((bot) => <BotRow key={bot.id} bot={bot} />)
        )}
      </div>
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

const SLEEVE_ORDER = ["stocks", "crypto", "options", "quant"] as const;

export default function Portfolio() {
  const { snap, isLoading } = usePortfolioSnapshot();

  const totalValue = snap.total_value_cents;
  const todayPnl = snap.total_pnl_today_cents;
  const ret30 = snap.return_30d_pct;
  const retAll = snap.return_alltime_pct;
  const openPos = snap.total_open_positions;
  const isUp = todayPnl >= 0;

  // Donut slices use current_value_cents only — reserved_capital_cents is already
  // part of the sleeve's portfolio value (the $200k options reservation lives
  // inside the options StrategyPortfolio as starting capital). Adding it again
  // would double-count and push the total above 100%.
  const slices = SLEEVE_ORDER
    .filter((k) => snap.by_sleeve[k].current_value_cents > 0)
    .map((k) => ({
      key: k,
      value_cents: snap.by_sleeve[k].current_value_cents,
    }));

  const deployedCents = SLEEVE_ORDER.reduce((acc, k) => acc + snap.by_sleeve[k].current_value_cents, 0);
  const cashCents = Math.max(0, totalValue - deployedCents);
  const allSlices = cashCents > 0 ? [...slices, { key: "cash", value_cents: cashCents }] : slices;

  return (
    <div className="min-h-screen bg-t-bg0 text-t-hi animate-page-in">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-10">

        {/* Header */}
        <div className="mb-8">
          <p className="text-xs text-t-muted uppercase tracking-widest mb-1">BMG Capital · Portfolio</p>
          <div className="flex items-end gap-4 flex-wrap">
            <div>
              <p className="text-5xl font-bold tracking-tight font-mono-t tabular-nums">
                {isLoading ? <span className="text-t-dim">$—</span> : fmtUsd(totalValue)}
              </p>
              <div className="flex items-center gap-3 mt-2 flex-wrap">
                <span className={cn("flex items-center gap-1 text-lg font-semibold font-mono-t tabular-nums", isUp ? "text-t-green" : "text-t-red")}>
                  {isUp ? <TrendingUp size={18} /> : <TrendingDown size={18} />}
                  {isUp ? "+" : ""}{fmtUsd(todayPnl)}
                  <span className="text-sm font-normal font-mono-t tabular-nums">today</span>
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

        {/* Allocation donut */}
        {totalValue > 0 && allSlices.length > 0 && (
          <div className="bg-t-bg1 border border-t-dim rounded-2xl p-5 mb-8">
            <p className="text-xs font-semibold text-t-muted uppercase tracking-wider mb-4">Capital Allocation</p>
            <AllocationDonut totalCents={totalValue} slices={allSlices} size={160} />
          </div>
        )}

        {/* Stat cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
          <StatCard
            label="Today P&L"
            value={`${isUp ? "+" : ""}${fmtUsd(todayPnl)}`}
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
            value={isLoading ? "—" : `${retAll >= 0 ? "+" : ""}${retAll.toFixed(2)}%`}
            positive={isLoading ? undefined : retAll >= 0}
          />
        </div>

        {/* Per-sleeve breakdown */}
        {SLEEVE_ORDER.map((key) => {
          const sleeve = snap.by_sleeve[key];
          if (!sleeve || (sleeve.total_bots === 0 && (sleeve.reserved_capital_cents ?? 0) === 0)) return null;
          const sleeveBots = snap.bots.filter((b) => b.category === key);
          return (
            <SleeveCard key={key} sleeveKey={key} sleeve={sleeve} bots={sleeveBots} />
          );
        })}

        {snap.bots.length === 0 && !isLoading && (
          <div className="bg-t-bg1 border border-t-dim rounded-2xl p-10 text-center">
            <Layers className="mx-auto mb-3 text-t-dim" size={32} />
            <p className="text-t-mid2 text-sm">No portfolios set up yet.</p>
            <p className="text-t-muted text-xs mt-1">Go to Strategy Lab → Bots to configure your allocation.</p>
          </div>
        )}

        {/* Leaderboard */}
        {snap.bots.length > 0 && (
          <div className="mt-6 bg-t-bg1 border border-t-dim rounded-2xl overflow-hidden">
            <div className="flex items-center gap-2 px-5 py-4 border-b border-t-dim">
              <Activity size={16} className="text-t-muted" />
              <p className="text-sm font-semibold text-t-hi">Bot Leaderboard · 30d</p>
            </div>
            <div className="px-5 py-2">
              {[...snap.bots]
                .sort((a, b) => b.return_30d_pct - a.return_30d_pct)
                .slice(0, 8)
                .map((bot, i) => (
                  <div key={bot.id} className="flex items-center justify-between py-2.5 border-b border-t-dim/50 last:border-0">
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-t-muted w-4 text-right">{i + 1}</span>
                      <span className="text-sm text-t-hi">{bot.display_name}</span>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className={cn("text-sm font-mono-t tabular-nums font-medium", bot.return_30d_pct >= 0 ? "text-t-green" : "text-t-red")}>
                        {bot.return_30d_pct >= 0 ? "+" : ""}{bot.return_30d_pct.toFixed(2)}%
                      </span>
                      <span className="text-xs text-t-muted font-mono-t tabular-nums w-20 text-right">
                        {fmtUsd(bot.current_value_cents)}
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

/**
 * Dashboard v2 — BMG Capital
 *
 * Fixed-layout page. No react-grid-layout. No drag/drop.
 * Rows (top to bottom):
 *   1. Health Bar (sticky)
 *   2. Hero Stats (total value, today P&L, 30d P&L, Sharpe + mini sparkline)
 *   3. Market Regime Strip
 *   4. Portfolio Cards (3-col grid)
 *   5. Analyst Highlights
 *   6. Catalyst Chips
 *   7. Activity Feed (recent cross-bot signals)
 *   8. Top Open Positions
 *   9. Watchlist Movers
 *  10. Quick Links
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, Link } from "react-router-dom";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { cn } from "@/lib/utils";
import SymbolChartDrawer from "@/components/ui/SymbolChartDrawer";

import {
  getDashboardHealth,
  getRecentSignals,
  getWatchlistMovers,
  getStrategyLabPortfolio,
  getRegime,
  getPortfolios,
  getCatalysts,
  getCrossBotPositions,
  pauseAllBots,
  type DashboardHealth,
  type RecentSignal,
  type WatchlistMover,
  type PortfolioData,
  type RegimeData,
  type StrategyPortfolio,
  type CatalystEvent,
  type CrossBotPosition,
} from "@/api/bots";
import { getAnalystSummary, type AnalystSummary, type AnalystSummaryItem } from "@/api/analyst";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtUsd(cents: number): string {
  const usd = cents / 100;
  return usd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(val: number, plus = true): string {
  const sign = val >= 0 ? (plus ? "+" : "") : "";
  return `${sign}${val.toFixed(2)}%`;
}

function timeAgo(ts: string): string {
  try {
    const diff = Date.now() - new Date(ts).getTime();
    const m = Math.floor(diff / 60_000);
    const h = Math.floor(diff / 3_600_000);
    const d = Math.floor(diff / 86_400_000);
    if (d >= 1) return `${d}d`;
    if (h >= 1) return `${h}h`;
    if (m >= 1) return `${m}m`;
    return "now";
  } catch {
    return "";
  }
}

function daysUntil(ts: string): number {
  try {
    return Math.ceil((new Date(ts).getTime() - Date.now()) / 86_400_000);
  } catch {
    return 0;
  }
}

// ─── Row 1 — Health Bar ───────────────────────────────────────────────────────

function HealthBar({ health }: { health: DashboardHealth | undefined }) {
  const qc = useQueryClient();

  const pauseMut = useMutation({
    mutationFn: pauseAllBots,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dashboard-health"] });
      toast.success("All bots paused");
    },
    onError: () => toast.error("Failed to pause bots"),
  });

  const dotColor =
    health?.status === "ok"
      ? "bg-lime-400"
      : health?.status === "warn"
      ? "bg-amber-400"
      : "bg-red-500";

  const textColor =
    health?.status === "ok"
      ? "text-lime-400"
      : health?.status === "warn"
      ? "text-amber-400"
      : "text-red-400";

  return (
    <div className="sticky top-0 z-30 bg-zinc-900 border-b border-zinc-800 px-4 py-2.5 flex items-center justify-between gap-4">
      {/* Left: status */}
      <div className="flex items-center gap-3 min-w-0">
        <span className={cn("w-2 h-2 rounded-full flex-shrink-0", dotColor)} />
        <span className={cn("text-xs font-semibold truncate", textColor)}>
          {health?.message ?? "Loading…"}
        </span>
        {health && (
          <span className="text-xs text-zinc-500 whitespace-nowrap hidden sm:inline">
            {health.bots_active} bot{health.bots_active !== 1 ? "s" : ""} active
            {health.bots_paused > 0 && ` · ${health.bots_paused} paused`}
          </span>
        )}
      </div>

      {/* Right: actions */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <button
          onClick={() => pauseMut.mutate()}
          disabled={pauseMut.isPending}
          className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-300 hover:border-red-700 hover:text-red-400 transition-colors disabled:opacity-40"
        >
          {pauseMut.isPending ? "Pausing…" : "Pause All"}
        </button>
        <Link
          to="/morning-brief"
          className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-300 hover:border-lime-600 hover:text-lime-400 transition-colors"
        >
          Brief me 60s
        </Link>
      </div>
    </div>
  );
}

// ─── Row 2 — Hero Stats ───────────────────────────────────────────────────────

function HeroStats({ portfolio }: { portfolio: PortfolioData | undefined }) {
  const totalVal = (portfolio?.total_value_cents ?? 0) / 100;
  const todayPnl = (portfolio?.today_pnl_cents ?? 0) / 100;
  const ret30 = portfolio?.return_30d_pct ?? 0;
  const sharpe = portfolio?.sharpe_30d ?? 0;
  const todayPos = todayPnl >= 0;
  const ret30Pos = ret30 >= 0;

  // Mini sparkline — last 30 points of equity curve
  const sparkData = (portfolio?.equity_curve ?? []).slice(-30).map((pt) => ({
    v: pt.value_cents / 100,
  }));

  return (
    <div className="px-4 pt-6 pb-4">
      <div className="flex flex-col sm:flex-row sm:items-end gap-4">
        {/* Big number */}
        <div className="flex-1">
          <p className="text-[10px] text-zinc-600 uppercase tracking-widest mb-1">
            Strategy Lab Portfolio
          </p>
          <p className="font-mono text-5xl font-bold text-white leading-none">
            ${fmtUsd(portfolio?.total_value_cents ?? 0)}
          </p>
          <div className="flex flex-wrap gap-x-6 gap-y-1 mt-3">
            <div>
              <span className="text-[10px] text-zinc-600 mr-1.5">Today</span>
              <span
                className={cn(
                  "text-sm font-semibold tabular-nums",
                  todayPos ? "text-lime-400" : "text-red-400"
                )}
              >
                {todayPos ? "+" : "-"}${Math.abs(todayPnl).toLocaleString("en-US", { minimumFractionDigits: 2 })}
              </span>
            </div>
            <div>
              <span className="text-[10px] text-zinc-600 mr-1.5">30d</span>
              <span
                className={cn(
                  "text-sm font-semibold",
                  ret30Pos ? "text-lime-400" : "text-red-400"
                )}
              >
                {fmtPct(ret30)}
              </span>
            </div>
            <div>
              <span className="text-[10px] text-zinc-600 mr-1.5">Sharpe</span>
              <span className="text-sm font-semibold text-white">{sharpe.toFixed(2)}</span>
            </div>
          </div>
        </div>

        {/* Sparkline */}
        {sparkData.length > 1 && (
          <div className="w-full sm:w-48 h-14 opacity-30">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={sparkData} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
                <defs>
                  <linearGradient id="heroGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#84cc16" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#84cc16" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" hide />
                <YAxis domain={["auto", "auto"]} hide />
                <Area
                  type="monotone"
                  dataKey="v"
                  stroke="#84cc16"
                  strokeWidth={2}
                  fill="url(#heroGrad)"
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Row 3 — Regime Strip ─────────────────────────────────────────────────────

function RegimeStrip({ regime }: { regime: RegimeData | undefined }) {
  if (!regime) {
    return (
      <div className="mx-4 mb-4 bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-2.5 flex gap-4 animate-pulse">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-4 w-20 bg-zinc-800 rounded" />
        ))}
      </div>
    );
  }

  const vix = (regime.vix_regime ?? "mid").toUpperCase();
  const trend = (regime.trend_regime ?? "chop").toUpperCase();
  const btcDom = typeof regime.btc_dominance === "number" ? `${regime.btc_dominance.toFixed(0)}%` : "—";
  const vixVal = typeof regime.vix_value === "number" ? `VIX ${regime.vix_value.toFixed(1)}` : null;

  const vixCls =
    vix === "LOW" ? "text-lime-400" : vix === "PANIC" ? "text-red-400" : vix === "HIGH" ? "text-orange-400" : "text-amber-400";
  const trendCls =
    trend === "BULL" ? "text-lime-400" : trend === "BEAR" ? "text-red-400" : "text-zinc-400";

  return (
    <div className="mx-4 mb-4 bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-2.5 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs">
      <span className="text-zinc-500 font-semibold uppercase tracking-wide">Market</span>
      <span>
        <span className="text-zinc-500 mr-1">VIX</span>
        <span className={cn("font-semibold", vixCls)}>{vix}{vixVal ? ` (${vixVal})` : ""}</span>
      </span>
      <span>
        <span className="text-zinc-500 mr-1">Trend</span>
        <span className={cn("font-semibold", trendCls)}>{trend}</span>
      </span>
      <span>
        <span className="text-zinc-500 mr-1">BTC Dom</span>
        <span className="text-zinc-300 font-semibold">{btcDom}</span>
      </span>
      {typeof regime.btc_funding_rate === "number" && (
        <span>
          <span className="text-zinc-500 mr-1">Funding</span>
          <span className={cn("font-semibold", regime.btc_funding_rate >= 0 ? "text-lime-400" : "text-red-400")}>
            {regime.btc_funding_rate >= 0 ? "+" : ""}{(regime.btc_funding_rate * 100).toFixed(3)}%
          </span>
        </span>
      )}
    </div>
  );
}

// ─── Row 4 — Portfolio Cards ──────────────────────────────────────────────────

function PortfolioCards({ portfolios }: { portfolios: StrategyPortfolio[] }) {
  const navigate = useNavigate();

  if (portfolios.length === 0) {
    return (
      <div className="mx-4 mb-4 grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-28 rounded-2xl bg-zinc-900 border border-zinc-800 animate-pulse" />
        ))}
      </div>
    );
  }

  const borderColor = (ac: string) => {
    if (ac === "stocks") return "border-lime-500/40 hover:border-lime-500/70";
    if (ac === "crypto") return "border-amber-500/40 hover:border-amber-500/70";
    return "border-purple-500/40 hover:border-purple-500/70";
  };

  const pnlColor = (ac: string) => {
    if (ac === "stocks") return "text-lime-400";
    if (ac === "crypto") return "text-amber-400";
    return "text-purple-400";
  };

  return (
    <div className="mx-4 mb-4 grid grid-cols-1 sm:grid-cols-3 gap-4">
      {portfolios.map((port) => {
        const curUsd = port.current_value_cents / 100;
        const pnlUsd = port.pnl_cents / 100;
        const isPos = port.pnl_pct >= 0;

        return (
          <button
            key={port.id}
            onClick={() => navigate(`/strategy/portfolio/${port.asset_class}`)}
            className={cn(
              "rounded-2xl border-2 bg-zinc-950 p-4 text-left transition-all hover:bg-zinc-900/60 group",
              borderColor(port.asset_class)
            )}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xl">{port.emoji}</span>
              <span className="font-bold text-white text-sm">{port.name}</span>
              <span className="ml-auto text-zinc-600 group-hover:text-zinc-400 text-xs">→</span>
            </div>
            <p className="text-lg font-bold text-white leading-tight tabular-nums">
              ${curUsd.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            </p>
            <p className={cn("text-xs font-medium mt-0.5", isPos ? "text-lime-400" : "text-red-400")}>
              {isPos ? "+" : ""}
              {pnlUsd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              {" "}({fmtPct(port.pnl_pct)})
            </p>
            <p className="text-[11px] text-zinc-600 mt-1">
              {port.bots.length} bot{port.bots.length !== 1 ? "s" : ""}
              {" · "}
              <span className={cn("font-medium", pnlColor(port.asset_class))}>
                Open →
              </span>
            </p>
          </button>
        );
      })}
    </div>
  );
}

// ─── Row 5 — Analyst Highlights ───────────────────────────────────────────────

function ConvictionStars({ score }: { score: number | null }) {
  if (score == null) return <span className="text-zinc-600 text-xs">—</span>;
  const filled = Math.round(score);
  return (
    <span className={score >= 4 ? "text-lime-400" : score >= 3 ? "text-yellow-400" : "text-zinc-500"}>
      {"★".repeat(filled)}{"☆".repeat(5 - filled)}
    </span>
  );
}

function AnalystHighlights({ summary }: { summary: AnalystSummary | undefined }) {
  const picks = summary?.top_picks ?? [];
  const numConcerns = summary?.num_flagged ?? 0;

  if (!summary) {
    return (
      <div className="mx-4 mb-4 bg-zinc-900 border border-zinc-800 rounded-2xl p-5 animate-pulse">
        <div className="h-4 w-48 bg-zinc-800 rounded mb-3" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[0, 1, 2, 3].map((i) => <div key={i} className="h-16 bg-zinc-800 rounded-xl" />)}
        </div>
      </div>
    );
  }

  if (picks.length === 0 && numConcerns === 0) {
    return (
      <div className="mx-4 mb-4 bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-zinc-300">AI Analyst Highlights</h3>
          <Link to="/strategy/analyst" className="text-xs text-lime-400 hover:text-lime-300">
            Full report →
          </Link>
        </div>
        <p className="text-zinc-600 text-xs py-2 text-center">No analyst data yet. Run a refresh from Strategy Lab.</p>
      </div>
    );
  }

  function PickCard({ item, flag }: { item: AnalystSummaryItem; flag?: boolean }) {
    return (
      <Link
        to="/strategy/analyst"
        className="block bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-3 hover:border-zinc-600 transition-colors"
      >
        <div className="flex items-center justify-between mb-1">
          <span className="font-semibold text-white text-sm">{item.symbol}</span>
          {flag
            ? <span className="text-xs text-red-400 font-semibold">⚑ Flag</span>
            : <ConvictionStars score={item.conviction_score} />}
        </div>
        <p className="text-[11px] text-zinc-500 leading-snug line-clamp-2">{item.thesis_preview}</p>
        <p className="text-[10px] text-zinc-600 mt-1">{item.bot_name.replace(/_/g, " ")} · {item.suggested_hold}</p>
      </Link>
    );
  }

  return (
    <div className="mx-4 mb-4 bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-300">AI Analyst Highlights</h3>
        <Link to="/strategy/analyst" className="text-xs text-lime-400 hover:text-lime-300">
          Full report →
        </Link>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {picks.slice(0, 4).map((p) => <PickCard key={p.id} item={p} />)}
      </div>
      {numConcerns > 0 && (
        <p className="text-xs text-amber-400 mt-3 font-medium">
          ⚑ {numConcerns} concern{numConcerns !== 1 ? "s" : ""} flagged
        </p>
      )}
    </div>
  );
}

// ─── Row 6 — Catalyst Chips ───────────────────────────────────────────────────

function CatalystChips({ catalysts }: { catalysts: CatalystEvent[] }) {
  if (catalysts.length === 0) return null;

  return (
    <div className="mx-4 mb-4">
      <p className="text-[10px] text-zinc-600 uppercase tracking-widest mb-2 font-semibold">
        Today's Catalysts
      </p>
      <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-none">
        {catalysts.slice(0, 12).map((ev) => {
          const d = daysUntil(ev.event_ts);
          const label =
            d <= 0 ? "today" : d === 1 ? "1d" : `${d}d`;
          return (
            <span
              key={ev.id}
              className="flex-shrink-0 inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border border-zinc-700 bg-zinc-800 text-zinc-300"
            >
              <span className="text-lime-400">{ev.symbol ?? "—"}</span>
              <span className="text-zinc-500">{ev.event_type?.replace(/_/g, " ")}</span>
              <span className="text-zinc-600">{label}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ─── Row 7 — Activity Feed ────────────────────────────────────────────────────

type FeedTab = "all" | "trades" | "signals";

function ActivityFeed({
  signals,
  onClickSymbol,
}: {
  signals: RecentSignal[];
  onClickSymbol: (sym: string) => void;
}) {
  const [tab, setTab] = useState<FeedTab>("all");

  const filtered =
    tab === "all"
      ? signals
      : tab === "trades"
      ? signals.filter((s) => s.side === "buy" || s.side === "sell")
      : signals.filter((s) => s.side !== "buy" && s.side !== "sell");

  function sideEmoji(bot: string, side: string) {
    if (bot.includes("crypto")) return "🪙";
    if (side === "buy") return "📈";
    if (side === "sell") return "📉";
    return "⚡";
  }

  function sideLabel(side: string) {
    if (side === "buy") return "BUY";
    if (side === "sell") return "EXIT";
    return "HOLD";
  }

  function sideCls(side: string) {
    if (side === "buy") return "text-lime-400";
    if (side === "sell") return "text-red-400";
    return "text-zinc-400";
  }

  const TABS: { key: FeedTab; label: string }[] = [
    { key: "all", label: "All" },
    { key: "trades", label: "Trades" },
    { key: "signals", label: "Signals" },
  ];

  return (
    <div className="mx-4 mb-4 bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-300">Activity Feed</h3>
        <div className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={cn(
                "text-xs px-2.5 py-1 rounded-lg font-medium transition-colors",
                tab === t.key
                  ? "bg-lime-500/15 text-lime-400 border border-lime-500/30"
                  : "text-zinc-500 hover:text-zinc-300"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="text-zinc-600 text-xs text-center py-6">
          No signals yet. Bots scan at market open (9:30 AM ET).
        </p>
      ) : (
        <div className="space-y-1">
          {filtered.map((s, i) => (
            <div
              key={`${s.ts}-${s.symbol}-${i}`}
              onClick={() => onClickSymbol(s.symbol)}
              className="flex items-center gap-3 px-3 py-2 rounded-xl bg-zinc-800/50 border border-zinc-800/80 cursor-pointer hover:bg-zinc-700/50 hover:border-zinc-600 transition-colors"
            >
              <span className="text-sm w-6 text-center flex-shrink-0">
                {sideEmoji(s.bot_name, s.side)}
              </span>
              <span className="text-[10px] text-zinc-600 w-8 flex-shrink-0 tabular-nums">
                {timeAgo(s.ts)}
              </span>
              <span className="text-xs text-zinc-500 flex-1 truncate min-w-0">
                {s.display_name}
              </span>
              <span className={cn("text-xs font-bold w-10 text-right flex-shrink-0", sideCls(s.side))}>
                {sideLabel(s.side)}
              </span>
              <span className="text-xs font-semibold text-white w-14 text-right flex-shrink-0">
                {s.symbol}
              </span>
              <span className="text-[10px] text-zinc-500 w-12 text-right flex-shrink-0">
                {Math.round(s.confidence * 100)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Row 8 — Top Open Positions ───────────────────────────────────────────────

function TopPositions({
  positions,
  onClickSymbol,
}: {
  positions: CrossBotPosition[];
  onClickSymbol: (sym: string) => void;
}) {
  const top5 = [...positions].sort((a, b) => b.pnl - a.pnl).slice(0, 5);

  return (
    <div className="mx-4 mb-4 bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-300">Top Open Positions</h3>
        <Link to="/strategy" className="text-xs text-zinc-500 hover:text-zinc-300">
          All →
        </Link>
      </div>

      {top5.length === 0 ? (
        <p className="text-zinc-600 text-xs text-center py-4">
          No open positions. Bots enter at market open on weekdays.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-zinc-600 border-b border-zinc-800">
                <th className="text-left pb-2 font-medium">Symbol</th>
                <th className="text-left pb-2 font-medium hidden sm:table-cell">Portfolio</th>
                <th className="text-right pb-2 font-medium">Qty</th>
                <th className="text-right pb-2 font-medium">P&L</th>
                <th className="text-right pb-2 font-medium hidden sm:table-cell">Exposure</th>
              </tr>
            </thead>
            <tbody>
              {top5.map((pos) => {
                const pnlPos = pos.pnl >= 0;
                const botEmoji = pos.bots_holding.some((b) => b.includes("crypto"))
                  ? "🪙"
                  : pos.bots_holding.some((b) => b.includes("options"))
                  ? "⚡"
                  : "📈";
                return (
                  <tr
                    key={pos.symbol}
                    onClick={() => onClickSymbol(pos.symbol)}
                    className="border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/20 cursor-pointer transition-colors"
                  >
                    <td className="py-2.5 font-semibold text-white">{pos.symbol}</td>
                    <td className="py-2.5 text-zinc-400 hidden sm:table-cell">
                      {botEmoji} {pos.bots_holding.map((b) => b.replace(/_/g, " ")).join(", ")}
                    </td>
                    <td className="py-2.5 text-zinc-300 text-right tabular-nums">{pos.total_qty.toFixed(2)}</td>
                    <td className={cn("py-2.5 font-semibold text-right tabular-nums", pnlPos ? "text-lime-400" : "text-red-400")}>
                      {pnlPos ? "+" : "−"}${Math.abs(pos.pnl).toFixed(2)}
                    </td>
                    <td className="py-2.5 text-zinc-500 text-right hidden sm:table-cell">
                      {pos.exposure_pct.toFixed(1)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Row 9 — Watchlist Movers ─────────────────────────────────────────────────

function WatchlistMovers({ movers }: { movers: WatchlistMover[] }) {
  if (movers.length === 0) return null;

  return (
    <div className="mx-4 mb-4 bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
      <h3 className="text-sm font-semibold text-zinc-300 mb-3">Watchlist Movers</h3>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {movers.map((m) => {
          const pos = m.change_pct >= 0;
          return (
            <div
              key={m.symbol}
              className="bg-zinc-800/50 border border-zinc-700/50 rounded-xl px-3 py-3"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-bold text-white text-sm">{m.symbol}</span>
                {m.change_pct !== 0 && (
                  <span className={cn("text-xs font-semibold", pos ? "text-lime-400" : "text-red-400")}>
                    {pos ? "+" : ""}{m.change_pct.toFixed(2)}%
                  </span>
                )}
              </div>
              <p className="text-[10px] text-zinc-500 truncate">{m.portfolio || "Watchlist"}</p>
              <p className="text-[10px] text-zinc-600">score {m.score.toFixed(2)}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Row 10 — Quick Links ─────────────────────────────────────────────────────

function QuickLinks() {
  const navigate = useNavigate();

  const links = [
    { label: "Strategy Lab", icon: "⊞", to: "/strategy" },
    { label: "Screener", icon: "🔍", to: "/screener" },
    { label: "Portfolio", icon: "📊", to: "/net-portfolio" },
    { label: "Settings", icon: "⚙", to: "/settings" },
  ];

  return (
    <div className="mx-4 mb-6">
      <p className="text-[10px] text-zinc-600 uppercase tracking-widest mb-2 font-semibold">
        Quick Links
      </p>
      <div className="flex flex-wrap gap-2">
        {links.map((l) => (
          <button
            key={l.to}
            onClick={() => navigate(l.to)}
            className="flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-zinc-700 bg-zinc-800/60 text-zinc-300 hover:border-zinc-500 hover:text-white transition-colors"
          >
            <span>{l.icon}</span>
            {l.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [chartSymbol, setChartSymbol] = useState<string | null>(null);

  // Health — 30s stale
  const { data: health } = useQuery({
    queryKey: ["dashboard-health"],
    queryFn: getDashboardHealth,
    staleTime: 30_000,
    refetchInterval: 30_000,
    retry: 0,
  });

  // Portfolio hero — 60s stale
  const { data: portfolio } = useQuery({
    queryKey: ["strategy-lab-portfolio"],
    queryFn: getStrategyLabPortfolio,
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 0,
  });

  // Regime
  const { data: regime } = useQuery({
    queryKey: ["regime"],
    queryFn: getRegime,
    staleTime: 60_000,
    retry: 0,
  });

  // Portfolios
  const { data: portfolioData } = useQuery({
    queryKey: ["strategy-portfolios"],
    queryFn: getPortfolios,
    staleTime: 60_000,
    retry: 0,
  });
  const portfolios: StrategyPortfolio[] = portfolioData?.portfolios ?? [];

  // Analyst
  const { data: analystSummary } = useQuery({
    queryKey: ["analyst-summary"],
    queryFn: getAnalystSummary,
    staleTime: 300_000,
    retry: 0,
  });

  // Catalysts
  const { data: catalysts = [] } = useQuery({
    queryKey: ["catalysts"],
    queryFn: getCatalysts,
    staleTime: 120_000,
    retry: 0,
  });

  // Recent signals — 15s stale
  const { data: signalsData } = useQuery({
    queryKey: ["recent-signals"],
    queryFn: () => getRecentSignals(20),
    staleTime: 15_000,
    refetchInterval: 15_000,
    retry: 0,
  });
  const signals: RecentSignal[] = signalsData?.signals ?? [];

  // Cross-bot positions
  const { data: positionsRaw = [] } = useQuery({
    queryKey: ["cross-bot-positions"],
    queryFn: getCrossBotPositions,
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 0,
  });
  const positions: CrossBotPosition[] = Array.isArray(positionsRaw) ? positionsRaw : [];

  // Watchlist movers
  const { data: moversData } = useQuery({
    queryKey: ["watchlist-movers"],
    queryFn: () => getWatchlistMovers(4),
    staleTime: 120_000,
    retry: 0,
  });
  const movers: WatchlistMover[] = moversData?.movers ?? [];

  return (
    <>
      {/* Health Bar (sticky) */}
      <HealthBar health={health} />

      {/* Scrollable page content */}
      <div className="max-w-6xl mx-auto pb-20 md:pb-6">
        {/* Row 2: Hero */}
        <HeroStats portfolio={portfolio} />

        {/* Row 3: Regime Strip */}
        <RegimeStrip regime={regime} />

        {/* Row 4: Portfolio Cards */}
        <PortfolioCards portfolios={portfolios} />

        {/* Row 5: Analyst Highlights */}
        <AnalystHighlights summary={analystSummary} />

        {/* Row 6: Catalyst Chips */}
        <CatalystChips catalysts={catalysts} />

        {/* ─── Below fold ─────────────────────────────────────── */}

        {/* Row 7: Activity Feed */}
        <ActivityFeed signals={signals} onClickSymbol={setChartSymbol} />

        {/* Row 8: Top Open Positions */}
        <TopPositions positions={positions} onClickSymbol={setChartSymbol} />

        {/* Row 9: Watchlist Movers */}
        <WatchlistMovers movers={movers} />

        {/* Row 10: Quick Links */}
        <QuickLinks />
      </div>

      {/* Chart drawer */}
      <SymbolChartDrawer symbol={chartSymbol} onClose={() => setChartSymbol(null)} />
    </>
  );
}

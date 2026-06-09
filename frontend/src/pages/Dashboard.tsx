import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import TickerTape from "@/components/ui/TickerTape";
import {
  getStrategyLabPortfolio,
  getPortfolios,
  getRecentSignals,
  getCatalysts,
  getWatchlistMovers,
  pauseAllBots,
  type StrategyPortfolio,
  type RecentSignal,
} from "@/api/bots";
import { getRegime } from "@/api/bots";
import { useIsViewer } from "@/store/authStore";
import { getAnalystHighlights, type AnalystHighlight } from "@/api/analyst";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtUsd(cents: number): string {
  const usd = cents / 100;
  if (Math.abs(usd) >= 1_000_000) return `$${(usd / 1_000_000).toFixed(2)}M`;
  if (Math.abs(usd) >= 1_000) return `$${(usd / 1_000).toFixed(1)}k`;
  return usd.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function fmtPct(val: number): string {
  const sign = val >= 0 ? "+" : "";
  return `${sign}${val.toFixed(2)}%`;
}

function timeAgo(ts: string): string {
  try {
    const diff = Date.now() - new Date(ts).getTime();
    const m = Math.floor(diff / 60_000);
    const h = Math.floor(diff / 3_600_000);
    const d = Math.floor(diff / 86_400_000);
    if (d >= 1) return `${d}d ago`;
    if (h >= 1) return `${h}h ago`;
    if (m >= 1) return `${m}m ago`;
    return "just now";
  } catch { return ""; }
}

const DAILY_TIPS: Record<number, string> = {
  1: "Paper trading builds muscle memory — treat every signal like real money",
  2: "Check regime before placing trades — bots adjust strategy by market condition",
  3: "Diversify across timeframes: swing + day + long-term",
  4: "Review your journal weekly — patterns only appear looking back",
  5: "Options expire Friday — check positions before close",
  6: "Use weekends to backtest and plan next week's setups",
  0: "Use weekends to backtest and plan next week's setups",
};

// ─── Sub-components ──────────────────────────────────────────────────────────

function PortfolioCard({ p }: { p: StrategyPortfolio }) {
  const isUp = p.pnl_cents >= 0;
  return (
    <Link to="/strategy" className="block bg-zinc-900 border border-zinc-800 rounded-2xl p-6 hover:border-zinc-700 transition-colors">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-xl">{p.emoji}</span>
          <span className="text-sm font-medium text-zinc-400 capitalize">{p.name}</span>
        </div>
        <span className={cn("text-xs font-semibold px-2 py-0.5 rounded-full", isUp ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400")}>
          {fmtPct(p.pnl_pct)}
        </span>
      </div>
      <div className="text-2xl font-bold text-white tabular-nums">{fmtUsd(p.current_value_cents)}</div>
      <div className={cn("text-sm mt-1 tabular-nums", isUp ? "text-emerald-400" : "text-red-400")}>
        {isUp ? "+" : ""}{fmtUsd(p.pnl_cents)} all time
      </div>
      <div className="mt-4 pt-4 border-t border-zinc-800 flex justify-between text-xs text-zinc-500">
        <span>{p.bots.length} bot{p.bots.length !== 1 ? "s" : ""}</span>
        <span>{p.bots.filter((b) => b.allocation?.enabled).length} active</span>
      </div>
    </Link>
  );
}

function SignalRow({ s }: { s: RecentSignal }) {
  const dotCls = { buy: "bg-emerald-500", sell: "bg-red-500", hold: "bg-zinc-500" }[s.side] ?? "bg-zinc-500";
  const textCls = { buy: "text-emerald-400", sell: "text-red-400", hold: "text-zinc-400" }[s.side] ?? "text-zinc-400";
  return (
    <div className="flex items-center gap-3 py-3 border-b border-zinc-800 last:border-0">
      <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", dotCls)} />
      <span className="font-semibold text-white text-sm w-16 flex-shrink-0">{s.symbol}</span>
      <span className={cn("text-xs font-medium uppercase w-8 flex-shrink-0", textCls)}>{s.side}</span>
      <span className="text-xs text-zinc-500 flex-1 truncate">{s.reason || s.strategy}</span>
      <span className="text-xs text-zinc-600 flex-shrink-0">{timeAgo(s.ts)}</span>
    </div>
  );
}

const CONVICTION_STYLE: Record<string, string> = {
  HIGH: "bg-emerald-500/10 text-emerald-400",
  MED: "bg-yellow-500/10 text-yellow-400",
  LOW: "bg-zinc-700 text-zinc-400",
};

const PLACEHOLDER_HIGHLIGHTS: AnalystHighlight[] = [
  { symbol: "AAPL", conviction: "HIGH", thesis: "Strong earnings momentum" },
  { symbol: "NVDA", conviction: "HIGH", thesis: "AI infrastructure cycle" },
  { symbol: "BTC", conviction: "MED", thesis: "Regime breakout setup" },
  { symbol: "ETH", conviction: "MED", thesis: "ETF inflows building" },
];

const PLACEHOLDER_CATALYSTS = [
  { id: "fomc", event_type: "FOMC Watch", symbol: null, event_ts: "", description: "🏛" },
  { id: "earn", event_type: "Earnings Season", symbol: null, event_ts: "", description: "📊" },
  { id: "opex", event_type: "Options Expiry", symbol: null, event_ts: "", description: "⚡" },
];

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const qc = useQueryClient();
  const isViewer = useIsViewer();
  const { data: overview } = useQuery({ queryKey: ["strategy-lab-portfolio"], queryFn: getStrategyLabPortfolio, staleTime: 60_000, retry: 0 });
  const { data: portfoliosData } = useQuery({ queryKey: ["portfolios"], queryFn: getPortfolios, staleTime: 60_000, retry: 0 });
  const { data: signalsData } = useQuery({ queryKey: ["recent-signals", 20], queryFn: () => getRecentSignals(20), staleTime: 30_000, retry: 0 });
  const { data: catalystsRaw } = useQuery({ queryKey: ["catalysts"], queryFn: getCatalysts, staleTime: 60_000, retry: 0 });
  const { data: moversData } = useQuery({ queryKey: ["watchlist-movers"], queryFn: () => getWatchlistMovers(4), staleTime: 60_000, retry: 0 });
  const { data: regimeRaw } = useQuery({ queryKey: ["strategy-regime"], queryFn: getRegime, staleTime: 120_000, retry: 0 });
  const { data: highlightsData } = useQuery({ queryKey: ["analyst-highlights"], queryFn: getAnalystHighlights, staleTime: 120_000, retry: 0 });

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["strategy-lab-portfolio"] });
    qc.invalidateQueries({ queryKey: ["portfolios"] });
    qc.invalidateQueries({ queryKey: ["bots-v2"] });
  };
  const pauseMut = useMutation({ mutationFn: pauseAllBots, onSuccess: invalidateAll });

  const portfolios = portfoliosData?.portfolios ?? [];
  const signals = signalsData?.signals ?? [];
  const catalysts = (catalystsRaw && catalystsRaw.length > 0) ? catalystsRaw : PLACEHOLDER_CATALYSTS;
  const movers = moversData?.movers ?? [];
  const highlights: AnalystHighlight[] =
    highlightsData?.highlights && highlightsData.highlights.length > 0
      ? highlightsData.highlights.slice(0, 4)
      : PLACEHOLDER_HIGHLIGHTS;

  const totalValue = overview?.total_value_cents ?? 0;
  const todayPnl = overview?.today_pnl_cents ?? 0;
  const todayPct = overview?.today_pnl_pct ?? 0;
  const return30d = overview?.return_30d_pct ?? 0;
  const isUp = todayPnl >= 0;

  const leaderboard = overview?.leaderboard ?? [];
  const topBot = leaderboard.length > 0
    ? leaderboard.reduce((a, b) => (b.return_30d_pct > a.return_30d_pct ? b : a))
    : null;

  // Open positions from all portfolio bots
  const allPositions: Array<{ symbol: string; side: string; qty: number; avg_cost: number; current: number; pnl: number; botName: string }> = [];
  portfolios.forEach((p) => {
    p.bots.forEach((b) => {
      const raw = b as any;
      const positions: any[] = raw.open_positions ?? raw.positions ?? [];
      positions.forEach((pos: any) => {
        const avgCents = pos.avg_cost_cents ?? 0;
        const currentCents = pos.current_price_cents ?? pos.current_value_cents ?? avgCents;
        const qty = pos.qty ?? 1;
        const pnl = (currentCents - avgCents) * qty;
        allPositions.push({ symbol: pos.symbol ?? "?", side: pos.side ?? "long", qty, avg_cost: avgCents, current: currentCents, pnl, botName: b.profile.name });
      });
    });
  });
  const topPositions = allPositions.sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl)).slice(0, 5);

  const todayDow = new Date().getDay();
  const dailyTip = DAILY_TIPS[todayDow] ?? DAILY_TIPS[1];

  const botsEnabled = portfolios.some((p) => p.bots.some((b) => b.allocation?.enabled));

  return (
    <div className="min-h-screen bg-zinc-950 text-white">

      {/* S&P 500 Live Ticker Tape */}
      <TickerTape />

      {/* Row 1 – Health Bar */}
      <div className="sticky top-0 z-10 bg-zinc-900/80 backdrop-blur border-b border-zinc-800 px-6 py-2 flex items-center justify-between text-xs">
        <div className="flex items-center gap-2">
          <span className={cn("w-1.5 h-1.5 rounded-full", botsEnabled ? "bg-emerald-500" : "bg-yellow-500")} />
          <span className={botsEnabled ? "text-zinc-300" : "text-yellow-400"}>
            {botsEnabled ? "All systems normal" : "Warning: bots may be disabled"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {!isViewer && (
            <button
              onClick={() => pauseMut.mutate()}
              disabled={pauseMut.isPending}
              className="px-3 py-1 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors disabled:opacity-50"
            >
              Pause All
            </button>
          )}
          <button
            onClick={() => window.dispatchEvent(new CustomEvent("copilot:open", { detail: { query: "Brief me on what's happening with my bots today." } }))}
            className="px-3 py-1 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 transition-colors"
          >
            Brief me
          </button>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-10">

        {/* Row 2 – Hero Stats */}
        <div className="mb-8">
          <p className="text-sm text-zinc-500 mb-1">Total Portfolio Value</p>
          <div className="text-5xl font-bold tracking-tight tabular-nums">
            {totalValue ? fmtUsd(totalValue) : <span className="text-zinc-700">$—</span>}
          </div>
          <div className="flex items-center gap-4 mt-3 flex-wrap">
            <span className={cn("text-lg font-semibold tabular-nums", isUp ? "text-emerald-400" : "text-red-400")}>
              {isUp ? "+" : ""}{fmtUsd(todayPnl)}{" "}
              <span className="text-sm font-normal">({fmtPct(todayPct)} today)</span>
            </span>
            <span className="text-zinc-600">·</span>
            <span className={cn("text-sm tabular-nums", return30d >= 0 ? "text-emerald-400/70" : "text-red-400/70")}>
              {fmtPct(return30d)} 30d
            </span>
          </div>
        </div>

        {/* Row 3 – Market Regime */}
        <div className="mb-8 bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
          <h2 className="text-sm font-semibold text-zinc-300 mb-3">Market Regime</h2>
          {regimeRaw ? (
            <>
              <div className="flex items-center gap-3 flex-wrap mb-3">
                <span className="px-3 py-1 rounded-full bg-zinc-800 text-xs text-zinc-200 font-medium">
                  VIX: {((regimeRaw as any).vix_regime ?? "mid").toUpperCase()}
                </span>
                <span className="px-3 py-1 rounded-full bg-zinc-800 text-xs text-zinc-200 font-medium">
                  Trend: {((regimeRaw as any).trend_regime ?? "chop").toUpperCase()}
                </span>
                <span className="px-3 py-1 rounded-full bg-zinc-800 text-xs text-zinc-200 font-medium">
                  BTC.D: {typeof (regimeRaw as any).btc_dominance === "number" ? `${((regimeRaw as any).btc_dominance as number).toFixed(1)}%` : "50.0%"}
                </span>
              </div>
              <p className="text-xs text-zinc-500">
                {(regimeRaw as any).regime
                  ? `Regime: ${(regimeRaw as any).regime} — bots are adjusting strategy accordingly`
                  : "Bots are optimizing for current market conditions"}
              </p>
            </>
          ) : (
            <p className="text-xs text-zinc-600">Regime: Scanning markets...</p>
          )}
        </div>

        {/* Row 4 – 3 Portfolio Cards */}
        <div className="mb-8">
          {portfolios.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {portfolios.map((p) => <PortfolioCard key={p.id} p={p} />)}
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {[{ emoji: "📈", name: "Stocks" }, { emoji: "🪙", name: "Crypto" }, { emoji: "⚡", name: "Options" }].map((p) => (
                <Link key={p.name} to="/strategy" className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 hover:border-zinc-700 transition-colors">
                  <div className="flex items-center gap-2 mb-4">
                    <span className="text-xl">{p.emoji}</span>
                    <span className="text-sm font-medium text-zinc-400">{p.name}</span>
                  </div>
                  <div className="text-2xl font-bold text-zinc-700">--</div>
                  <div className="text-sm text-zinc-700 mt-1">--</div>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Row 5 – Analyst Highlights */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-zinc-300">Analyst Highlights</h2>
            <Link to="/strategy/analyst" className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">View all →</Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {highlights.map((h, i) => (
              <div key={`${h.symbol}-${i}`} className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-bold text-white">{h.symbol}</span>
                  <span className={cn("text-xs font-semibold px-1.5 py-0.5 rounded", CONVICTION_STYLE[h.conviction] ?? "bg-zinc-700 text-zinc-400")}>
                    {h.conviction}
                  </span>
                </div>
                <p className="text-xs text-zinc-500 leading-relaxed">{h.thesis}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Row 6 – Today's Catalysts */}
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-sm font-semibold text-zinc-300">Catalysts</h2>
            <span className="text-xs text-zinc-600">{new Date().toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
            {catalysts.map((c: any, i: number) => (
              <span key={c.id ?? i} className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-zinc-800 border border-zinc-700 text-xs text-zinc-200 whitespace-nowrap">
                {c.description && c.description.length <= 2 ? c.description : "📅"} {c.event_type}{c.symbol ? ` · ${c.symbol}` : ""}
              </span>
            ))}
          </div>
        </div>

        {/* Row 7 – Live Activity Feed */}
        <div className="mb-8 bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-zinc-300">Live Activity</h2>
            <Link to="/strategy" className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">View all →</Link>
          </div>
          {signals.length > 0 ? (
            <div>{signals.map((s, i) => <SignalRow key={`${s.ts}-${s.symbol}-${i}`} s={s} />)}</div>
          ) : (
            <p className="text-sm text-zinc-600 py-4 text-center">No signals yet</p>
          )}
        </div>

        {/* Row 8 – Top Positions */}
        <div className="mb-8 bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-zinc-300">Top Positions</h2>
            <span className="text-xs text-zinc-600">{topPositions.length} across all portfolios</span>
          </div>
          {topPositions.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-zinc-600 border-b border-zinc-800">
                    <th className="text-left pb-2 font-medium">Symbol</th>
                    <th className="text-left pb-2 font-medium">Side</th>
                    <th className="text-right pb-2 font-medium">Qty</th>
                    <th className="text-right pb-2 font-medium">Avg Cost</th>
                    <th className="text-right pb-2 font-medium">Current</th>
                    <th className="text-right pb-2 font-medium">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {topPositions.map((pos, i) => (
                    <tr key={`${pos.symbol}-${i}`} className="border-b border-zinc-800/50 last:border-0">
                      <td className="py-2 font-semibold text-white">{pos.symbol}</td>
                      <td className="py-2 text-zinc-400 capitalize">{pos.side}</td>
                      <td className="py-2 text-right tabular-nums text-zinc-300">{pos.qty}</td>
                      <td className="py-2 text-right tabular-nums text-zinc-400">{pos.avg_cost ? fmtUsd(pos.avg_cost) : "—"}</td>
                      <td className="py-2 text-right tabular-nums text-zinc-300">{pos.current ? fmtUsd(pos.current) : "—"}</td>
                      <td className={cn("py-2 text-right tabular-nums font-medium", pos.pnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                        {pos.pnl >= 0 ? "+" : ""}{fmtUsd(pos.pnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-zinc-600 py-4 text-center">No open positions</p>
          )}
        </div>

        {/* Row 9 – Watchlist Movers */}
        <div className="mb-8">
          <h2 className="text-sm font-semibold text-zinc-300 mb-3">Watchlist Movers</h2>
          {movers.length > 0 ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {movers.map((m, i) => (
                <div key={`${m.symbol}-${i}`} className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-bold text-white">{m.symbol}</span>
                    <span className={cn("text-xs font-semibold px-1.5 py-0.5 rounded-full", m.score >= 70 ? "bg-emerald-500/10 text-emerald-400" : "bg-zinc-700 text-zinc-400")}>
                      {m.score}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-600 truncate">{m.portfolio}</p>
                  <span className="mt-2 inline-block text-xs px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400">{m.status}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-zinc-600 py-4">No watchlist movers</p>
          )}
        </div>

        {/* Row 10 – Strategy Spotlight */}
        <div className="mb-8 bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
          <h2 className="text-sm font-semibold text-zinc-300 mb-3">Strategy Spotlight</h2>
          {topBot ? (
            <div className="flex items-center justify-between">
              <div>
                <div className="text-base font-bold text-white capitalize">{topBot.name.replace(/_/g, " ")}</div>
                <div className="text-xs text-zinc-500 mt-0.5">30-day leader</div>
              </div>
              <span className={cn("text-lg font-bold tabular-nums", topBot.return_30d_pct >= 0 ? "text-emerald-400" : "text-red-400")}>
                {fmtPct(topBot.return_30d_pct)}
              </span>
            </div>
          ) : (
            <p className="text-sm text-zinc-600">Scanning top strategies...</p>
          )}
        </div>

        {/* Row 11 – Learning Tip */}
        <div className="mb-8 bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
          <h2 className="text-sm font-semibold text-zinc-300 mb-2">Daily Tip</h2>
          <p className="text-sm text-zinc-400">💡 {dailyTip}</p>
        </div>

        {/* Row 12 – Quick Links footer */}
        <div className="mb-4">
          <div className="flex items-center justify-around flex-wrap gap-4 py-4 border-t border-zinc-800">
            {[
              { label: "Strategy Lab", to: "/strategy" },
              { label: "Screener", to: "/screener" },
              { label: "Analytics", to: "/analytics" },
              { label: "Chart", to: "/chart" },
            ].map((link) => (
              <Link key={link.to} to={link.to} className="text-sm text-zinc-500 hover:text-white transition-colors flex items-center gap-1">
                {link.label} <span className="text-zinc-700">→</span>
              </Link>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}

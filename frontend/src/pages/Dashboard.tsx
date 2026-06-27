import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import TickerTape from "@/components/ui/TickerTape";
import { BracketFrame, SectionLabel } from "@/components/design";
import client from "@/api/client";
import { pauseAllBots } from "@/api/bots";
import { getDashboardV2, type DashboardV2, type DashV2Sleeve } from "@/api/dashboard";
import { useIsViewer } from "@/store/authStore";
import type { AnalystHighlight } from "@/api/analyst";

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

const SLEEVE_META: Record<string, { name: string; emoji: string }> = {
  stocks:  { name: "Stocks",  emoji: "📈" },
  crypto:  { name: "Crypto",  emoji: "🪙" },
  options: { name: "Options", emoji: "⚡" },
};

function SleeveCard({ id, sleeve }: { id: string; sleeve: DashV2Sleeve }) {
  const meta = SLEEVE_META[id] ?? { name: id, emoji: "📊" };
  const starting = sleeve.value_cents - sleeve.pnl_cents;
  const pnlPct = starting > 0 ? sleeve.pnl_cents / starting * 100 : 0;
  const isUp = sleeve.pnl_cents >= 0;
  return (
    <Link to="/strategy" className="block bg-t-bg1 border border-t-dim rounded-2xl p-6 hover:border-t-mid card-hover transition-colors">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-xl">{meta.emoji}</span>
          <span className="text-sm font-medium text-t-mid2 capitalize">{meta.name}</span>
        </div>
        <span className={cn("text-xs font-semibold px-2 py-0.5 rounded-full font-mono-t tabular-nums", isUp ? "bg-t-green/10 text-t-green" : "bg-t-red/10 text-t-red")}>
          {fmtPct(pnlPct)}
        </span>
      </div>
      <div className="text-2xl font-bold text-t-hi tabular-nums font-mono-t">{fmtUsd(sleeve.value_cents)}</div>
      <div className={cn("text-sm mt-1 tabular-nums font-mono-t", isUp ? "text-t-green" : "text-t-red")}>
        {isUp ? "+" : ""}{fmtUsd(sleeve.pnl_cents)} all time
      </div>
      <div className={cn(
        "inline-flex items-center gap-1.5 text-xs font-bold mt-2 px-2 py-1 rounded-md border",
        isUp
          ? "bg-emerald-500/8 border-emerald-500/20 text-t-green"
          : "bg-red-500/8 border-red-500/20 text-t-red"
      )}>
        <span className="text-t-muted font-medium">ALL-TIME</span>
        <span className="font-mono-t tabular-nums">{fmtPct(pnlPct)}</span>
      </div>
      <div className="mt-4 pt-4 border-t border-t-dim flex justify-between text-xs text-t-muted">
        <span>{sleeve.bots_total} bot{sleeve.bots_total !== 1 ? "s" : ""}{sleeve.reserved_capital_cents > 0 ? ` · ${fmtUsd(sleeve.reserved_capital_cents)} reserved` : ""}</span>
        <span>{sleeve.bots_active} active · {sleeve.open_positions} pos · {sleeve.watching} watching</span>
      </div>
    </Link>
  );
}

function SignalRow({ s }: { s: DashboardV2["recent_signals"][number] }) {
  const dotCls = { buy: "bg-emerald-500", long: "bg-emerald-500", sell: "bg-red-500", short: "bg-red-500", hold: "bg-zinc-500" }[s.side] ?? "bg-zinc-500";
  const textCls = { buy: "text-t-green", long: "text-t-green", sell: "text-t-red", short: "text-t-red", hold: "text-t-mid2" }[s.side] ?? "text-t-mid2";
  return (
    <div className="flex items-center gap-3 py-3 border-b border-t-dim last:border-0">
      <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", dotCls)} />
      <span className="font-semibold text-t-hi text-sm w-16 flex-shrink-0">{s.symbol}</span>
      <span className={cn("text-xs font-medium uppercase w-8 flex-shrink-0", textCls)}>{s.side}</span>
      <span className="text-xs text-t-muted flex-1 truncate">{s.reason || s.strategy}</span>
      <span className="text-xs text-t-muted flex-shrink-0">{timeAgo(s.ts)}</span>
    </div>
  );
}

const CONVICTION_STYLE: Record<string, string> = {
  HIGH: "bg-t-green/10 text-t-green",
  MED: "bg-yellow-500/10 text-yellow-400",
  LOW: "bg-zinc-700 text-t-mid2",
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

  const { data } = useQuery({
    queryKey: ["dashboard-v2"],
    queryFn: getDashboardV2,
    staleTime: 60_000,
    retry: 1,
  });

  const { data: regime } = useQuery({
    queryKey: ["portfolio-regime"],
    queryFn: () => client.get<{
      regime: string; confidence: number | null; days_in_regime: number;
      vix_level: number | null; routing_enabled: boolean; snapshot_date: string | null;
    }>("/portfolio/regime/current").then(r => r.data),
    staleTime: 120_000,
    retry: 0,
  });

  const invalidateAll = () => qc.invalidateQueries({ queryKey: ["dashboard-v2"] });
  const pauseMut = useMutation({ mutationFn: pauseAllBots, onSuccess: invalidateAll });

  // ── Map v2 response to render variables ──────────────────────────────────
  const totalValue = data?.portfolio.total_value_cents ?? 0;
  const todayPnl = data?.portfolio.today_pnl_cents ?? 0;
  const todayPct = data?.portfolio.today_pnl_pct ?? 0;
  const return30d = data?.portfolio.return_30d_pct ?? 0;
  const isUp = todayPnl >= 0;

  const leaderboard = data?.portfolio.leaderboard ?? [];
  const topBot = leaderboard.length > 0
    ? leaderboard.reduce((a, b) => b.return_30d_pct > a.return_30d_pct ? b : a)
    : null;

  // deployed_cents + starting_capital_cents now ride on the dashboard-v2
  // leaderboard entry itself (threaded through dashboard.py), so no extra
  // fetch of /strategy-lab/portfolio is required.
  const topBotDeploy = topBot
    ? { deployed_cents: topBot.deployed_cents, starting_capital_cents: topBot.starting_capital_cents }
    : undefined;

  const signals = data?.recent_signals ?? [];

  const highlights: AnalystHighlight[] =
    data?.analyst_highlights && data.analyst_highlights.length > 0
      ? data.analyst_highlights
      : PLACEHOLDER_HIGHLIGHTS;

  const topPositions = (data?.open_positions ?? []).slice(0, 5).map((pos) => ({
    symbol: pos.symbol,
    side: pos.side,
    qty: pos.qty,
    avg_cost: pos.avg_cost_cents,
    current: pos.avg_cost_cents,
    pnl: 0,
    botName: pos.bot_name,
  }));

  const todayDow = new Date().getDay();
  const dailyTip = DAILY_TIPS[todayDow] ?? DAILY_TIPS[1];

  // Banner: warn only if no active bots, not just because data hasn't loaded
  const botsEnabled = data ? data.health.status === "ok" : true;

  return (
    <div className="min-h-screen bg-t-bg0 text-t-hi animate-page-in">

      {/* S&P 500 Live Ticker Tape */}
      <TickerTape />

      {/* Row 1 – Health Bar */}
      <div className="sticky top-0 z-10 bg-t-bg1/80 backdrop-blur border-b border-t-dim px-6 py-2 flex items-center justify-between text-xs">
        <div className="flex items-center gap-2">
          <span className={cn("w-1.5 h-1.5 rounded-full", botsEnabled ? "bg-emerald-500" : "bg-yellow-500")} />
          <span className={botsEnabled ? "text-t-hi" : "text-yellow-400"}>
            {botsEnabled ? "All systems normal" : "Warning: bots may be disabled"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {!isViewer && (
            <button
              onClick={() => pauseMut.mutate()}
              disabled={pauseMut.isPending}
              className="px-3 py-1 rounded-lg bg-t-bg2 hover:bg-zinc-700 text-t-hi transition-colors disabled:opacity-50"
            >
              Pause All
            </button>
          )}
          <button
            onClick={() => window.dispatchEvent(new CustomEvent("copilot:open", { detail: { query: "Brief me on what's happening with my bots today." } }))}
            className="px-3 py-1 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 text-t-green transition-colors"
          >
            Brief me
          </button>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-10">

        {/* Row 2 – Hero Stats */}
        <BracketFrame className="mb-8 p-5 rounded-xl" glow>
          <SectionLabel as="p" className="mb-3">Portfolio Value</SectionLabel>
          <div className="text-5xl font-bold tracking-tight tabular-nums font-mono-t">
            {totalValue ? fmtUsd(totalValue) : <span className="text-t-muted">$—</span>}
          </div>
          <div className="flex items-center gap-4 mt-3 flex-wrap">
            <span className={cn("text-lg font-semibold tabular-nums font-mono-t", isUp ? "text-[var(--bmg-green)]" : "text-t-red")}>
              {isUp ? "+" : ""}{fmtUsd(todayPnl)}{" "}
              <span className="text-sm font-normal">({fmtPct(todayPct)} today)</span>
            </span>
            <span className="text-t-muted">·</span>
            <span className={cn("text-sm tabular-nums font-mono-t", return30d >= 0 ? "text-[var(--bmg-green)]/70" : "text-t-red/70")}>
              {fmtPct(return30d)} 30d
            </span>
          </div>
        </BracketFrame>

        {/* Row 3 – Market Regime */}
        <div className="mb-8 bg-t-bg1 border border-t-dim rounded-2xl p-5">
          <SectionLabel as="h2" className="mb-3 text-t-hi">Market Regime</SectionLabel>
          {regime ? (
            <div className="flex items-center gap-3 flex-wrap">
              <span className="px-3 py-1 rounded-full bg-t-bg2 text-xs text-t-hi font-medium uppercase tracking-wide">
                {regime.regime}
              </span>
              {regime.days_in_regime > 0 && (
                <span className="px-3 py-1 rounded-full bg-t-bg2 text-xs text-t-muted font-medium">
                  {regime.days_in_regime}d in regime
                </span>
              )}
              {regime.confidence != null && (
                <span className="px-3 py-1 rounded-full bg-t-bg2 text-xs text-t-muted font-medium font-mono-t tabular-nums">
                  {(regime.confidence * 100).toFixed(0)}% conf
                </span>
              )}
              {regime.vix_level != null && (
                <span className="px-3 py-1 rounded-full bg-t-bg2 text-xs text-t-muted font-medium font-mono-t tabular-nums">
                  VIX {regime.vix_level.toFixed(1)}
                </span>
              )}
            </div>
          ) : (
            <p className="text-xs text-t-muted">Regime: Scanning markets...</p>
          )}
        </div>

        {/* Row 4 – 4 Sleeve Cards (Stocks/Crypto/Options/Quant). Render every
            canonical sleeve even if the API omits one — Dashboard was missing
            Quant pre-2026-06-27 because this array was hardcoded to 3. */}
        <div className="mb-8">
          {data?.sleeves ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {(["stocks", "crypto", "options", "quant"] as const).map((key) => (
                data.sleeves[key] ? (
                  <SleeveCard key={key} id={key} sleeve={data.sleeves[key]} />
                ) : (
                  <div key={key} className="bg-t-bg1 border border-t-dim rounded-2xl p-6 opacity-60">
                    <div className="text-sm font-medium text-t-mid2 uppercase tracking-wide mb-2">{key}</div>
                    <div className="text-2xl font-bold text-t-muted font-mono-t tabular-nums">--</div>
                    <div className="text-xs text-t-muted mt-1">sleeve missing from payload</div>
                  </div>
                )
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                { emoji: "📈", name: "Stocks" },
                { emoji: "🪙", name: "Crypto" },
                { emoji: "⚡", name: "Options" },
                { emoji: "∑",  name: "Quant"   },
              ].map((p) => (
                <Link key={p.name} to="/strategy" className="bg-t-bg1 border border-t-dim rounded-2xl p-6 hover:border-t-mid card-hover transition-colors">
                  <div className="flex items-center gap-2 mb-4">
                    <span className="text-xl">{p.emoji}</span>
                    <span className="text-sm font-medium text-t-mid2">{p.name}</span>
                  </div>
                  <div className="text-2xl font-bold text-t-muted font-mono-t tabular-nums">--</div>
                  <div className="text-sm text-t-muted mt-1">--</div>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Row 5 – Analyst Highlights */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-3">
            <SectionLabel as="h2" className="text-t-hi">Analyst Highlights</SectionLabel>
            <Link to="/strategy/analyst" className="text-xs text-t-muted hover:text-t-hi transition-colors">View all →</Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {highlights.map((h, i) => (
              <div key={`${h.symbol}-${i}`} className="bg-t-bg1 border border-t-dim rounded-2xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-bold text-t-hi">{h.symbol}</span>
                  <span className={cn("text-xs font-semibold px-1.5 py-0.5 rounded", CONVICTION_STYLE[h.conviction] ?? "bg-zinc-700 text-t-mid2")}>
                    {h.conviction}
                  </span>
                </div>
                <p className="text-xs text-t-muted leading-relaxed">{h.thesis}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Row 6 – Today's Catalysts */}
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-3">
            <SectionLabel as="h2" className="text-t-hi">Catalysts</SectionLabel>
            <span className="text-xs text-t-muted">{new Date().toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
            {PLACEHOLDER_CATALYSTS.map((c: any, i: number) => (
              <span key={c.id ?? i} className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-t-bg2 border border-t-mid text-xs text-t-hi whitespace-nowrap">
                {c.description && c.description.length <= 2 ? c.description : "📅"} {c.event_type}{c.symbol ? ` · ${c.symbol}` : ""}
              </span>
            ))}
          </div>
        </div>

        {/* Row 7 – Live Activity Feed */}
        <div className="mb-8 bg-t-bg1 border border-t-dim rounded-2xl p-5">
          <div className="flex items-center justify-between mb-3">
            <SectionLabel as="h2" className="text-t-hi">Live Activity</SectionLabel>
            <Link to="/strategy" className="text-xs text-t-muted hover:text-t-hi transition-colors">View all →</Link>
          </div>
          {signals.length > 0 ? (
            <div>{signals.map((s, i) => <SignalRow key={`${s.ts}-${s.symbol}-${i}`} s={s} />)}</div>
          ) : (
            <p className="text-sm text-t-muted py-4 text-center">No signals yet</p>
          )}
        </div>

        {/* Row 8 – Top Positions */}
        <div className="mb-8 bg-t-bg1 border border-t-dim rounded-2xl p-5">
          <div className="flex items-center justify-between mb-3">
            <SectionLabel as="h2" className="text-t-hi">Top Positions</SectionLabel>
            <span className="text-xs text-t-muted font-mono-t tabular-nums">{topPositions.length} across all portfolios</span>
          </div>
          {topPositions.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-t-muted border-b border-t-dim">
                    <th className="text-left pb-2 font-medium">Symbol</th>
                    <th className="text-left pb-2 font-medium">Side</th>
                    <th className="text-right pb-2 font-medium">Qty</th>
                    <th className="text-right pb-2 font-medium">Avg Cost</th>
                    <th className="text-right pb-2 font-medium">Bot</th>
                  </tr>
                </thead>
                <tbody>
                  {topPositions.map((pos, i) => (
                    <tr key={`${pos.symbol}-${i}`} className="border-b border-t-dim/50 last:border-0">
                      <td className="py-2 font-semibold text-t-hi">{pos.symbol}</td>
                      <td className="py-2 text-t-mid2 capitalize">{pos.side}</td>
                      <td className="py-2 text-right tabular-nums font-mono-t text-t-hi">{pos.qty}</td>
                      <td className="py-2 text-right tabular-nums font-mono-t text-t-mid2">{pos.avg_cost ? fmtUsd(pos.avg_cost) : "—"}</td>
                      <td className="py-2 text-right text-t-muted text-xs">{pos.botName.replace(/_/g, " ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-t-muted py-4 text-center">No open positions</p>
          )}
        </div>

        {/* Row 9 – Strategy Spotlight */}
        <div className="mb-8 bg-t-bg1 border border-t-dim rounded-2xl p-5">
          <SectionLabel as="h2" className="text-t-hi mb-3">Strategy Spotlight</SectionLabel>
          {topBot ? (
            <div className="flex items-center justify-between">
              <div>
                <div className="text-base font-bold text-t-hi capitalize">{topBot.name.replace(/_/g, " ")}</div>
                <div className="text-xs text-t-muted mt-0.5">30-day leader</div>
                {topBotDeploy && (topBotDeploy.starting_capital_cents ?? 0) > 0 && (
                  <div className="text-[11px] text-t-mid2 mt-1 font-mono-t tabular-nums">
                    deployed:{" "}
                    {(
                      ((topBotDeploy.deployed_cents ?? 0) /
                        (topBotDeploy.starting_capital_cents ?? 1)) *
                      100
                    ).toFixed(0)}
                    % of {fmtUsd(topBotDeploy.starting_capital_cents ?? 0)}
                  </div>
                )}
              </div>
              <span className={cn("text-lg font-bold tabular-nums font-mono-t", topBot.return_30d_pct >= 0 ? "text-t-green" : "text-t-red")}>
                {fmtPct(topBot.return_30d_pct)}
              </span>
            </div>
          ) : (
            <p className="text-sm text-t-muted">Scanning top strategies...</p>
          )}
        </div>

        {/* Row 10 – Learning Tip */}
        <div className="mb-8 bg-t-bg1 border border-t-dim rounded-2xl p-5">
          <SectionLabel as="h2" className="text-t-hi mb-2">Daily Tip</SectionLabel>
          <p className="text-sm text-t-mid2">💡 {dailyTip}</p>
        </div>

        {/* Row 11 – Quick Links footer */}
        <div className="mb-4">
          <div className="flex items-center justify-around flex-wrap gap-4 py-4 border-t border-t-dim">
            {[
              { label: "Strategy Lab", to: "/strategy" },
              { label: "Screener", to: "/screener" },
              { label: "Analytics", to: "/strategy/performance" },
              { label: "Chart", to: "/chart" },
            ].map((link) => (
              <Link key={link.to} to={link.to} className="text-sm text-t-muted hover:text-t-hi transition-colors flex items-center gap-1">
                {link.label} <span className="text-t-muted">→</span>
              </Link>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import {
  getStrategyLabPortfolio,
  getPortfolios,
  getRecentSignals,
  type StrategyPortfolio,
  type RecentSignal,
} from "@/api/bots";

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
  } catch {
    return "";
  }
}

// ─── Portfolio card ───────────────────────────────────────────────────────────

function PortfolioCard({ p }: { p: StrategyPortfolio }) {
  const isUp = p.pnl_cents >= 0;

  return (
    <Link
      to="/strategy"
      className="block bg-zinc-900 border border-zinc-800 rounded-2xl p-6 hover:border-zinc-700 transition-colors"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-xl">{p.emoji}</span>
          <span className="text-sm font-medium text-zinc-400 capitalize">{p.name}</span>
        </div>
        <span
          className={cn(
            "text-xs font-semibold px-2 py-0.5 rounded-full",
            isUp
              ? "bg-emerald-500/10 text-emerald-400"
              : "bg-red-500/10 text-red-400"
          )}
        >
          {fmtPct(p.pnl_pct)}
        </span>
      </div>

      <div className="text-2xl font-bold text-white tabular-nums">
        {fmtUsd(p.current_value_cents)}
      </div>

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

// ─── Signal row ───────────────────────────────────────────────────────────────

function SignalRow({ s }: { s: RecentSignal }) {
  const sideColor = {
    buy: "text-emerald-400",
    sell: "text-red-400",
    hold: "text-zinc-400",
  }[s.side] ?? "text-zinc-400";

  const sideDot = {
    buy: "bg-emerald-500",
    sell: "bg-red-500",
    hold: "bg-zinc-500",
  }[s.side] ?? "bg-zinc-500";

  return (
    <div className="flex items-center gap-3 py-3 border-b border-zinc-800 last:border-0">
      <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", sideDot)} />
      <span className="font-semibold text-white text-sm w-16 flex-shrink-0">{s.symbol}</span>
      <span className={cn("text-xs font-medium uppercase w-8 flex-shrink-0", sideColor)}>{s.side}</span>
      <span className="text-xs text-zinc-500 flex-1 truncate">{s.reason || s.strategy}</span>
      <span className="text-xs text-zinc-600 flex-shrink-0">{timeAgo(s.ts)}</span>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const { data: overview } = useQuery({
    queryKey: ["strategy-lab-portfolio"],
    queryFn: getStrategyLabPortfolio,
    staleTime: 60_000,
    retry: 0,
  });

  const { data: portfoliosData } = useQuery({
    queryKey: ["portfolios"],
    queryFn: getPortfolios,
    staleTime: 60_000,
    retry: 0,
  });

  const { data: signalsData } = useQuery({
    queryKey: ["recent-signals", 8],
    queryFn: () => getRecentSignals(8),
    staleTime: 30_000,
    retry: 0,
  });

  const portfolios = portfoliosData?.portfolios ?? [];
  const signals = signalsData?.signals ?? [];

  const totalValue = overview?.total_value_cents ?? 0;
  const todayPnl = overview?.today_pnl_cents ?? 0;
  const todayPct = overview?.today_pnl_pct ?? 0;
  const return30d = overview?.return_30d_pct ?? 0;
  const isUp = todayPnl >= 0;

  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-10 space-y-10">

        {/* Hero */}
        <div>
          <p className="text-sm text-zinc-500 mb-1">Total Portfolio Value</p>
          <div className="text-5xl font-bold tracking-tight tabular-nums">
            {totalValue ? fmtUsd(totalValue) : <span className="text-zinc-700">$—</span>}
          </div>
          <div className="flex items-center gap-4 mt-3">
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

        {/* 3 Portfolio cards */}
        {portfolios.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {portfolios.map((p) => (
              <PortfolioCard key={p.id} p={p} />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {[
              { emoji: "📈", name: "Stocks" },
              { emoji: "🪙", name: "Crypto" },
              { emoji: "⚡", name: "Options" },
            ].map((p) => (
              <Link
                key={p.name}
                to="/strategy"
                className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 hover:border-zinc-700 transition-colors"
              >
                <div className="flex items-center gap-2 mb-4">
                  <span className="text-xl">{p.emoji}</span>
                  <span className="text-sm font-medium text-zinc-400">{p.name}</span>
                </div>
                <div className="text-zinc-700 text-sm">No data yet</div>
              </Link>
            ))}
          </div>
        )}

        {/* Recent signals + Quick links (side by side on large screens) */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Recent signals */}
          <div className="lg:col-span-2 bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-zinc-300">Recent Signals</h2>
              <Link to="/strategy" className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
                View all →
              </Link>
            </div>
            {signals.length > 0 ? (
              <div>
                {signals.map((s, i) => (
                  <SignalRow key={`${s.ts}-${s.symbol}-${i}`} s={s} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-zinc-600 py-6 text-center">
                No signals yet — bots will post here when they find setups.
              </p>
            )}
          </div>

          {/* Quick links */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
            <h2 className="text-sm font-semibold text-zinc-300 mb-4">Quick Links</h2>
            <nav className="space-y-1">
              {[
                { label: "Strategy Lab", to: "/strategy", desc: "Bots & portfolios" },
                { label: "Screener", to: "/screener", desc: "Find setups" },
                { label: "Strategy Library", to: "/library", desc: "Browse strategies" },
                { label: "Analyst", to: "/analyst", desc: "AI thesis & picks" },
                { label: "Custom Bot Builder", to: "/custom-bot", desc: "Build your own" },
              ].map((link) => (
                <Link
                  key={link.to}
                  to={link.to}
                  className="flex items-center justify-between px-3 py-2.5 rounded-xl hover:bg-zinc-800 transition-colors group"
                >
                  <div>
                    <div className="text-sm font-medium text-zinc-200 group-hover:text-white transition-colors">
                      {link.label}
                    </div>
                    <div className="text-xs text-zinc-600">{link.desc}</div>
                  </div>
                  <span className="text-zinc-700 group-hover:text-zinc-400 transition-colors text-xs">→</span>
                </Link>
              ))}
            </nav>
          </div>
        </div>

      </div>
    </div>
  );
}

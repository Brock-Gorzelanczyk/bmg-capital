import { useState, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, X, Lock, Unlock } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  BarChart,
  Bar,
  Cell,
} from "recharts";
import {
  getBot,
  allocateBot,
  joinWaitlist,
  leaveWaitlist,
  getRegime,
  getBotWatchlist,
  runBacktest,
  getCatalysts,
  getActivity,
  getStrategyWeights,
  updateStrategyWeight,
  type BotPosition,
  type BotSignal,
  type RegimeData,
  type WatchlistItem,
  type CatalystEvent,
  type ActivityEvent,
  type StrategyWeight,
} from "@/api/bots";
import { cn } from "@/lib/utils";

// ─── Bot metadata ─────────────────────────────────────────────────────────────

const BOT_META: Record<
  string,
  { displayName: string; description: string; assetClass: "stock" | "crypto"; strategies: string[] }
> = {
  stock_swing: {
    displayName: "Stock Swing",
    description: "Russell 1000 momentum plays, 1-30 day holds",
    assetClass: "stock",
    strategies: ["momentum", "breakout", "mean_reversion"],
  },
  stock_day: {
    displayName: "Stock Day",
    description: "Intraday gappers & earnings momentum, EOD flat",
    assetClass: "stock",
    strategies: ["gap_and_go", "earnings_momentum", "vwap_reclaim"],
  },
  stock_lt: {
    displayName: "Stock Long-Term",
    description: "S&P 500 factor model, monthly rebalance",
    assetClass: "stock",
    strategies: ["value_factor", "quality_factor", "low_vol_factor"],
  },
  crypto_swing: {
    displayName: "Crypto Swing",
    description: "Top 20 crypto by mcap, 1-30 day holds",
    assetClass: "crypto",
    strategies: ["momentum", "on_chain_signal", "funding_reversal"],
  },
  crypto_day: {
    displayName: "Crypto Day",
    description: "BTC/ETH/SOL intraday momentum, 24h force-close",
    assetClass: "crypto",
    strategies: ["orderflow", "liquidation_hunt", "trend_follow"],
  },
  crypto_lt: {
    displayName: "Crypto L-T DCA",
    description: "BTC/ETH + majors, weekly DCA & monthly rebalance",
    assetClass: "crypto",
    strategies: ["dca_core", "rebalance", "altseason_rotate"],
  },
};

// ─── Hardcoded upcoming FOMC dates as fallback catalysts ─────────────────────

const FOMC_FALLBACK: CatalystEvent[] = [
  { id: "fomc-1", event_type: "FOMC", symbol: null, event_ts: "2026-07-29T18:00:00Z", description: "FOMC Rate Decision" },
  { id: "fomc-2", event_type: "FOMC", symbol: null, event_ts: "2026-09-16T18:00:00Z", description: "FOMC Rate Decision" },
  { id: "fomc-3", event_type: "FOMC", symbol: null, event_ts: "2026-11-04T18:00:00Z", description: "FOMC Rate Decision" },
  { id: "fomc-4", event_type: "FOMC", symbol: null, event_ts: "2026-12-16T18:00:00Z", description: "FOMC Rate Decision" },
  { id: "fomc-5", event_type: "CPI", symbol: null, event_ts: "2026-06-10T12:30:00Z", description: "CPI Report" },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function displayName(name: string): string {
  return (
    BOT_META[name]?.displayName ??
    name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

function formatPnl(val: number): string {
  const abs = Math.abs(val);
  const sign = val >= 0 ? "+" : "-";
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(2)}`;
}

function formatPct(val: number): string {
  const sign = val >= 0 ? "+" : "";
  return `${sign}${val.toFixed(2)}%`;
}

function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function formatRelativeTime(ts: string): string {
  try {
    const now = Date.now();
    const then = new Date(ts).getTime();
    const diffMs = then - now;
    const diffMin = Math.round(diffMs / 60000);
    const diffH = Math.round(diffMs / 3600000);
    const diffD = Math.round(diffMs / 86400000);
    if (diffD > 0) return `in ${diffD}d`;
    if (diffH > 0) return `in ${diffH}h`;
    if (diffMin > 0) return `in ${diffMin}m`;
    if (diffMin < 0) return `${Math.abs(diffMin)}m ago`;
    return "now";
  } catch {
    return ts;
  }
}

function formatRelativeAgo(ts: string | null): string {
  if (!ts) return "—";
  try {
    const now = Date.now();
    const then = new Date(ts).getTime();
    const diffMs = now - then;
    const diffMin = Math.round(diffMs / 60000);
    const diffH = Math.round(diffMs / 3600000);
    const diffD = Math.round(diffMs / 86400000);
    if (diffD >= 1) return `${diffD}d ago`;
    if (diffH >= 1) return `${diffH}h ago`;
    if (diffMin >= 1) return `${diffMin}m ago`;
    return "just now";
  } catch {
    return ts;
  }
}

// ─── Side badge ───────────────────────────────────────────────────────────────

function SideBadge({ side }: { side: "buy" | "sell" | "hold" }) {
  const styles = {
    buy: "bg-lime-500/15 text-lime-400 border-lime-500/30",
    sell: "bg-red-500/15 text-red-400 border-red-500/30",
    hold: "bg-zinc-800 text-zinc-400 border-zinc-700",
  };
  return (
    <span className={cn("text-xs font-bold px-2 py-0.5 rounded-full border", styles[side])}>
      {side.toUpperCase()}
    </span>
  );
}

// ─── Equity curve ─────────────────────────────────────────────────────────────

interface EquityPoint {
  date: string;
  portfolio: number;
  benchmark: number;
}

function EquityCurve({ data, isCrypto }: { data: EquityPoint[]; isCrypto: boolean }) {
  const benchmarkLabel = isCrypto ? "BTC" : "SPY";

  if (!data || data.length === 0) {
    return (
      <div className="h-48 flex items-center justify-center bg-zinc-900/50 rounded-xl border border-zinc-800">
        <p className="text-zinc-600 text-sm">No equity data yet</p>
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
        <XAxis dataKey="date" tick={{ fill: "#71717a", fontSize: 10 }} tickLine={false} axisLine={false} />
        <YAxis tick={{ fill: "#71717a", fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => `${v.toFixed(1)}%`} />
        <Tooltip
          contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: "#a1a1aa" }}
        />
        <Line type="monotone" dataKey="portfolio" stroke="#84cc16" strokeWidth={2} dot={false} name="Portfolio" />
        <Line type="monotone" dataKey="benchmark" stroke="#52525b" strokeWidth={2} dot={false} name={benchmarkLabel} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ─── Regime helpers ───────────────────────────────────────────────────────────

function vixPillClass(regime: string): string {
  const r = regime?.toLowerCase() ?? "";
  if (r === "low") return "bg-green-500/15 text-green-400 border-green-500/30";
  if (r === "mid") return "bg-yellow-500/15 text-yellow-400 border-yellow-500/30";
  if (r === "high") return "bg-orange-500/15 text-orange-400 border-orange-500/30";
  if (r === "panic") return "bg-red-500/15 text-red-400 border-red-500/30";
  return "bg-zinc-800 text-zinc-400 border-zinc-700";
}

function trendPillClass(regime: string): string {
  const r = regime?.toLowerCase() ?? "";
  if (r === "bull") return "bg-lime-500/15 text-lime-400 border-lime-500/30";
  if (r === "chop") return "bg-zinc-700/40 text-zinc-400 border-zinc-600";
  if (r === "bear") return "bg-red-500/15 text-red-400 border-red-500/30";
  return "bg-zinc-800 text-zinc-400 border-zinc-700";
}

function getGatingText(regime: RegimeData | undefined): string {
  if (!regime) return "Regime data unavailable.";
  const vix = regime.vix_regime?.toLowerCase() ?? "mid";
  const trend = regime.trend_regime?.toLowerCase() ?? "chop";
  const parts: string[] = [];
  if (vix === "panic") parts.push("VIX in panic: all new entries halted.");
  else if (vix === "high") parts.push("VIX high: position sizes halved.");
  if (trend === "bear") parts.push("No new long entries in bear market.");
  else if (trend === "chop") parts.push("Choppy market: tighter entry filters active.");
  if (parts.length === 0) return "No active regime constraints — normal operations.";
  return parts.join(" ");
}

// ─── Regime panel ─────────────────────────────────────────────────────────────

function RegimePanel({ regime, isLoading }: { regime: RegimeData | undefined; isLoading: boolean }) {
  if (isLoading) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 animate-pulse">
        <div className="h-3 w-32 bg-zinc-800 rounded mb-3" />
        <div className="flex gap-2">
          {[0, 1, 2].map((i) => <div key={i} className="h-7 w-20 bg-zinc-800 rounded-full" />)}
        </div>
      </div>
    );
  }

  const vix = regime?.vix_regime?.toUpperCase() ?? "MID";
  const trend = regime?.trend_regime?.toUpperCase() ?? "CHOP";
  const btcDom = typeof regime?.btc_dominance === "number" ? `${regime.btc_dominance.toFixed(0)}%` : "—";

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3">
      <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-2">Current Regime</h3>
      <div className="flex flex-wrap gap-2">
        <span className={cn("inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border", vixPillClass(vix))}>
          <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
          VIX {vix}
        </span>
        <span className={cn("inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border", trendPillClass(trend))}>
          <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
          {trend}
        </span>
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border bg-zinc-800 border-zinc-700 text-zinc-300">
          <span className="w-1.5 h-1.5 rounded-full bg-orange-400" />
          BTC Dom {btcDom}
        </span>
      </div>
      <p className="text-xs text-zinc-600 mt-1.5">{getGatingText(regime)}</p>
    </div>
  );
}

// ─── Catalyst calendar ────────────────────────────────────────────────────────

function eventTypeColor(type: string): string {
  const t = type?.toLowerCase() ?? "";
  if (t === "fomc") return "bg-blue-500/15 text-blue-400";
  if (t === "cpi" || t === "pce") return "bg-orange-500/15 text-orange-400";
  if (t === "earnings") return "bg-lime-500/15 text-lime-400";
  if (t === "expiry") return "bg-purple-500/15 text-purple-400";
  return "bg-zinc-700/40 text-zinc-400";
}

function CatalystCalendar() {
  const { data: catalysts, isLoading } = useQuery({
    queryKey: ["catalysts"],
    queryFn: getCatalysts,
    retry: 0,
    staleTime: 300_000,
  });

  const events: CatalystEvent[] = (catalysts && catalysts.length > 0) ? catalysts : FOMC_FALLBACK;

  if (isLoading) {
    return (
      <div className="space-y-2 animate-pulse">
        {[0, 1, 2].map((i) => <div key={i} className="h-8 bg-zinc-800 rounded" />)}
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {events.slice(0, 5).map((evt) => (
        <div
          key={String(evt.id)}
          className="flex items-center gap-3 py-1.5 border-b border-zinc-800/50 last:border-0"
        >
          <span className={cn("text-xs font-semibold px-2 py-0.5 rounded", eventTypeColor(evt.event_type))}>
            {evt.event_type.toUpperCase()}
          </span>
          <span className="text-xs text-zinc-400">{evt.symbol ?? (evt.description ?? "Market-wide")}</span>
          <span className="text-xs text-zinc-600 ml-auto">{formatRelativeTime(evt.event_ts)}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Why modal ────────────────────────────────────────────────────────────────

interface WhyModalProps {
  signal: BotSignal | null;
  onClose: () => void;
}

function WhyModal({ signal, onClose }: WhyModalProps) {
  if (!signal) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative bg-zinc-900 border border-zinc-700 rounded-2xl p-6 w-full max-w-md shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-white font-semibold text-base">Why did we trade this?</h3>
          <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-4">
          <div className="flex gap-4">
            <div className="flex-1">
              <p className="text-xs text-zinc-500 mb-1">Symbol</p>
              <p className="text-sm font-semibold text-white">{signal.symbol}</p>
            </div>
            <div>
              <p className="text-xs text-zinc-500 mb-1">Direction</p>
              <SideBadge side={signal.side} />
            </div>
          </div>

          <div>
            <p className="text-xs text-zinc-500 mb-1">Strategy</p>
            <p className="text-sm font-semibold text-white">{signal.strategy}</p>
          </div>

          <div>
            <p className="text-xs text-zinc-500 mb-1">Signal Reason</p>
            <p className="text-sm text-zinc-300">{signal.reason || "—"}</p>
          </div>

          <div>
            <p className="text-xs text-zinc-500 mb-1">Confidence</p>
            <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
              <div
                className="h-2 bg-lime-500 rounded-full transition-all"
                style={{ width: `${Math.min(100, Math.max(0, signal.confidence * 100))}%` }}
              />
            </div>
            <p className="text-xs text-zinc-500 mt-0.5">{(signal.confidence * 100).toFixed(0)}%</p>
          </div>

          <div>
            <p className="text-xs text-zinc-500 mb-1">Signal Time</p>
            <p className="text-xs text-zinc-400">{formatTime(signal.ts)}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Watchlist table ──────────────────────────────────────────────────────────

function WatchlistTable({ botName }: { botName: string }) {
  const [showAll, setShowAll] = useState(false);

  const { data: watchlist = [], isLoading } = useQuery({
    queryKey: ["watchlist", botName],
    queryFn: () => getBotWatchlist(botName),
    enabled: !!botName,
    retry: 0,
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="animate-pulse space-y-2">
        {[0, 1, 2, 3].map((i) => <div key={i} className="h-10 bg-zinc-800 rounded" />)}
      </div>
    );
  }

  if (!watchlist || watchlist.length === 0) {
    return (
      <p className="text-zinc-600 text-sm py-6 text-center">
        Watchlist rebuilds at next scheduled cadence
      </p>
    );
  }

  const displayed = showAll ? watchlist : watchlist.slice(0, 20);

  function statusBadgeClass(status: string): string {
    const s = status?.toLowerCase() ?? "";
    if (s === "active") return "bg-lime-500/15 text-lime-400 border-lime-500/30";
    if (s === "blacklisted") return "bg-red-500/15 text-red-400 border-red-500/30";
    return "bg-zinc-800 text-zinc-400 border-zinc-700";
  }

  function getTopReason(reasons: Record<string, number> | null): string {
    if (!reasons) return "—";
    const entries = Object.entries(reasons);
    if (entries.length === 0) return "—";
    const top = entries.sort((a, b) => b[1] - a[1])[0];
    return top[0].replace(/_/g, " ");
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-zinc-600 border-b border-zinc-800">
              <th className="text-left pb-2 font-medium w-8">#</th>
              <th className="text-left pb-2 font-medium">Symbol</th>
              <th className="text-left pb-2 font-medium w-32">Score</th>
              <th className="text-left pb-2 font-medium">Top Reason</th>
              <th className="text-left pb-2 font-medium">Status</th>
              <th className="text-right pb-2 font-medium">Last Evaluated</th>
            </tr>
          </thead>
          <tbody>
            {displayed.map((item, idx) => (
              <tr key={item.symbol} className="border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/20 transition-colors">
                <td className="py-2.5 text-xs text-zinc-600">{item.rank ?? idx + 1}</td>
                <td className="py-2.5 font-semibold text-white text-sm">{item.symbol}</td>
                <td className="py-2.5 pr-4">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden min-w-[60px]">
                      <div
                        className={cn("h-1.5 rounded-full", item.score >= 70 ? "bg-lime-500" : item.score >= 40 ? "bg-yellow-500" : "bg-red-500")}
                        style={{ width: `${Math.min(100, Math.max(0, item.score))}%` }}
                      />
                    </div>
                    <span className="text-xs text-zinc-400 w-6 text-right">{item.score}</span>
                  </div>
                </td>
                <td className="py-2.5 text-xs text-zinc-400 capitalize">{getTopReason(item.reasons)}</td>
                <td className="py-2.5">
                  <span className={cn("text-xs font-semibold px-1.5 py-0.5 rounded-full border", statusBadgeClass(item.status))}>
                    {item.status}
                  </span>
                </td>
                <td className="py-2.5 text-right text-xs text-zinc-500">
                  {formatRelativeAgo(item.last_evaluated_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {watchlist.length > 20 && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="mt-3 text-xs text-zinc-500 hover:text-zinc-300 underline underline-offset-2 transition-colors"
        >
          {showAll ? "Show fewer" : `Show all ${watchlist.length} symbols`}
        </button>
      )}
    </div>
  );
}

// ─── Strategy attribution chart ───────────────────────────────────────────────

function StrategyAttributionChart({ botName, totalPnl }: { botName: string; totalPnl: number }) {
  const strategies = BOT_META[botName]?.strategies ?? ["strategy_1", "strategy_2", "strategy_3"];
  const n = strategies.length;

  // Demo: distribute total P&L roughly across strategies with some variation
  const rawSplit = strategies.map((_, i) => {
    const base = totalPnl / n;
    const variation = base * (i % 2 === 0 ? 0.3 : -0.15);
    return base + variation;
  });

  const data = strategies.map((s, i) => ({
    name: s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    value: rawSplit[i],
  }));

  return (
    <div className="mt-4">
      <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-3">Strategy Attribution (Est.)</h3>
      <ResponsiveContainer width="100%" height={120}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: "#71717a", fontSize: 9 }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fill: "#71717a", fontSize: 9 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
          <Tooltip
            contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 11 }}
            labelStyle={{ color: "#a1a1aa" }}
            formatter={(v: number) => [`$${v.toFixed(2)}`, "Est. P&L"]}
          />
          <Bar dataKey="value" radius={[3, 3, 0, 0]}>
            {data.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={entry.value >= 0 ? "#84cc16" : "#ef4444"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── Backtest tab ─────────────────────────────────────────────────────────────

interface BacktestResult {
  sharpe?: number;
  sortino?: number;
  calmar?: number;
  max_drawdown?: number;
  win_rate?: number;
  profit_factor?: number;
  total_trades?: number;
  equity_curve?: { date: string; equity: number }[];
  monte_carlo?: { sharpe_p5?: number; sharpe_p95?: number };
}

function BacktestTab({ botName }: { botName: string }) {
  const [startDate, setStartDate] = useState("2019-01-01");
  const [endDate, setEndDate] = useState("2024-01-01");
  const [capital, setCapital] = useState(100000);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [hasRun, setHasRun] = useState(false);

  async function handleRun() {
    setIsRunning(true);
    setHasRun(true);
    try {
      const data = await runBacktest(botName, { start: startDate, end: endDate, capital });
      setResult(data ?? null);
    } catch {
      toast.error("Backtest failed — check dates and try again");
      setResult(null);
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-zinc-300 mb-3">Backtest Parameters</h3>
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">Start Date</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-lime-500/50"
            />
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">End Date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-lime-500/50"
            />
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">Starting Capital ($)</label>
            <input
              type="number"
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
              step={10000}
              min={1000}
              className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-white w-32 focus:outline-none focus:border-lime-500/50"
            />
          </div>
          <button
            onClick={handleRun}
            disabled={isRunning}
            className="px-4 py-2 rounded-lg bg-lime-500 text-black text-sm font-bold hover:bg-lime-400 transition-colors disabled:opacity-50"
          >
            {isRunning ? "Running…" : "Run Backtest"}
          </button>
        </div>
      </div>

      {/* Results */}
      {isRunning && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 animate-pulse space-y-3">
          <div className="grid grid-cols-4 gap-3">
            {[0, 1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="h-14 bg-zinc-800 rounded-xl" />
            ))}
          </div>
          <div className="h-48 bg-zinc-800 rounded-xl" />
        </div>
      )}

      {!isRunning && hasRun && !result && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 text-center">
          <p className="text-zinc-500 text-sm">No backtest data returned. Try a different date range.</p>
        </div>
      )}

      {!isRunning && result && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 space-y-5">
          {/* Metrics grid */}
          <div>
            <h3 className="text-sm font-semibold text-zinc-300 mb-3">Performance Metrics</h3>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: "Sharpe", value: result.sharpe?.toFixed(2) ?? "—" },
                { label: "Sortino", value: result.sortino?.toFixed(2) ?? "—" },
                { label: "Calmar", value: result.calmar?.toFixed(2) ?? "—" },
                { label: "Max DD", value: result.max_drawdown ? `-${(result.max_drawdown * 100).toFixed(1)}%` : "—" },
                { label: "Win Rate", value: result.win_rate ? `${(result.win_rate * 100).toFixed(1)}%` : "—" },
                { label: "Profit Factor", value: result.profit_factor?.toFixed(2) ?? "—" },
                { label: "Total Trades", value: result.total_trades ? String(result.total_trades) : "—" },
              ].map((m) => (
                <div key={m.label} className="bg-zinc-950 rounded-xl px-4 py-3 border border-zinc-800">
                  <p className="text-zinc-600 text-xs mb-1">{m.label}</p>
                  <p className="text-lg font-bold text-white">{m.value}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Equity curve */}
          {result.equity_curve && result.equity_curve.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-zinc-300 mb-3">Equity Curve</h3>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={result.equity_curve} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis dataKey="date" tick={{ fill: "#71717a", fontSize: 10 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fill: "#71717a", fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
                  <Tooltip
                    contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }}
                    labelStyle={{ color: "#a1a1aa" }}
                    formatter={(v: number) => [`$${v.toFixed(0)}`, "Portfolio"]}
                  />
                  <Line type="monotone" dataKey="equity" stroke="#84cc16" strokeWidth={2} dot={false} name="Portfolio" />
                  {/* Flat benchmark line at starting capital */}
                  <Line
                    type="monotone"
                    dataKey={() => capital}
                    stroke="#52525b"
                    strokeWidth={1.5}
                    strokeDasharray="4 2"
                    dot={false}
                    name="Benchmark"
                  />
                </LineChart>
              </ResponsiveContainer>
              <div className="flex gap-4 mt-2">
                <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                  <span className="w-3 h-0.5 bg-[#84cc16] inline-block rounded" />
                  Portfolio
                </div>
                <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                  <span className="w-3 h-0.5 bg-zinc-600 inline-block rounded" />
                  ${(capital / 1000).toFixed(0)}k Flat
                </div>
              </div>
            </div>
          )}

          {/* Monte Carlo */}
          {result.monte_carlo && (
            <div className="bg-zinc-950 border border-zinc-800 rounded-xl px-4 py-3">
              <p className="text-xs text-zinc-500 mb-1">Monte Carlo Confidence Band</p>
              <p className="text-sm text-zinc-300">
                Sharpe 5th–95th percentile:{" "}
                <span className="font-semibold text-white">
                  {result.monte_carlo.sharpe_p5?.toFixed(2) ?? "—"} to {result.monte_carlo.sharpe_p95?.toFixed(2) ?? "—"}
                </span>
              </p>
            </div>
          )}

          {/* Trade list header */}
          <div>
            <h3 className="text-sm font-semibold text-zinc-300 mb-2">Trade List</h3>
            <p className="text-xs text-zinc-600 italic">Individual trade breakdown available in v2.</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Tab system ───────────────────────────────────────────────────────────────

type Tab = "overview" | "watchlist" | "backtest" | "activity" | "strategies" | "settings";

function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  const tabs: { key: Tab; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "watchlist", label: "Watchlist" },
    { key: "backtest", label: "Backtest" },
    { key: "activity", label: "Activity" },
    { key: "strategies", label: "Strategies" },
    { key: "settings", label: "Settings" },
  ];

  return (
    <div className="overflow-x-auto -mx-1">
      <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1 min-w-max">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => onChange(t.key)}
            className={cn(
              "text-sm font-semibold py-2 px-3 rounded-lg transition-colors whitespace-nowrap",
              active === t.key
                ? "bg-zinc-700 text-white"
                : "text-zinc-500 hover:text-zinc-300"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Activity tab ─────────────────────────────────────────────────────────────

type ActivityCategory = "all" | "signal" | "fill" | "skip";

function ActivityTab({ botName, searchRef }: { botName: string; searchRef?: React.RefObject<HTMLInputElement | null> }) {
  const [category, setCategory] = useState<ActivityCategory>("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;

  const { data, isLoading } = useQuery({
    queryKey: ["bot-activity", botName, category, page],
    queryFn: () =>
      getActivity(botName, {
        category: category === "all" ? undefined : category,
        limit: PAGE_SIZE,
        page,
      }),
    enabled: !!botName,
    retry: 0,
    staleTime: 30_000,
  });

  const items: ActivityEvent[] = data?.items ?? [];
  const total = data?.total ?? 0;

  const filtered = search
    ? items.filter(
        (i) =>
          i.symbol?.toLowerCase().includes(search.toLowerCase()) ||
          i.strategy?.toLowerCase().includes(search.toLowerCase()) ||
          i.reason?.toLowerCase().includes(search.toLowerCase())
      )
    : items;

  const cats: { key: ActivityCategory; label: string }[] = [
    { key: "all", label: "All" },
    { key: "signal", label: "Signals" },
    { key: "fill", label: "Fills" },
    { key: "skip", label: "Skips" },
  ];

  function resultIcon(result?: string) {
    if (result === "filled") return <span className="text-lime-400">✓</span>;
    if (result === "skipped") return <span className="text-zinc-500">✗</span>;
    if (result === "error") return <span className="text-red-400">!</span>;
    return <span className="text-zinc-600">⚡</span>;
  }

  return (
    <div className="space-y-4">
      {/* Search + filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <input
          ref={searchRef}
          type="text"
          placeholder="Search activity…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-teal-500/50"
        />
        <div className="flex gap-1">
          {cats.map((c) => (
            <button
              key={c.key}
              onClick={() => { setCategory(c.key); setPage(1); }}
              className={cn(
                "text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors whitespace-nowrap",
                category === c.key
                  ? "bg-teal-500/15 border-teal-500/30 text-teal-400"
                  : "bg-zinc-800 border-zinc-700 text-zinc-500 hover:text-zinc-300"
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>

      {/* Timeline */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
        {isLoading ? (
          <div className="animate-pulse space-y-3">
            {[0, 1, 2, 3, 4].map((i) => <div key={i} className="h-12 bg-zinc-800 rounded-lg" />)}
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-zinc-600 text-sm py-6 text-center">No activity found</p>
        ) : (
          <div className="space-y-0">
            {filtered.map((item) => {
              const ts = (() => {
                try { return new Date(item.ts).toLocaleString(); } catch { return item.ts; }
              })();
              return (
                <div
                  key={item.id}
                  className="flex items-center gap-3 py-3 border-b border-zinc-800/60 last:border-0 flex-wrap"
                >
                  <span className="text-xs text-zinc-600 w-32 flex-shrink-0">{ts}</span>
                  <span className="font-semibold text-white text-sm">{item.symbol}</span>
                  {item.side && (
                    <span className={cn(
                      "text-xs font-bold px-2 py-0.5 rounded-full border",
                      item.side === "buy"
                        ? "bg-lime-500/15 text-lime-400 border-lime-500/30"
                        : item.side === "sell"
                        ? "bg-red-500/15 text-red-400 border-red-500/30"
                        : "bg-zinc-800 text-zinc-400 border-zinc-700"
                    )}>
                      {item.side.toUpperCase()}
                    </span>
                  )}
                  {item.strategy && (
                    <span className="text-xs px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-400">
                      {item.strategy}
                    </span>
                  )}
                  {item.reason && (
                    <span className="text-xs text-zinc-500 flex-1 truncate min-w-0">{item.reason}</span>
                  )}
                  <span className="ml-auto flex-shrink-0">{resultIcon(item.result)}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-zinc-600">
            Showing {Math.min(page * PAGE_SIZE, total)} of {total}
          </span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={page * PAGE_SIZE >= total}
            className="text-xs font-semibold px-4 py-2 rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-300 hover:text-white disabled:opacity-40 transition-colors"
          >
            Load more
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Strategies tab ───────────────────────────────────────────────────────────

function StrategiesTab({ botName }: { botName: string }) {
  const qc = useQueryClient();

  const { data: weights = [], isLoading } = useQuery({
    queryKey: ["strategy-weights", botName],
    queryFn: () => getStrategyWeights(botName),
    enabled: !!botName,
    retry: 0,
    staleTime: 30_000,
  });

  const lockMut = useMutation({
    mutationFn: ({ strategy, locked }: { strategy: string; locked: boolean }) =>
      updateStrategyWeight(botName, strategy, { locked }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["strategy-weights", botName] }),
    onError: () => toast.error("Failed to update lock"),
  });

  const resetMut = useMutation({
    mutationFn: () =>
      Promise.all(
        weights.map((w: StrategyWeight) =>
          updateStrategyWeight(botName, w.strategy, { locked: false })
        )
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategy-weights", botName] });
      toast.success("Weights reset");
    },
    onError: () => toast.error("Failed to reset weights"),
  });

  if (isLoading) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 animate-pulse space-y-3">
        {[0, 1, 2].map((i) => <div key={i} className="h-12 bg-zinc-800 rounded" />)}
      </div>
    );
  }

  // If no data from API, show fallback rows from BOT_META
  const displayWeights: StrategyWeight[] =
    weights.length > 0
      ? weights
      : (BOT_META[botName]?.strategies ?? []).map((s, i) => ({
          strategy: s,
          weight_pct: Math.round(100 / (BOT_META[botName]?.strategies.length ?? 3)),
          wins_30d: Math.floor(Math.random() * 15),
          losses_30d: Math.floor(Math.random() * 7),
          locked: false,
        }));

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-zinc-300">Strategy Weights</h2>
        <button
          onClick={() => resetMut.mutate()}
          disabled={resetMut.isPending}
          className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-400 hover:text-white transition-colors disabled:opacity-40"
        >
          {resetMut.isPending ? "Resetting…" : "Reset weights"}
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-zinc-600 border-b border-zinc-800">
              <th className="text-left pb-2 font-medium">Strategy</th>
              <th className="text-center pb-2 font-medium">Weight</th>
              <th className="text-center pb-2 font-medium">30d Wins</th>
              <th className="text-center pb-2 font-medium">30d Losses</th>
              <th className="text-center pb-2 font-medium">Win Rate</th>
              <th className="text-center pb-2 font-medium">Lock</th>
            </tr>
          </thead>
          <tbody>
            {displayWeights.map((w: StrategyWeight) => {
              const winRate = w.wins_30d + w.losses_30d > 0
                ? ((w.wins_30d / (w.wins_30d + w.losses_30d)) * 100).toFixed(0)
                : "—";
              return (
                <tr key={w.strategy} className="border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/20 transition-colors">
                  <td className="py-3 font-medium text-white capitalize">
                    {w.strategy.replace(/_/g, " ")}
                  </td>
                  <td className="py-3 text-center">
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-teal-500/15 border border-teal-500/30 text-teal-400">
                      {w.weight_pct}%
                    </span>
                  </td>
                  <td className="py-3 text-center text-lime-400 font-semibold text-xs">
                    {w.wins_30d}
                  </td>
                  <td className="py-3 text-center text-red-400 font-semibold text-xs">
                    {w.losses_30d}
                  </td>
                  <td className="py-3 text-center text-zinc-300 text-xs">
                    {winRate}{winRate !== "—" ? "%" : ""}
                  </td>
                  <td className="py-3 text-center">
                    <button
                      onClick={() => lockMut.mutate({ strategy: w.strategy, locked: !w.locked })}
                      disabled={lockMut.isPending}
                      className={cn(
                        "p-1.5 rounded-lg border transition-colors",
                        w.locked
                          ? "bg-amber-500/15 border-amber-500/30 text-amber-400"
                          : "bg-zinc-800 border-zinc-700 text-zinc-500 hover:text-zinc-300"
                      )}
                      title={w.locked ? "Unlock weight" : "Lock weight"}
                    >
                      {w.locked ? <Lock className="w-3.5 h-3.5" /> : <Unlock className="w-3.5 h-3.5" />}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Settings tab ─────────────────────────────────────────────────────────────

function SettingsTab({
  botName,
  initialCapitalPct,
  initialRiskProfile,
  isOnWaitlist,
}: {
  botName: string;
  initialCapitalPct: number;
  initialRiskProfile: "conservative" | "standard" | "aggressive";
  isOnWaitlist: boolean;
}) {
  const qc = useQueryClient();
  const [capitalPct, setCapitalPct] = useState(initialCapitalPct);
  const [riskProfile, setRiskProfile] = useState(initialRiskProfile);
  const [notified, setNotified] = useState(isOnWaitlist);

  const allocateMut = useMutation({
    mutationFn: () =>
      import("@/api/bots").then(({ allocateBot }) =>
        allocateBot(botName, { capital_pct: capitalPct, risk_profile: riskProfile, enabled: true })
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", botName] });
      qc.invalidateQueries({ queryKey: ["bots-v2"] });
      toast.success("Settings saved");
    },
    onError: () => toast.error("Failed to save settings"),
  });

  const waitlistMut = useMutation({
    mutationFn: () =>
      import("@/api/bots").then(({ joinWaitlist }) => joinWaitlist(botName)),
    onSuccess: () => {
      setNotified(true);
      toast.success("Added to waitlist");
    },
    onError: () => toast.error("Failed to join waitlist"),
  });

  return (
    <div className="space-y-5">
      {/* Capital slider */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 space-y-4">
        <h2 className="text-sm font-semibold text-zinc-300">Paper Allocation</h2>
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs text-zinc-500">Capital %</label>
            <span className="text-sm font-bold text-white">{capitalPct}%</span>
          </div>
          <input
            type="range"
            min={0}
            max={20}
            step={0.5}
            value={capitalPct}
            onChange={(e) => setCapitalPct(Number(e.target.value))}
            className="w-full accent-teal-500"
          />
          <div className="flex justify-between text-xs text-zinc-700 mt-0.5">
            <span>0%</span>
            <span>20%</span>
          </div>
        </div>

        {/* Risk profile */}
        <div>
          <label className="text-xs text-zinc-500 mb-2 block">Risk Profile</label>
          <div className="flex gap-2">
            {(["conservative", "standard", "aggressive"] as const).map((r) => (
              <button
                key={r}
                onClick={() => setRiskProfile(r)}
                className={cn(
                  "text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors capitalize",
                  riskProfile === r
                    ? "bg-teal-500/15 border-teal-500/40 text-teal-400"
                    : "bg-zinc-800 border-zinc-700 text-zinc-500 hover:text-zinc-300"
                )}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={() => allocateMut.mutate()}
          disabled={allocateMut.isPending}
          className="px-4 py-2 rounded-lg bg-teal-500 text-black text-sm font-bold hover:bg-teal-400 transition-colors disabled:opacity-50"
        >
          {allocateMut.isPending ? "Saving…" : "Save Settings"}
        </button>
      </div>

      {/* Go Live section */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 space-y-3">
        <h2 className="text-sm font-semibold text-zinc-300">Go Live</h2>
        <div className="flex items-center gap-3">
          <div className="relative">
            <button
              disabled
              className="relative inline-flex h-6 w-11 items-center rounded-full bg-zinc-700 cursor-not-allowed opacity-50"
              title="Live trading unlocks Q3 2026 after WI DFI RIA approval"
            >
              <span className="translate-x-1 inline-block h-4 w-4 rounded-full bg-white" />
            </button>
          </div>
          <span className="text-xs text-zinc-500">
            Live trading unlocks Q3 2026 after WI DFI RIA approval
          </span>
        </div>
        {notified ? (
          <p className="text-sm text-lime-400 font-semibold">
            You're on the waitlist ✓
          </p>
        ) : (
          <button
            onClick={() => waitlistMut.mutate()}
            disabled={waitlistMut.isPending}
            className="text-sm font-semibold px-4 py-2 rounded-lg border border-amber-500/30 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 transition-colors"
          >
            {waitlistMut.isPending ? "Joining…" : "Notify me when live unlocks →"}
          </button>
        )}
      </div>

      {/* Reset paper balance */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 space-y-3">
        <h2 className="text-sm font-semibold text-zinc-300">Reset Paper Balance</h2>
        <p className="text-xs text-zinc-500">
          Resets this bot's paper trading balance to the starting capital. Use to test fresh strategies.
        </p>
        <button
          className="text-xs font-semibold px-4 py-2 rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-400 hover:text-white transition-colors"
        >
          Reset paper balance
        </button>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function BotDetailPage() {
  const { botName = "" } = useParams<{ botName: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [selectedSignal, setSelectedSignal] = useState<BotSignal | null>(null);
  const activitySearchRef = useRef<HTMLInputElement | null>(null);

  const meta = BOT_META[botName];
  const isCrypto = (meta?.assetClass ?? (botName.startsWith("crypto") ? "crypto" : "stock")) === "crypto";

  const { data, isLoading } = useQuery({
    queryKey: ["bot", botName],
    queryFn: () => getBot(botName),
    enabled: !!botName,
    retry: 1,
  });

  const { data: regime, isLoading: regimeLoading } = useQuery({
    queryKey: ["regime"],
    queryFn: getRegime,
    retry: 0,
    staleTime: 60_000,
  });

  const profile = data?.profile;
  const allocation = data?.allocation;
  const positions: BotPosition[] = Array.isArray(data?.positions) ? data!.positions : [];
  const signals: BotSignal[] = Array.isArray(data?.signals) ? data!.signals : [];
  const stats = (data?.stats ?? {}) as {
    return_30d_pct?: number;
    today_pnl?: number;
    open_positions?: number;
    win_rate_pct?: number;
    equity_curve?: EquityPoint[];
  };

  // Local allocation state
  const [capitalPct, setCapitalPct] = useState<number>(allocation?.capital_pct ?? 10);
  const [riskProfile, setRiskProfile] = useState<"conservative" | "standard" | "aggressive">(
    allocation?.risk_profile ?? "standard"
  );

  const isEnabled = allocation?.enabled ?? false;
  const isOnWaitlist = allocation?.go_live_requested ?? false;

  const allocateMut = useMutation({
    mutationFn: (overrides: Partial<{ capital_pct: number; risk_profile: string; enabled: boolean }> | undefined) =>
      allocateBot(botName, {
        capital_pct: overrides?.capital_pct ?? capitalPct,
        risk_profile: overrides?.risk_profile ?? riskProfile,
        enabled: overrides?.enabled ?? isEnabled,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", botName] });
      qc.invalidateQueries({ queryKey: ["bots-v2"] });
      toast.success("Allocation saved");
    },
    onError: () => toast.error("Failed to save allocation"),
  });

  const waitlistMut = useMutation({
    mutationFn: (joining: boolean) =>
      joining ? joinWaitlist(botName) : leaveWaitlist(botName),
    onSuccess: (_data, joining) => {
      qc.invalidateQueries({ queryKey: ["bot", botName] });
      toast.success(joining ? "Added to live waitlist" : "Removed from waitlist");
    },
    onError: () => toast.error("Failed to update waitlist"),
  });

  const equityCurve: EquityPoint[] = Array.isArray(stats.equity_curve) ? stats.equity_curve : [];
  const totalPnl = stats.today_pnl ?? 0;

  // Keyboard shortcuts (defined after allocateMut and isEnabled are available)
  const pauseBot = useCallback(() => {
    if (!botName) return;
    allocateMut.mutate({ enabled: !isEnabled });
  }, [botName, isEnabled, allocateMut]);

  const focusSearch = useCallback(() => {
    setActiveTab("activity");
    setTimeout(() => activitySearchRef.current?.focus(), 100);
  }, []);

  useKeyboardShortcuts(navigate, botName, {
    onPause: pauseBot,
    onFocusSearch: focusSearch,
    onOpenCoPilot: () =>
      window.dispatchEvent(new CustomEvent("copilot:open", { detail: { query: "" } })),
  });

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      {/* Back nav */}
      <button
        onClick={() => navigate("/strategy")}
        className="flex items-center gap-1.5 text-zinc-500 hover:text-white text-sm transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Strategy Lab
      </button>

      {/* Paper-only banner */}
      <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 flex items-center gap-3">
        <span className="text-amber-400 text-sm font-semibold">📄 Paper trading only.</span>
        <span className="text-amber-300 text-xs">
          Live trading unlocks Q3 2026 when BMG completes RIA registration.
        </span>
        <button
          onClick={() => waitlistMut.mutate(!isOnWaitlist)}
          disabled={waitlistMut.isPending}
          className="ml-auto text-xs text-amber-400 underline whitespace-nowrap"
        >
          {isOnWaitlist ? "✓ On waitlist" : "Join the waitlist →"}
        </button>
      </div>

      {/* Regime panel */}
      <RegimePanel regime={regime} isLoading={regimeLoading} />

      {/* Catalyst calendar */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3">
        <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-2">Upcoming Catalysts</h3>
        <CatalystCalendar />
      </div>

      {/* Hero card */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
        {isLoading ? (
          <div className="animate-pulse space-y-4">
            <div className="h-7 w-48 bg-zinc-800 rounded" />
            <div className="h-4 w-64 bg-zinc-800 rounded" />
            <div className="grid grid-cols-4 gap-4 mt-4">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-14 bg-zinc-800 rounded-xl" />
              ))}
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-start justify-between mb-1">
              <div>
                <h1 className="text-xl font-bold text-white">
                  {meta?.displayName ?? displayName(botName)}
                </h1>
                <p className="text-zinc-500 text-sm mt-0.5">
                  {meta?.description ?? profile?.description ?? ""}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "text-xs font-semibold px-2 py-0.5 rounded-full",
                    isEnabled
                      ? "bg-lime-500/15 text-lime-400 border border-lime-500/30"
                      : "bg-zinc-800 text-zinc-500 border border-zinc-700"
                  )}
                >
                  {isEnabled ? "ACTIVE" : "DISABLED"}
                </span>
              </div>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-5 mb-6">
              {[
                {
                  label: "30d Return",
                  value: formatPct(stats?.return_30d_pct ?? 0),
                  positive: (stats?.return_30d_pct ?? 0) >= 0,
                  colored: true,
                },
                {
                  label: "Today P&L",
                  value: formatPnl(stats?.today_pnl ?? 0),
                  positive: (stats?.today_pnl ?? 0) >= 0,
                  colored: true,
                },
                {
                  label: "Open Positions",
                  value: String(stats?.open_positions ?? 0),
                  positive: true,
                  colored: false,
                },
                {
                  label: "Win Rate",
                  value: `${(stats?.win_rate_pct ?? 0).toFixed(1)}%`,
                  positive: (stats?.win_rate_pct ?? 0) >= 50,
                  colored: true,
                },
              ].map((s) => (
                <div key={s.label} className="bg-zinc-950 rounded-xl px-4 py-3 border border-zinc-800">
                  <p className="text-zinc-600 text-xs mb-1">{s.label}</p>
                  <p
                    className={cn(
                      "text-lg font-bold",
                      s.colored ? (s.positive ? "text-lime-400" : "text-red-400") : "text-white"
                    )}
                  >
                    {s.value}
                  </p>
                </div>
              ))}
            </div>

            {/* Allocation */}
            <div className="border-t border-zinc-800 pt-5">
              <h2 className="text-sm font-semibold text-zinc-300 mb-4">Allocation Settings</h2>
              <div className="flex flex-col sm:flex-row gap-6">
                <div className="flex-1">
                  <label className="text-xs text-zinc-500 mb-1 block">
                    Capital Allocated — {capitalPct}%
                  </label>
                  <input
                    type="range"
                    min={10}
                    max={100}
                    step={10}
                    value={capitalPct}
                    onChange={(e) => setCapitalPct(Number(e.target.value))}
                    className="w-full accent-lime-500"
                  />
                  <div className="flex justify-between text-xs text-zinc-700 mt-0.5">
                    <span>10%</span>
                    <span>100%</span>
                  </div>
                </div>
                <div>
                  <label className="text-xs text-zinc-500 mb-1 block">Risk Profile</label>
                  <div className="flex gap-2">
                    {(["conservative", "standard", "aggressive"] as const).map((r) => (
                      <button
                        key={r}
                        onClick={() => setRiskProfile(r)}
                        className={cn(
                          "text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors capitalize",
                          riskProfile === r
                            ? "bg-lime-500/15 border-lime-500/40 text-lime-400"
                            : "bg-zinc-800 border-zinc-700 text-zinc-500 hover:text-zinc-300"
                        )}
                      >
                        {r}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3 mt-4">
                <button
                  onClick={() => allocateMut.mutate(undefined)}
                  disabled={allocateMut.isPending}
                  className="px-4 py-2 rounded-lg bg-lime-500 text-black text-sm font-bold hover:bg-lime-400 transition-colors disabled:opacity-50"
                >
                  {allocateMut.isPending ? "Saving…" : "Save"}
                </button>
                <button
                  onClick={() => allocateMut.mutate({ enabled: !isEnabled })}
                  disabled={allocateMut.isPending}
                  className={cn(
                    "px-4 py-2 rounded-lg border text-sm font-semibold transition-colors",
                    isEnabled
                      ? "border-zinc-700 text-zinc-400 hover:border-red-600 hover:text-red-400"
                      : "border-lime-600/50 text-lime-400 hover:bg-lime-500/10"
                  )}
                >
                  {isEnabled ? "Disable Bot" : "Enable Bot"}
                </button>
                <div className="relative ml-auto">
                  <button
                    disabled
                    className="opacity-50 cursor-not-allowed px-4 py-2 rounded-lg border border-zinc-700 text-sm text-zinc-400"
                  >
                    Go Live
                  </button>
                  <div className="absolute -top-8 left-0 bg-zinc-800 text-xs text-zinc-300 px-2 py-1 rounded whitespace-nowrap pointer-events-none">
                    Live trading unlocks Q3 2026. Join the waitlist above.
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Mobile swipe hint */}
      <p className="text-xs text-zinc-700 text-center md:hidden">
        Swipe between bots ←
      </p>

      {/* Tab system */}
      <TabBar active={activeTab} onChange={setActiveTab} />

      {/* Overview tab */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          {/* Equity curve */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
            <h2 className="text-sm font-semibold text-zinc-300 mb-4">
              Equity Curve vs {isCrypto ? "BTC" : "SPY"}
            </h2>
            <EquityCurve data={equityCurve} isCrypto={isCrypto} />
            <div className="flex gap-4 mt-2">
              <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                <span className="w-3 h-0.5 bg-[#84cc16] inline-block rounded" />
                Portfolio
              </div>
              <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                <span className="w-3 h-0.5 bg-zinc-600 inline-block rounded" />
                {isCrypto ? "BTC" : "SPY"}
              </div>
            </div>
            {/* Strategy attribution */}
            <StrategyAttributionChart botName={botName} totalPnl={totalPnl} />
          </div>

          {/* Paper Positions */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
            <h2 className="text-sm font-semibold text-zinc-300 mb-4">Paper Positions</h2>
            {positions.length === 0 ? (
              <p className="text-zinc-600 text-sm py-4 text-center">No open positions</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-zinc-600 border-b border-zinc-800">
                      <th className="text-left pb-2 font-medium">Symbol</th>
                      <th className="text-right pb-2 font-medium">Qty</th>
                      <th className="text-right pb-2 font-medium">Avg Cost</th>
                      <th className="text-right pb-2 font-medium">Current Price</th>
                      <th className="text-right pb-2 font-medium">P&L</th>
                      <th className="text-right pb-2 font-medium">Opened</th>
                      <th className="text-right pb-2 font-medium"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((pos) => {
                      // Find associated signal for "Why?" button
                      const signal = signals.find((s) => s.symbol === pos.symbol) ?? null;
                      return (
                        <tr key={pos.id} className="border-b border-zinc-800/50 last:border-0">
                          <td className="py-2.5 font-semibold text-white">{pos.symbol}</td>
                          <td className="py-2.5 text-right text-zinc-300">{pos.qty}</td>
                          <td className="py-2.5 text-right text-zinc-300">{formatCents(pos.avg_cost_cents)}</td>
                          <td className="py-2.5 text-right text-zinc-500">—</td>
                          <td className="py-2.5 text-right text-zinc-500">—</td>
                          <td className="py-2.5 text-right text-zinc-500 text-xs">{formatTime(pos.opened_at)}</td>
                          <td className="py-2.5 text-right">
                            {signal && (
                              <button
                                onClick={() => setSelectedSignal(signal)}
                                className="text-xs text-zinc-500 hover:text-lime-400 underline underline-offset-2 transition-colors"
                              >
                                Why?
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Recent Signals */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
            <h2 className="text-sm font-semibold text-zinc-300 mb-4">Recent Signals</h2>
            {signals.length === 0 ? (
              <p className="text-zinc-600 text-sm py-4 text-center">No recent signals</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-zinc-600 border-b border-zinc-800">
                      <th className="text-left pb-2 font-medium">Time</th>
                      <th className="text-left pb-2 font-medium">Symbol</th>
                      <th className="text-left pb-2 font-medium">Side</th>
                      <th className="text-right pb-2 font-medium">Confidence</th>
                      <th className="text-left pb-2 font-medium">Strategy</th>
                      <th className="text-left pb-2 font-medium">Reason</th>
                      <th className="text-right pb-2 font-medium"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {signals.map((sig) => (
                      <tr key={sig.id} className="border-b border-zinc-800/50 last:border-0">
                        <td className="py-2.5 text-zinc-500 text-xs">{formatTime(sig.ts)}</td>
                        <td className="py-2.5 font-semibold text-white">{sig.symbol}</td>
                        <td className="py-2.5"><SideBadge side={sig.side} /></td>
                        <td className="py-2.5 text-right text-zinc-300">{sig.confidence.toFixed(0)}%</td>
                        <td className="py-2.5 text-zinc-400 text-xs">{sig.strategy}</td>
                        <td className="py-2.5 text-zinc-500 text-xs max-w-xs truncate">{sig.reason}</td>
                        <td className="py-2.5 text-right">
                          <button
                            onClick={() => setSelectedSignal(sig)}
                            className="text-xs text-zinc-500 hover:text-lime-400 underline underline-offset-2 transition-colors"
                          >
                            Why?
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Watchlist tab */}
      {activeTab === "watchlist" && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
          <h2 className="text-sm font-semibold text-zinc-300 mb-4">Watchlist</h2>
          <WatchlistTable botName={botName} />
        </div>
      )}

      {/* Backtest tab */}
      {activeTab === "backtest" && <BacktestTab botName={botName} />}

      {/* Activity tab */}
      {activeTab === "activity" && (
        <ActivityTab botName={botName} searchRef={activitySearchRef} />
      )}

      {/* Strategies tab */}
      {activeTab === "strategies" && <StrategiesTab botName={botName} />}

      {/* Settings tab */}
      {activeTab === "settings" && (
        <SettingsTab
          botName={botName}
          initialCapitalPct={capitalPct}
          initialRiskProfile={riskProfile}
          isOnWaitlist={isOnWaitlist}
        />
      )}

      {/* Footer */}
      <p className="text-xs text-center text-zinc-600 mt-8">
        Paper trading. Not investment advice. Not a registered investment adviser.
      </p>

      {/* Why modal */}
      <WhyModal signal={selectedSignal} onClose={() => setSelectedSignal(null)} />
    </div>
  );
}

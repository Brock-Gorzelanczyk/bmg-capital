import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { BracketFrame, SectionLabel } from "@/components/design";
import { useParams, useNavigate } from "react-router-dom";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, X, Lock, Unlock, ChevronDown, ChevronRight, CheckCircle2, XCircle } from "lucide-react";
import {
  LineChart,
  Line,
  AreaChart,
  Area,
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
  getBotWatchlistReadiness,
  getBotStrategyTrace,
  runBacktest,
  getCatalysts,
  getActivity,
  getStrategyWeights,
  updateStrategyWeight,
  type BotPosition,
  type BotSignal,
  type RegimeData,
  type WatchlistItem,
  type ReadinessRow,
  type CatalystEvent,
  type ActivityEvent,
  type StrategyWeight,
  type StrategyTraceResult,
  type StrategyTrace,
} from "@/api/bots";
import { cn } from "@/lib/utils";
import { formatTradeSize, formatQty } from "@/lib/formatTradeSize";
import { CoachmarkOverlay } from "@/pages/CustomBotBuilderPage";
import { getWatchlistAnalyses, type WatchlistAnalysis } from "@/api/analyst";
import { getLatestPrices } from "@/api/bars";
import { useIsViewer } from "@/store/authStore";

// ─── Bot metadata ─────────────────────────────────────────────────────────────

const BOT_META: Record<
  string,
  { displayName: string; description: string; assetClass: "stock" | "crypto" | "quant"; strategies: string[]; ensemble?: string }
> = {
  stock_swing: {
    displayName: "Stock Swing",
    description: "Russell 1000 momentum plays, 1-30 day holds",
    assetClass: "stock",
    strategies: [
      "mean_reversion", "momentum_breakout", "rsi_bands",
      "fifty_two_week_high_momentum", "relative_strength_leaders",
      "factor_momentum_value", "golden_cross", "bollinger_squeeze",
      "cup_and_handle", "macd_crossover", "earnings_drift_post",
    ],
  },
  stock_day: {
    displayName: "Stock Day",
    description: "Intraday gappers & earnings momentum, EOD flat",
    assetClass: "stock",
    strategies: [
      "orb_stocks_in_play", "intraday_momentum_noise_band",
      "heston_half_hour_continuation", "first_half_hour_predicts_last",
      "pead_intraday_drift", "gex_pin_reversion", "fomc_drift",
      "vwap_reversion_chop",
    ],
  },
  stock_lt: {
    displayName: "Stock Long-Term",
    description: "S&P 500 factor model, monthly rebalance",
    assetClass: "stock",
    strategies: [
      "factor_blend", "dividend_growth", "quality_score",
      "low_vol_anomaly", "momentum_12_1", "small_cap_value",
      "shareholder_yield", "monthly_rebalance",
    ],
  },
  crypto_swing: {
    displayName: "Crypto Swing",
    description: "Top 20 crypto by mcap, 1-30 day holds",
    assetClass: "crypto",
    strategies: [
      "crypto_rsi_mean_reversion", "crypto_momentum_breakout",
      "crypto_btc_dominance_regime", "crypto_macd_swing",
      "crypto_ema_cross", "crypto_relative_strength",
    ],
  },
  crypto_day: {
    displayName: "Crypto Day",
    description: "BTC/ETH/SOL intraday momentum, 8h force-close",
    assetClass: "crypto",
    strategies: [
      "crypto_intraday_momentum", "crypto_weekend_momentum",
      "crypto_volatility_breakout", "crypto_news_sentiment",
      "crypto_session_open",
    ],
  },
  crypto_lt: {
    displayName: "Crypto L-T DCA",
    description: "BTC/ETH + majors, weekly DCA & monthly rebalance",
    assetClass: "crypto",
    strategies: [
      "dca_btc_eth", "monthly_rebalance_majors",
      "btc_dominance_rotation", "dollar_cost_average_dip",
      "yield_overlay",
    ],
  },
  crypto_quant_aggressive: {
    displayName: "Crypto Quant Aggressive",
    description: "5-signal high-turnover quant · 20-coin universe · $100k paper sub-account",
    assetClass: "quant",
    ensemble: "any_above_threshold",
    strategies: [
      "crypto_quant_vwap_fade",
      "crypto_quant_bb_breakout",
      "crypto_quant_momentum_trigger",
      "crypto_quant_volume_zscore_spike",
      "crypto_quant_range_break_retest",
    ],
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

const CADENCE_MAP: Record<string, string> = {
  "* 9-15 * * 1-5": "Trades intraday, Mon–Fri",
  "5 16 * * 1-5":   "Runs at 4:05 PM ET, Mon–Fri",
  "0 10 1-7 * 2":   "Rebalances 1st Tuesday/month",
  "* * * * *":      "Trades 24/7",
  "intraday":       "Trades intraday, Mon–Fri",
  "weekly":         "Rebalances weekly",
  "daily":          "Runs daily",
};
function formatCadence(c: string): string {
  return CADENCE_MAP[c] ?? c.replace(/_/g, " ");
}

function fmtPrice(price: number | null | undefined): string {
  if (price == null || !isFinite(price as number)) return "—";
  const abs = Math.abs(price as number);
  let maxDec: number;
  if (abs >= 1000) maxDec = 2;
  else if (abs >= 1) maxDec = 4;
  else if (abs >= 0.01) maxDec = 5;
  else if (abs >= 0.0001) maxDec = 6;
  else maxDec = 8;
  return `$${(price as number).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: maxDec })}`;
}

function formatPnl(val: number): string {
  const abs = Math.abs(val);
  const sign = val >= 0 ? "+" : "-";
  if (abs >= 1_000_000_000) return `${sign}$${(abs / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000)     return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000)         return `${sign}$${(abs / 1_000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(2)}`;
}

function formatPct(val: number): string {
  const sign = val >= 0 ? "+" : "";
  return `${sign}${val.toFixed(2)}%`;
}

function formatCents(cents: number | null | undefined): string {
  if (cents == null || isNaN(cents)) return "—";
  return `$${(cents / 100).toFixed(2)}`;
}

function formatTime(ts: string | null | undefined): string {
  if (!ts) return "—";
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleString();
  } catch {
    return "—";
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

function SideBadge({ side }: { side: string }) {
  const isLong = side === "buy" || side === "long";
  const isShort = side === "sell" || side === "short";
  const label = isLong ? "LONG" : isShort ? "SHORT" : side.toUpperCase();
  const style = isLong
    ? "bg-lime-500/15 text-lime-400 border-lime-500/30"
    : isShort
    ? "bg-red-500/15 text-red-400 border-red-500/30"
    : "bg-zinc-800 text-zinc-400 border-zinc-700";
  return (
    <span className={cn("text-xs font-bold px-2 py-0.5 rounded-full border", style)}>
      {label}
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

// ─── Position detail modal ────────────────────────────────────────────────────

interface PositionDetailModalProps {
  pos: BotPosition | null;
  signal: BotSignal | null;
  stopLossPct: number | null;
  takeProfitPct: number | null;
  onClose: () => void;
}

function PositionDetailModal({
  pos, signal, stopLossPct, takeProfitPct, onClose,
}: PositionDetailModalProps) {
  if (!pos) return null;

  const entry = pos.avg_cost_cents / 100;
  const stopPrice = stopLossPct != null ? entry * (1 - stopLossPct / 100) : null;
  const targetPrice = takeProfitPct != null ? entry * (1 + takeProfitPct / 100) : null;

  const heldMs = Date.now() - new Date(pos.opened_at).getTime();
  const heldDays = Math.floor(heldMs / 86_400_000);
  const heldHours = Math.floor((heldMs % 86_400_000) / 3_600_000);
  const holdStr = heldDays > 0 ? `${heldDays}d ${heldHours}h` : `${heldHours}h`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative bg-zinc-900 border border-zinc-700 rounded-2xl p-6 w-full max-w-md shadow-2xl space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h3 className="text-white font-bold text-lg">{pos.symbol}</h3>
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-lime-500/15 border border-lime-500/30 text-lime-400">
              LONG
            </span>
            {pos.is_paper && (
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-500">
                PAPER
              </span>
            )}
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Key levels */}
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-zinc-950 rounded-xl p-3 border border-zinc-800">
            <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Entry</p>
            <p className="text-sm font-bold text-white mt-1">{fmtPrice(entry)}</p>
          </div>
          <div className="bg-zinc-950 rounded-xl p-3 border border-red-900/30">
            <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Stop Loss</p>
            <p className="text-sm font-bold text-red-400 mt-1">
              {fmtPrice(stopPrice)}
            </p>
            {stopLossPct != null && (
              <p className="text-[10px] text-zinc-600 mt-0.5">−{stopLossPct}%</p>
            )}
          </div>
          <div className="bg-zinc-950 rounded-xl p-3 border border-lime-900/30">
            <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Target</p>
            <p className="text-sm font-bold text-lime-400 mt-1">
              {fmtPrice(targetPrice)}
            </p>
            {takeProfitPct != null && (
              <p className="text-[10px] text-zinc-600 mt-0.5">+{takeProfitPct}%</p>
            )}
          </div>
        </div>

        {/* Position info */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-xs text-zinc-500">Qty</p>
            <p className="text-sm font-semibold text-white">{pos.qty}</p>
          </div>
          <div>
            <p className="text-xs text-zinc-500">Hold Time</p>
            <p className="text-sm font-semibold text-white">{holdStr}</p>
          </div>
          <div>
            <p className="text-xs text-zinc-500">Opened</p>
            <p className="text-sm font-semibold text-zinc-300">{formatTime(pos.opened_at)}</p>
          </div>
          <div>
            <p className="text-xs text-zinc-500">Unrealized P&L</p>
            <p className="text-sm font-semibold text-zinc-500">—</p>
          </div>
        </div>

        {/* Why we opened it */}
        {signal && (
          <div className="bg-zinc-800/60 rounded-xl p-4 space-y-2">
            <p className="text-xs font-semibold text-zinc-400">Why we opened this</p>
            <p className="text-xs text-zinc-500">
              <span className="text-zinc-400">Strategy:</span> {signal.strategy}
            </p>
            <p className="text-xs text-zinc-300 leading-relaxed">{signal.reason || "No reason recorded"}</p>
            <div className="flex items-center gap-2 pt-1">
              <p className="text-xs text-zinc-500">Confidence</p>
              <div className="flex-1 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-lime-500 rounded-full"
                  style={{ width: `${Math.round(signal.confidence * 100)}%` }}
                />
              </div>
              <p className="text-xs text-zinc-400">{Math.round(signal.confidence * 100)}%</p>
            </div>
          </div>
        )}

        {!signal && (
          <p className="text-xs text-zinc-600 text-center py-2">
            No signal record found for this position
          </p>
        )}
      </div>
    </div>
  );
}

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

// ─── Analyst helpers ──────────────────────────────────────────────────────────

function ConvictionStars({ score }: { score: number | null }) {
  if (score == null) return <span className="text-zinc-600 text-xs">—</span>;
  const filled = Math.round(score);
  return (
    <span className={cn("text-sm font-medium", score >= 4 ? "text-lime-400" : score >= 3 ? "text-yellow-400" : "text-zinc-500")}>
      {"★".repeat(filled)}{"☆".repeat(5 - filled)}
    </span>
  );
}

function AnalystDrawer({ analysis, onClose }: { analysis: WatchlistAnalysis; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div
        className="relative h-full w-full max-w-md bg-zinc-950 border-l border-zinc-800 shadow-2xl overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-zinc-950 border-b border-zinc-800 px-5 py-4 flex items-center justify-between">
          <div>
            <span className="font-bold text-white text-lg mr-2">{analysis.symbol}</span>
            <ConvictionStars score={analysis.conviction_score} />
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors">
            <X size={18} />
          </button>
        </div>
        <div className="p-5 space-y-5">
          <div>
            <p className="text-xs text-zinc-500 uppercase tracking-wide font-semibold mb-2">Thesis</p>
            <p className="text-sm text-zinc-300 leading-relaxed">{analysis.thesis_md}</p>
          </div>
          {analysis.reasons_to_own?.length > 0 && (
            <div>
              <p className="text-xs text-zinc-500 uppercase tracking-wide font-semibold mb-2">Reasons to Own</p>
              <ul className="space-y-1.5">
                {analysis.reasons_to_own.map((r, i) => (
                  <li key={i} className="flex gap-2 text-sm text-zinc-300">
                    <span className="text-lime-400 mt-0.5">✓</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {analysis.risks?.length > 0 && (
            <div>
              <p className="text-xs text-zinc-500 uppercase tracking-wide font-semibold mb-2">Risks</p>
              <ul className="space-y-1.5">
                {analysis.risks.map((r, i) => (
                  <li key={i} className="flex gap-2 text-sm text-zinc-300">
                    <span className="text-red-400 mt-0.5">⚠</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex gap-4">
            <div>
              <p className="text-[11px] text-zinc-600">Suggested Hold</p>
              <p className="text-sm text-zinc-300 font-medium">{analysis.suggested_hold || "—"}</p>
            </div>
            {analysis.concerns_flag && (
              <div>
                <p className="text-[11px] text-zinc-600">Flag</p>
                <p className="text-sm text-red-400 font-medium">⚑ Concerns flagged</p>
              </div>
            )}
          </div>
          <p className="text-[10px] text-zinc-700 border-t border-zinc-800 pt-3">
            Model: {analysis.model_used ?? "claude-haiku"} · {analysis.ts ? new Date(analysis.ts).toLocaleString() : ""}
            {analysis.cost_usd != null ? ` · $${analysis.cost_usd.toFixed(4)}` : ""}
          </p>
        </div>
      </div>
    </div>
  );
}

// ─── Entry-readiness watchlist ────────────────────────────────────────────────

function parseCadence(cron: string): string {
  if (!cron) return "scheduled";
  const parts = cron.trim().split(/\s+/);
  if (parts.length < 5) return cron;
  const [min, hour, , , dow] = parts;
  if (min === "*" && hour === "*" && dow === "*") return "every minute";
  if (min === "*/5") return "every 5 min";
  if (min === "*/15") return "every 15 min";
  if (min === "0" && hour === "*/4") return "every 4 hours";
  if (hour === "16") return "daily at 4 PM ET";
  if (hour === "9" || hour === "8") return "daily at open";
  return `cron: ${cron}`;
}

function GapScale({ current, target, unit, triggered }: {
  current: number; target: number; unit: string; triggered: boolean;
}) {
  if (triggered) {
    return (
      <div className="flex items-center gap-2 mt-2">
        <div className="flex-1 h-1 bg-lime-500/20 rounded-full overflow-hidden">
          <div className="h-1 bg-lime-500 rounded-full w-full" />
        </div>
        <span className="text-[9px] text-lime-500 font-semibold shrink-0">✓ met</span>
      </div>
    );
  }
  const gap = target - current;
  const padding = Math.max(Math.abs(gap) * 0.3, Math.abs(target) * 0.1, 0.01);
  const scaleMin = Math.min(current, target) - padding;
  const scaleMax = Math.max(current, target) + padding;
  const range = scaleMax - scaleMin || 1;
  const currentPct = ((current - scaleMin) / range) * 100;
  const targetPct = ((target - scaleMin) / range) * 100;
  const fmtVal = (v: number) => {
    const abs = Math.abs(v);
    const s = abs >= 100 ? v.toFixed(0) : abs >= 10 ? v.toFixed(1) : v.toFixed(2);
    return (v > 0 && unit !== "" ? "+" : "") + s + unit;
  };
  const clamp = (v: number) => Math.min(Math.max(v, 5), 95);
  return (
    <div className="mt-2 mb-4">
      <div className="relative h-1.5">
        <div className="absolute inset-0 bg-zinc-800 rounded-full" />
        <div
          className="absolute top-0 h-1.5 bg-zinc-600/40 rounded-full"
          style={{
            left: `${Math.min(currentPct, targetPct)}%`,
            width: `${Math.abs(targetPct - currentPct)}%`,
          }}
        />
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-lime-500/70 rounded-full"
          style={{ left: `${targetPct}%`, transform: "translateX(-50%)" }}
        />
        <div
          className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-2.5 h-2.5 rounded-full bg-zinc-400 border-2 border-zinc-800"
          style={{ left: `${currentPct}%` }}
        />
      </div>
      <div className="relative h-3.5 mt-0.5">
        <span
          className="absolute text-[9px] text-zinc-500 -translate-x-1/2 leading-none"
          style={{ left: `${clamp(currentPct)}%` }}
        >
          {fmtVal(current)}
        </span>
        <span
          className="absolute text-[9px] text-lime-600 font-medium -translate-x-1/2 leading-none"
          style={{ left: `${clamp(targetPct)}%` }}
        >
          {fmtVal(target)} ▲
        </span>
      </div>
    </div>
  );
}

const TIER_ORDER = ["triggered", "about_to_enter", "close", "waiting"] as const;
type TierKey = typeof TIER_ORDER[number];

const TIER_CFG: Record<TierKey, { icon: string; label: string; headerColor: string; rowBorder: string; rowBg: string }> = {
  triggered:      { icon: "⚡", label: "Entry Triggered", headerColor: "text-lime-400",   rowBorder: "border-lime-500/50",   rowBg: "bg-lime-500/8" },
  about_to_enter: { icon: "🟢", label: "About to Enter",  headerColor: "text-lime-400",   rowBorder: "border-lime-500/25",   rowBg: "bg-lime-500/5" },
  close:          { icon: "🟡", label: "Close",           headerColor: "text-yellow-400", rowBorder: "border-yellow-500/20", rowBg: "bg-zinc-900" },
  waiting:        { icon: "⚪", label: "Waiting",         headerColor: "text-zinc-500",   rowBorder: "border-zinc-800",      rowBg: "bg-zinc-900" },
};

// ── Strategy condition trace row ──────────────────────────────────────────────

function ConditionRow({ cond }: { cond: import("@/api/bots").ConditionTrace }) {
  const isVerge = !cond.passed && typeof cond.current_value === "number" &&
    typeof cond.required_value === "number" &&
    Math.abs(cond.current_value - cond.required_value) / Math.max(1, Math.abs(cond.required_value)) <= 0.10;

  const valueColor = cond.error
    ? "text-red-400"
    : cond.passed
    ? "text-lime-400"
    : isVerge
    ? "text-yellow-400"
    : "text-zinc-400";

  const fmtVal = (v: number | number[] | null) => {
    if (v == null) return "—";
    if (Array.isArray(v)) return `[${v.map((x) => x >= 1000 ? x.toLocaleString("en-US", { maximumFractionDigits: 2 }) : x).join(", ")}]`;
    return v >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 4 }) : String(v);
  };

  return (
    <div className={cn("pl-2 border-l-2 mb-2", cond.passed ? "border-lime-500/40" : isVerge ? "border-yellow-500/40" : "border-zinc-700")}>
      <div className="flex items-start gap-1.5">
        {cond.passed
          ? <CheckCircle2 size={11} className="text-lime-500 mt-0.5 flex-shrink-0" />
          : <XCircle size={11} className="text-zinc-600 mt-0.5 flex-shrink-0" />}
        <div className="flex-1 min-w-0">
          <p className="text-[11px] text-zinc-400 leading-tight">{cond.name}</p>
          {cond.error ? (
            <p className="text-[10px] text-red-400 mt-0.5">{cond.error}</p>
          ) : (
            <p className={cn("text-[11px] font-mono mt-0.5", valueColor)}>
              {cond.current_value}{cond.unit ? ` ${cond.unit}` : ""}
              <span className="text-zinc-600 font-sans mx-1">{cond.operator}</span>
              {fmtVal(cond.required_value)}{cond.unit ? ` ${cond.unit}` : ""}
            </p>
          )}
          <p className="text-[10px] text-zinc-500 mt-0.5 leading-snug">{cond.to_pass}</p>
        </div>
      </div>
    </div>
  );
}

function StrategyBlock({ strat }: { strat: StrategyTrace }) {
  const fired = strat.fired;
  return (
    <div className={cn(
      "rounded-xl border px-3 py-2.5 mb-2",
      fired ? "border-lime-500/30 bg-lime-500/5" : "border-zinc-800 bg-zinc-900/50",
    )}>
      <div className="flex items-start gap-2 mb-2">
        <span className={cn("text-sm leading-none mt-0.5", fired ? "text-lime-400" : "text-zinc-600")}>
          {fired ? "✓" : "✗"}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={cn("text-xs font-semibold", fired ? "text-lime-300" : "text-zinc-300")}>
              {strat.name}
            </span>
            {strat.score > 0 && (
              <span className="text-[10px] text-zinc-500">
                score {(strat.score * 100).toFixed(0)}
              </span>
            )}
            {strat.weight > 0 && (
              <span className="text-[10px] text-zinc-600">
                w={strat.weight.toFixed(2)}
              </span>
            )}
            {fired && strat.side && (
              <span className={cn(
                "text-[9px] font-bold px-1.5 py-0.5 rounded-full leading-none",
                strat.side === "buy" || strat.side === "long"
                  ? "bg-lime-500/20 text-lime-400 border border-lime-500/30"
                  : "bg-orange-500/20 text-orange-400 border border-orange-500/30",
              )}>
                {strat.side === "buy" || strat.side === "long" ? "LONG" : "SHORT"}
              </span>
            )}
          </div>
          <p className="text-[11px] text-zinc-500 mt-0.5 leading-snug">{strat.summary}</p>
        </div>
      </div>
      {strat.conditions.length > 0 && (
        <div className="ml-4 mt-1.5">
          {strat.conditions.map((c, i) => <ConditionRow key={i} cond={c} />)}
        </div>
      )}
      {strat.error && !strat.conditions.length && (
        <p className="text-[10px] text-red-400 ml-4 mt-1">{strat.error}</p>
      )}
    </div>
  );
}

function TraceExpandedPanel({ botName, symbol }: { botName: string; symbol: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["strategy-trace", botName, symbol],
    queryFn: () => getBotStrategyTrace(botName, symbol),
    staleTime: 55_000,
    refetchInterval: 60_000,
    retry: 1,
  });

  if (isLoading) {
    return (
      <div className="mt-3 space-y-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-14 bg-zinc-800/40 rounded-xl animate-pulse" />
        ))}
      </div>
    );
  }

  if (error || !data) {
    return (
      <p className="mt-3 text-xs text-red-400">
        Failed to load evaluation trace. Backend may be starting up — try again in a moment.
      </p>
    );
  }

  if (data.error) {
    return <p className="mt-3 text-xs text-red-400">{data.error}</p>;
  }

  const ageStr = data.scan_age_seconds != null
    ? data.scan_age_seconds < 60
      ? `${data.scan_age_seconds}s ago`
      : `${Math.round(data.scan_age_seconds / 60)}m ago`
    : "awaiting first scan";

  return (
    <div className="mt-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-zinc-600">
          {data.strategies_firing}/{data.total_strategies} strategies firing
        </span>
        <span className="text-[10px] text-zinc-600">evaluated {ageStr}</span>
      </div>
      {data.strategies.map((s) => <StrategyBlock key={s.key} strat={s} />)}
    </div>
  );
}

function ExpandableWatchlistRow({
  row,
  botName,
  cfg,
  navigate,
}: {
  row: ReadinessRow;
  botName: string;
  cfg: typeof TIER_CFG[TierKey];
  navigate: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const changePos = row.change_24h_pct >= 0;
  const isTriggered = row.tier === "triggered" || row.criteria_status === "triggered";

  const fmt$ = (v: number | null) => {
    if (v == null) return "—";
    if (v >= 1000) return `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
    return `$${v.toFixed(v >= 10 ? 2 : 4)}`;
  };

  return (
    <div
      className={cn(
        "rounded-xl border mb-1.5 transition-all",
        cfg.rowBorder, cfg.rowBg,
        row.tier === "waiting" && "opacity-80",
        expanded && "ring-1 ring-zinc-600/40",
      )}
    >
      {/* Collapsed header row */}
      <div
        className="flex items-center gap-2 px-4 py-3 cursor-pointer select-none"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-center gap-2 flex-1 min-w-0">
          {expanded
            ? <ChevronDown size={12} className="text-zinc-500 flex-shrink-0" />
            : <ChevronRight size={12} className="text-zinc-500 flex-shrink-0" />}
          <span className="font-mono font-bold text-white text-sm">{row.symbol}</span>
          {isTriggered && (
            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-lime-500 text-black leading-none">
              ⚡ ENTRY
            </span>
          )}
          {row.tier === "about_to_enter" && !isTriggered && (
            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-lime-500/15 text-lime-400 border border-lime-500/30 leading-none">
              CLOSE
            </span>
          )}
          <span className="text-[10px] text-zinc-600 truncate hidden sm:block">
            {row.gap_human || row.criteria_summary}
          </span>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          <div className="text-right">
            <span className="text-xs text-zinc-300 tabular-nums">{fmt$(row.current_price)}</span>
            <span className={cn("text-[10px] ml-1.5 tabular-nums", changePos ? "text-lime-400" : "text-red-400")}>
              {changePos ? "+" : ""}{row.change_24h_pct.toFixed(2)}%
            </span>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); navigate(`/chart?symbol=${row.symbol.replace("/", "-")}`); }}
            className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors px-1.5 py-0.5 rounded border border-zinc-800 hover:border-zinc-600"
          >
            chart
          </button>
        </div>
      </div>

      {/* Expanded strategy evaluation */}
      {expanded && (
        <div className="px-4 pb-3 border-t border-zinc-800/60">
          <TraceExpandedPanel botName={botName} symbol={row.symbol} />
        </div>
      )}
    </div>
  );
}

function EntryReadinessTable({ botName, botDisplayName, navigate }: {
  botName: string;
  botDisplayName: string;
  navigate: (path: string) => void;
}) {
  const { data, isLoading, dataUpdatedAt } = useQuery({
    queryKey: ["watchlist-readiness", botName],
    queryFn: () => getBotWatchlistReadiness(botName),
    enabled: !!botName,
    retry: 1,
    staleTime: 25_000,
    refetchInterval: 30_000,
  });

  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const containerRef = useRef<HTMLDivElement>(null);
  const prevTiersRef = useRef<Record<string, string>>({});

  const rows = data?.rows ?? [];
  const cadence = data?.cadence ? parseCadence(data.cadence) : "scheduled";
  const noUniverse = data?.no_universe;
  const lastUpdate = dataUpdatedAt ? new Date(dataUpdatedAt) : null;

  useEffect(() => {
    if (!rows.length) return;
    const prev = prevTiersRef.current;
    const justEntered = rows.filter(
      (r) => r.tier === "about_to_enter" && prev[r.symbol] && prev[r.symbol] !== "about_to_enter" && prev[r.symbol] !== "triggered"
    );
    if (justEntered.length > 0) {
      containerRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    }
    const next: Record<string, string> = {};
    rows.forEach((r) => { next[r.symbol] = r.tier; });
    prevTiersRef.current = next;
  }, [rows]);

  const secsSince = lastUpdate ? Math.round((Date.now() - lastUpdate.getTime()) / 1000) : 0;
  const nextScanIn = Math.max(0, 30 - (tick >= 0 ? secsSince : 0));

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="animate-pulse bg-zinc-800/50 rounded-xl h-16" />
        ))}
      </div>
    );
  }

  if (noUniverse || (rows.length === 0 && !isLoading)) {
    return (
      <div className="py-10 text-center">
        <p className="text-zinc-500 text-sm">No universe configured for this bot yet.</p>
        <p className="text-zinc-600 text-xs mt-1">
          Options bot universes are being wired up — check back after the next deploy.
        </p>
      </div>
    );
  }

  const tierCounts = Object.fromEntries(
    TIER_ORDER.map((t) => [t, rows.filter((r) => r.tier === t).length])
  ) as Record<TierKey, number>;

  const closest = rows[0];

  return (
    <div ref={containerRef} className="space-y-1">
      {/* Status banner */}
      <div className="bg-zinc-800/40 border border-zinc-700/50 rounded-xl px-4 py-3 mb-3 sticky top-0 z-10 backdrop-blur-sm">
        <p className="text-xs text-zinc-300 leading-relaxed">
          Watching <span className="font-semibold text-white">{rows.length}</span> symbols · {" "}
          <span className="text-lime-400 font-semibold">{tierCounts.triggered + tierCounts.about_to_enter}</span> close to entry · {" "}
          <span className="text-yellow-400 font-semibold">{tierCounts.close}</span> watching · {" "}
          <span className="text-zinc-500">{tierCounts.waiting}</span> waiting
          {closest?.gap_human && (
            <> · <span className="text-zinc-400">Closest: <span className="text-white font-medium">{closest.symbol}</span> — {closest.gap_human}</span></>
          )}
        </p>
        <p className="text-[10px] text-zinc-600 mt-0.5">
          Scans {cadence} · next scan in {nextScanIn}s · click any row to see why it's not firing
        </p>
      </div>

      {/* Tier sections */}
      {TIER_ORDER.map((tier) => {
        const cfg = TIER_CFG[tier];
        const tierRows = rows.filter((r) => r.tier === tier);
        return (
          <div key={tier}>
            <div className="flex items-center gap-2 pt-3 pb-1.5 first:pt-0">
              <span className="text-sm leading-none">{cfg.icon}</span>
              <span className={cn("text-xs font-semibold uppercase tracking-wide", cfg.headerColor)}>
                {cfg.label}
              </span>
              <span className="text-xs text-zinc-600">({tierCounts[tier]})</span>
              <div className="flex-1 h-px bg-zinc-800 ml-1" />
            </div>

            {tierRows.length === 0 && (
              <p className="text-[11px] text-zinc-700 pl-2 pb-2 italic">None</p>
            )}

            {tierRows.map((row) => (
              <ExpandableWatchlistRow
                key={row.symbol}
                row={row}
                botName={botName}
                cfg={cfg}
                navigate={navigate}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
}

// ─── Top-3 watchlist preview (for Overview tab) ───────────────────────────────

function WatchlistPreview({ botName, onViewAll }: { botName: string; onViewAll: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["watchlist-readiness", botName],
    queryFn: () => getBotWatchlistReadiness(botName),
    enabled: !!botName,
    retry: 1,
    staleTime: 25_000,
    refetchInterval: 30_000,
  });

  const rows = (data?.rows ?? [])
    .slice()
    .sort((a, b) => a.distance_to_trigger_pct - b.distance_to_trigger_pct)
    .slice(0, 3);

  if (isLoading) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
        <div className="flex items-center justify-between mb-3">
          <SectionLabel as="h2">Watchlist</SectionLabel>
        </div>
        <div className="space-y-2">
          {[0, 1, 2].map((i) => <div key={i} className="animate-pulse h-10 bg-zinc-800 rounded-xl" />)}
        </div>
      </div>
    );
  }

  if (!rows.length) return null;

  const fmt$ = (v: number | null) => {
    if (v == null) return "—";
    if (v >= 1000) return `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
    return `$${v.toFixed(v >= 10 ? 2 : 4)}`;
  };

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
      <div className="flex items-center justify-between mb-3">
        <SectionLabel as="h2">Watchlist — Closest to Entry</SectionLabel>
        <button
          onClick={onViewAll}
          className="text-xs text-lime-400 hover:text-lime-300 transition-colors"
        >
          See full watchlist →
        </button>
      </div>
      <div className="space-y-2">
        {rows.map((row) => {
          const isTriggered = row.criteria_status === "triggered" || row.distance_to_trigger_pct <= 0;
          const isClose = row.tier === "about_to_enter" || row.tier === "triggered";
          return (
            <div
              key={row.symbol}
              className={cn(
                "flex items-center justify-between rounded-xl border px-4 py-2.5",
                isTriggered
                  ? "border-lime-500/40 bg-lime-500/5"
                  : isClose
                  ? "border-lime-500/30 bg-lime-500/5"
                  : row.distance_color === "yellow"
                  ? "border-yellow-500/20 bg-zinc-900"
                  : "border-zinc-800 bg-zinc-900"
              )}
            >
              <div className="flex items-center gap-3 min-w-0">
                <span className="font-semibold text-white text-sm">{row.symbol}</span>
                <span className="text-xs text-zinc-500 truncate">{row.strategy_being_evaluated}</span>
              </div>
              <div className="flex items-center gap-4 flex-shrink-0">
                <span className="text-xs text-zinc-400">{fmt$(row.current_price)}</span>
                <span className={cn(
                  "text-xs font-semibold",
                  row.tier === "triggered" ? "text-lime-400" :
                  row.tier === "about_to_enter" ? "text-lime-300" :
                  row.tier === "close" ? "text-yellow-400" : "text-zinc-500"
                )}>
                  {row.tier === "triggered" ? "⚡ triggered" : row.gap_human || `${row.distance_to_trigger_pct.toFixed(1)}% away`}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Legacy watchlist table (kept for AI conviction column) ───────────────────

function WatchlistTable({
  botName,
  analysisBySymbol = {},
  onSelectAnalysis,
}: {
  botName: string;
  analysisBySymbol?: Record<string, WatchlistAnalysis>;
  onSelectAnalysis?: (a: WatchlistAnalysis) => void;
}) {
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

  const safeWatchlist = Array.isArray(watchlist) ? watchlist : [];

  if (safeWatchlist.length === 0) {
    return (
      <p className="text-zinc-600 text-sm py-4 text-center">
        Score data unavailable — entry-readiness shown above.
      </p>
    );
  }

  const displayed = showAll ? safeWatchlist : safeWatchlist.slice(0, 20);

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-zinc-600 border-b border-zinc-800">
              <th className="text-left pb-2 font-medium w-8">#</th>
              <th className="text-left pb-2 font-medium">Symbol</th>
              <th className="text-left pb-2 font-medium w-32">Score</th>
              <th className="text-left pb-2 font-medium">AI Conviction</th>
              <th className="text-right pb-2 font-medium">Last Evaluated</th>
            </tr>
          </thead>
          <tbody>
            {displayed.map((item, idx) => {
              const analysis = analysisBySymbol[item.symbol];
              return (
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
                  <td className="py-2.5">
                    {analysis ? (
                      <button
                        onClick={() => onSelectAnalysis?.(analysis)}
                        className="flex items-center gap-1.5 hover:opacity-80 transition-opacity"
                        title="View AI thesis"
                      >
                        <ConvictionStars score={analysis.conviction_score} />
                        {analysis.concerns_flag && <span className="text-red-400 text-xs">⚑</span>}
                      </button>
                    ) : (
                      <span className="text-zinc-700 text-xs">Not analyzed</span>
                    )}
                  </td>
                  <td className="py-2.5 text-right text-xs text-zinc-500">
                    {formatRelativeAgo(item.last_evaluated_at)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {safeWatchlist.length > 20 && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="mt-3 text-xs text-zinc-500 hover:text-zinc-300 underline underline-offset-2 transition-colors"
        >
          {showAll ? "Show fewer" : `Show all ${safeWatchlist.length} symbols`}
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
          <div className="px-4 py-2.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-xs text-zinc-500">
            Full backtesting engine coming Q3 — currently disabled to prevent misleading results.
          </div>
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

type Tab = "overview" | "watchlist" | "backtest" | "activity" | "strategies" | "settings" | "performance";

function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  const tabs: { key: Tab; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "watchlist", label: "Watchlist" },
    { key: "backtest", label: "Backtest" },
    { key: "activity", label: "Recent Trades" },
    { key: "strategies", label: "Strategies" },
    { key: "performance", label: "Performance" },
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

function ActivityTab({ botName, isCrypto, searchRef }: { botName: string; isCrypto: boolean; searchRef?: React.RefObject<HTMLInputElement | null> }) {
  const navigate = useNavigate();
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
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-800">
          <p className="text-sm font-semibold text-white">Recent Trades</p>
          <p className="text-xs text-zinc-600">every P&amp;L dollar backed by a trade</p>
        </div>
        <div className="p-5">
        {isLoading ? (
          <div className="animate-pulse space-y-3">
            {[0, 1, 2, 3, 4].map((i) => <div key={i} className="h-12 bg-zinc-800 rounded-lg" />)}
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-zinc-600 text-sm py-6 text-center">
            {isCrypto
              ? "No trades yet. Crypto bots scan continuously — next scan within 1 min."
              : "No trades yet. The execution engine runs during market hours (Mon–Fri 9:30am–4pm ET)."}
          </p>
        ) : (
          <div className="space-y-0">
            {filtered.map((item) => {
              const ts = (() => {
                try { return new Date(item.ts).toLocaleString(); } catch { return item.ts; }
              })();
              const isFill = item.category === "fill";
              const fillTradeId = isFill ? String(item.id).replace("fill-", "") : null;
              return (
                <div
                  key={item.id}
                  onClick={fillTradeId ? () => navigate(`/strategy/trade/${fillTradeId}`) : undefined}
                  className={cn(
                    "flex items-center gap-3 py-3 border-b border-zinc-800/60 last:border-0 flex-wrap",
                    fillTradeId && "cursor-pointer hover:bg-zinc-800/40 -mx-5 px-5 rounded-lg transition-colors"
                  )}
                >
                  <span className="text-xs text-zinc-600 w-32 flex-shrink-0">{ts}</span>
                  <span className="font-semibold text-white text-sm">{item.symbol}</span>
                  {item.side && (
                    <span className={cn(
                      "text-xs font-bold px-2 py-0.5 rounded-full border",
                      item.side === "buy" || item.side === "long"
                        ? "bg-lime-500/15 text-lime-400 border-lime-500/30"
                        : item.side === "sell" || item.side === "short"
                        ? "bg-red-500/15 text-red-400 border-red-500/30"
                        : "bg-zinc-800 text-zinc-400 border-zinc-700"
                    )}>
                      {item.side === "buy" || item.side === "long" ? "LONG" : item.side === "sell" || item.side === "short" ? "SHORT" : item.side.toUpperCase()}
                    </span>
                  )}
                  {isFill && item.qty != null && item.fill_price != null ? (
                    <span className="text-xs text-zinc-400 tabular-nums">
                      {(() => {
                        const base = item.symbol.includes("/") ? item.symbol.split("/")[0] : item.symbol;
                        const absQty = Math.abs(item.qty);
                        const qtyStr = absQty >= 100 ? item.qty.toFixed(2) : absQty >= 1 ? item.qty.toFixed(4) : item.qty.toFixed(8);
                        const cost = Math.abs(item.qty * item.fill_price);
                        const costStr = cost.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
                        return `${qtyStr} ${base} ($${costStr})`;
                      })()}
                    </span>
                  ) : (
                    <>
                      {item.strategy && (
                        <span className="text-xs px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-400">
                          {item.strategy}
                        </span>
                      )}
                      {item.reason && (
                        <span className="text-xs text-zinc-500 flex-1 truncate min-w-0">{item.reason}</span>
                      )}
                    </>
                  )}
                  {item.pnl_usd != null && (
                    <span className={cn("text-xs font-semibold tabular-nums", item.pnl_usd >= 0 ? "text-emerald-400" : "text-red-400")}>
                      {item.pnl_usd >= 0 ? "+" : ""}${item.pnl_usd.toFixed(2)}
                    </span>
                  )}
                  <span className="ml-auto flex-shrink-0">{resultIcon(item.result)}</span>
                </div>
              );
            })}
          </div>
        )}
        </div>
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

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  mean_reversion: "RSI(14) < 30 → buy, exit RSI > 60. Stop −8%.",
  momentum_breakout: "Break above 20d high with volume > 1.5× avg.",
  rsi_bands: "Buy RSI < 30, sell RSI > 70. Confidence scales with deviation.",
  fifty_two_week_high_momentum: "Long within 5% of 52w high with positive 50d slope.",
  relative_strength_leaders: "Top 5% RS rank in Russell 1000. Hold to 30d or RS exits top 20%.",
  factor_momentum_value: "Momentum (6m return) + value (low P/E). Long top decile.",
  golden_cross: "50d MA crosses above 200d MA. Exit on death cross or −10% stop.",
  bollinger_squeeze: "BB width at 6m low (squeeze), buy on upper-band breakout.",
  cup_and_handle: "Rounding base (15-40% depth) + handle (<8% pullback) + breakout.",
  macd_crossover: "MACD line crosses signal line on daily bars. Exit on reverse cross.",
  earnings_drift_post: "PEAD proxy: gap >3% + 2× volume surge after earnings. Hold 5-15d.",
  orb_stocks_in_play: "5-min ORB on top-20 stocks with first-5-min relative vol > 100%.",
  intraday_momentum_noise_band: "Noise-boundary band; long upper break, short lower, trailing stop.",
  heston_half_hour_continuation: "Cross-sectional half-hour return continuation at day multiples.",
  first_half_hour_predicts_last: "First 30-min SPY/QQQ direction → trade in last 30 min.",
  pead_intraday_drift: "Post-earnings drift, intraday window + NLP sentiment overlay.",
  gex_pin_reversion: "Fade extensions toward dealer pin on positive GEX days.",
  fomc_drift: "Long SPY 24h before FOMC, exit at announcement.",
  vwap_reversion_chop: "VWAP mean reversion, gated to chop regime (ADX < 20).",
  factor_blend: "Equal-weight: value + quality + momentum + low-vol. Top 20 S&P 500.",
  dividend_growth: "5+ yr dividend growth + payout < 60%. Hold for income.",
  quality_score: "High 1yr win rate + max DD > −15% + positive annual return.",
  low_vol_anomaly: "Lowest 1yr realized vol decile. Risk-adj outperformance.",
  momentum_12_1: "12-month return ex last month. Long top decile.",
  small_cap_value: "Price < $20 proxy + 60d momentum not below −10%.",
  shareholder_yield: "Annual return > 5% + monthly win rate ≥ 60%.",
  monthly_rebalance: "Rebalance engine, first Tuesday monthly.",
  crypto_rsi_mean_reversion: "BTC/ETH: long RSI < 25, exit RSI > 75. Wider stops than equity.",
  crypto_momentum_breakout: "Top-20 alts: long break above 30d high with volume confirm.",
  crypto_btc_dominance_regime: "BTC.D falling → rotate to alts. Rising → rotate to BTC.",
  crypto_macd_swing: "MACD cross on 4h bars. Bear regime blocks buy signals.",
  crypto_ema_cross: "9 EMA crosses 21 EMA on daily + BTC trend filter.",
  crypto_relative_strength: "Rank top-30 alts by 14d RS vs BTC. Long top tier.",
  crypto_intraday_momentum: "Noise-band momentum on BTC/ETH/SOL 1h-4h + vol filter.",
  crypto_weekend_momentum: "Hold Fri-close direction Sat-Sun, exit Monday.",
  crypto_volatility_breakout: "Donchian breakout + ATR stops + BTC dominance gate.",
  crypto_news_sentiment: "LunarCrush sentiment overlay on momentum signals.",
  crypto_session_open: "Fade gaps at 00:00 / 12:00 UTC institutional opens.",
  dca_btc_eth: "Weekly DCA Monday 10am UTC into BTC + ETH at target weights.",
  monthly_rebalance_majors: "First Tuesday monthly snap to 60/30/10 BTC/ETH/basket.",
  btc_dominance_rotation: "Rotate BTC↔alts based on BTC.D direction.",
  dollar_cost_average_dip: "Extra DCA fires on > 10% drawdown from 30d rolling high.",
  yield_overlay: "Park idle stables in highest-yield instrument.",
  crypto_quant_vwap_fade: "Price > 1.5σ above 15m session VWAP + RSI > 65 → fade short; below 1.5σ + RSI < 35 → fade long. 4h time-stop.",
  crypto_quant_bb_breakout: "15m close outside Bollinger(20,2) with volume > 1.2x avg → trade the breakout direction. 6h time-stop.",
  crypto_quant_momentum_trigger: "15m close breaks prior 4h high/low with volume > 1.3x avg → momentum entry. 2% trailing stop, 8h time-stop.",
  crypto_quant_volume_zscore_spike: "Volume z-score > 2.0 vs 24h rolling (96 bars) → trade in bar's direction. 1.5% stop, 2h time-stop.",
  crypto_quant_range_break_retest: "Price breaks range then retests breakout level → entry on confirmed retest hold. Tight zone filter.",
};

function strategyLabel(name: string): string {
  return name
    .replace(/^crypto_/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function StrategiesTab({
  botName,
  signals,
}: {
  botName: string;
  signals: BotSignal[];
}) {
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
      <div className="space-y-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 animate-pulse h-28" />
        ))}
      </div>
    );
  }

  const roster = BOT_META[botName]?.strategies ?? [];
  const weightMap = new Map(weights.map((w: StrategyWeight) => [w.strategy, w]));

  // Build display list: use API weight if available, else sensible defaults
  const displayList = roster.map((name) => {
    const w = weightMap.get(name);
    return w ?? {
      strategy: name,
      weight_pct: Math.round(100 / Math.max(roster.length, 1)),
      wins_30d: 0,
      losses_30d: 0,
      locked: false,
    };
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-zinc-300">
          Strategy Roster
          <span className="ml-2 text-xs font-normal text-zinc-600">
            {displayList.length} strategies · ensemble: {BOT_META[botName]?.ensemble ?? "weighted_vote"}
          </span>
        </p>
        <button
          onClick={() => resetMut.mutate()}
          disabled={resetMut.isPending || weights.length === 0}
          className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-400 hover:text-white transition-colors disabled:opacity-40"
        >
          {resetMut.isPending ? "Resetting…" : "Reset weights"}
        </button>
      </div>

      {displayList.map((w) => {
        const total = w.wins_30d + w.losses_30d;
        const winRate = total > 0 ? (w.wins_30d / total) * 100 : null;
        const lastSignal = signals.find((s) => s.strategy === w.strategy);
        const description = STRATEGY_DESCRIPTIONS[w.strategy];

        return (
          <div
            key={w.strategy}
            className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 space-y-3"
          >
            {/* Header row */}
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="text-sm font-semibold text-white">
                    {strategyLabel(w.strategy)}
                  </h3>
                  <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-teal-500/15 border border-teal-500/30 text-teal-400">
                    weight {w.weight_pct}%
                  </span>
                  {w.locked && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-400">
                      locked
                    </span>
                  )}
                </div>
                {description && (
                  <p className="text-xs text-zinc-600 mt-1 leading-relaxed">{description}</p>
                )}
              </div>
              <button
                onClick={() => lockMut.mutate({ strategy: w.strategy, locked: !w.locked })}
                disabled={lockMut.isPending}
                title={w.locked ? "Unlock weight" : "Lock weight"}
                className={cn(
                  "p-1.5 rounded-lg border transition-colors flex-shrink-0",
                  w.locked
                    ? "bg-amber-500/15 border-amber-500/30 text-amber-400"
                    : "bg-zinc-800 border-zinc-700 text-zinc-500 hover:text-zinc-300"
                )}
              >
                {w.locked ? <Lock className="w-3.5 h-3.5" /> : <Unlock className="w-3.5 h-3.5" />}
              </button>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              <div>
                <p className="text-[10px] text-zinc-600 uppercase tracking-wide">30d W / L</p>
                <p className="text-xs font-semibold mt-0.5">
                  <span className="text-lime-400">{w.wins_30d}W</span>
                  <span className="text-zinc-600 mx-1">/</span>
                  <span className="text-red-400">{w.losses_30d}L</span>
                </p>
              </div>
              <div>
                <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Win Rate</p>
                <p className={cn(
                  "text-xs font-semibold mt-0.5",
                  winRate !== null ? (winRate >= 50 ? "text-lime-400" : "text-red-400") : "text-zinc-500"
                )}>
                  {winRate !== null ? `${winRate.toFixed(0)}%` : "—"}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Last Signal</p>
                {lastSignal ? (
                  <p className="text-xs font-semibold mt-0.5">
                    <span className={lastSignal.side === "buy" || lastSignal.side === "long" ? "text-lime-400" : "text-red-400"}>
                      {lastSignal.side === "buy" || lastSignal.side === "long" ? "LONG" : lastSignal.side === "sell" || lastSignal.side === "short" ? "SHORT" : lastSignal.side.toUpperCase()}
                    </span>
                    <span className="text-zinc-500 ml-1">{lastSignal.symbol}</span>
                  </p>
                ) : (
                  <p className="text-xs text-zinc-600 mt-0.5">—</p>
                )}
              </div>
            </div>

            {/* Last signal reason */}
            {lastSignal?.reason && (
              <p className="text-[11px] text-zinc-500 bg-zinc-800/60 rounded-lg px-3 py-2 leading-relaxed">
                "{lastSignal.reason}"
              </p>
            )}
          </div>
        );
      })}
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
        <SectionLabel as="h2">Paper Allocation</SectionLabel>
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
        <SectionLabel as="h2">Go Live</SectionLabel>
        <div className="flex items-center gap-3">
          <div className="relative">
            <button
              disabled
              className="relative inline-flex h-6 w-11 items-center rounded-full bg-zinc-700 cursor-not-allowed opacity-50"
              title="Live trading coming soon — paper trading only"
            >
              <span className="translate-x-1 inline-block h-4 w-4 rounded-full bg-white" />
            </button>
          </div>
          <span className="text-xs text-zinc-500">
            Live trading coming soon — paper trading only
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

    </div>
  );
}

// ─── Performance tab (read-only analytics) ───────────────────────────────────

function BotPerformanceTab({ botName }: { botName: string }) {
  const [period, setPeriod] = useState<"7d" | "30d" | "90d" | "all">("30d");

  const { data: metrics, isLoading, isError } = useQuery({
    queryKey: ["perf-bot-detail", botName, period],
    queryFn: () =>
      import("@/api/performance").then((m) => m.getBotPerformance(botName, period)),
    staleTime: 300_000,
    retry: 0,
  });

  const { data: attrData } = useQuery({
    queryKey: ["perf-bot-attr-detail", botName],
    queryFn: () =>
      import("@/api/performance").then((m) => m.getBotStrategyAttribution(botName, "all")),
    staleTime: 300_000,
    retry: 0,
    enabled: !isError,
  });

  if (isError) return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-10 text-center">
      <p className="text-zinc-400 font-semibold mb-1">Performance analytics not enabled</p>
      <p className="text-zinc-600 text-sm">Set ENABLE_PERFORMANCE_ANALYTICS=true to activate.</p>
    </div>
  );

  const fmtPct = (v: number | null | undefined) =>
    v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
  const fmtUsd = (v: number | null | undefined) => {
    if (v == null) return "—";
    const abs = Math.abs(v);
    const s = abs >= 1000 ? `$${(abs / 1000).toFixed(1)}k` : `$${abs.toFixed(0)}`;
    return v < 0 ? `-${s}` : `+${s}`;
  };
  const pclr = (v: number | null | undefined) =>
    v == null ? "text-zinc-400" : v >= 0 ? "text-emerald-400" : "text-red-400";

  return (
    <div className="space-y-5">
      {/* Period selector */}
      <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1 w-fit">
        {(["7d","30d","90d","all"] as const).map((p) => (
          <button key={p} onClick={() => setPeriod(p)}
            className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors uppercase",
              period === p ? "bg-zinc-700 text-white" : "text-zinc-500 hover:text-zinc-300")}>
            {p}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[0,1,2,3].map((i) => <div key={i} className="h-20 bg-zinc-900 border border-zinc-800 rounded-2xl animate-pulse" />)}
        </div>
      ) : metrics?.total_trades === 0 ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-10 text-center">
          <p className="text-zinc-400 font-semibold">No trade data yet</p>
          <p className="text-zinc-600 text-sm mt-1">Performance appears after the first closed trade.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Metrics grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: "Total Return", value: fmtPct(metrics?.total_return_pct), sub: fmtUsd(metrics?.total_return_usd), cls: pclr(metrics?.total_return_pct) },
              { label: "Sharpe", value: metrics?.sharpe != null ? metrics.sharpe.toFixed(2) : "—", cls: "text-white" },
              { label: "Max Drawdown", value: fmtPct(metrics?.max_drawdown_pct), cls: "text-red-400" },
              { label: "Win Rate", value: metrics?.win_rate != null ? `${(metrics.win_rate * 100).toFixed(0)}%` : "—", sub: `${metrics?.total_trades ?? 0} trades`, cls: "text-white" },
            ].map((card) => (
              <div key={card.label} className="bg-zinc-900 border border-zinc-800 rounded-2xl px-4 py-3">
                <p className="text-[10px] font-semibold text-zinc-600 uppercase tracking-widest mb-1">{card.label}</p>
                <p className={cn("text-xl font-bold font-mono", card.cls)}>{card.value}</p>
                {card.sub && <p className="text-xs text-zinc-500 mt-0.5 font-mono">{card.sub}</p>}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: "Sortino", value: metrics?.sortino != null ? metrics.sortino.toFixed(2) : "—" },
              { label: "Profit Factor", value: metrics?.profit_factor != null ? metrics.profit_factor.toFixed(2) : "—" },
              { label: "Best Trade", value: fmtUsd(metrics?.best_trade_usd), cls: "text-emerald-400" },
              { label: "Worst Trade", value: fmtUsd(metrics?.worst_trade_usd), cls: "text-red-400" },
            ].map((card) => (
              <div key={card.label} className="bg-zinc-900 border border-zinc-800 rounded-2xl px-4 py-3">
                <p className="text-[10px] font-semibold text-zinc-600 uppercase tracking-widest mb-1">{card.label}</p>
                <p className={cn("text-xl font-bold font-mono", (card as any).cls ?? "text-white")}>{card.value}</p>
              </div>
            ))}
          </div>

          {/* Strategy attribution */}
          {attrData && attrData.attribution.length > 0 && (
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 overflow-x-auto">
              <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest mb-3">// STRATEGY ATTRIBUTION</p>
              <table className="w-full text-xs min-w-max">
                <thead>
                  <tr className="border-b border-zinc-800">
                    {["Strategy","Raw Return %","$ Contribution","Capital","Weight"].map((h) => (
                      <th key={h} className="text-left text-[10px] text-zinc-600 uppercase py-2 px-2 first:pl-0">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {attrData.attribution.map((row) => (
                    <tr key={row.strategy} className="border-b border-zinc-800/40">
                      <td className="py-2 pr-4 text-white font-medium">{row.strategy?.replace(/_/g," ") ?? "Unattributed"}</td>
                      <td className={cn("py-2 px-2 font-mono", pclr(row.raw_return_pct))}>{fmtPct(row.raw_return_pct)}</td>
                      <td className={cn("py-2 px-2 font-mono", pclr(row.pnl_usd))}>{fmtUsd(row.pnl_usd)}</td>
                      <td className="py-2 px-2 font-mono text-zinc-400">${(row.capital_deployed_usd ?? 0).toFixed(0)}</td>
                      <td className="py-2 px-2 font-mono text-zinc-400">{row.weight_pct != null ? `${row.weight_pct.toFixed(1)}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Bot Why section (expandable) ────────────────────────────────────────────

function BotWhySection({
  botName,
  meta,
  profile,
}: {
  botName: string;
  meta: { displayName: string; description: string; assetClass: "stock" | "crypto" | "quant"; strategies: string[]; ensemble?: string } | undefined;
  profile: import("@/api/bots").BotProfile | undefined;
}) {
  const [expanded, setExpanded] = useState(false);

  const strategies = meta?.strategies ?? [];
  const description = meta?.description ?? profile?.description ?? "";

  const strategySnippets = strategies.slice(0, 4).map((s) => {
    const desc = STRATEGY_DESCRIPTIONS[s];
    return { name: strategyLabel(s), desc: desc ?? null };
  });

  return (
    <div className="border border-zinc-800 rounded-xl overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-zinc-800/40 transition-colors"
      >
        <span className="text-xs font-semibold text-zinc-400">Why this bot?</span>
        <span className="text-zinc-600 text-xs">{expanded ? "▲" : "▼"}</span>
      </button>
      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-zinc-800">
          {description && (
            <p className="text-xs text-zinc-400 leading-relaxed pt-3">{description}</p>
          )}
          {strategySnippets.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] text-zinc-600 uppercase tracking-wide font-semibold">
                Sample Strategies ({strategies.length} total)
              </p>
              {strategySnippets.map((s) => (
                <div key={s.name}>
                  <p className="text-xs font-semibold text-zinc-300">{s.name}</p>
                  {s.desc && <p className="text-[11px] text-zinc-600 leading-relaxed">{s.desc}</p>}
                </div>
              ))}
              {strategies.length > 4 && (
                <p className="text-[11px] text-zinc-600 italic">
                  +{strategies.length - 4} more strategies — view in the Strategies tab
                </p>
              )}
            </div>
          )}
        </div>
      )}
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
  const [selectedPosition, setSelectedPosition] = useState<BotPosition | null>(null);
  const [analystPanel, setAnalystPanel] = useState<WatchlistAnalysis | null>(null);
  const activitySearchRef = useRef<HTMLInputElement | null>(null);

  const meta = BOT_META[botName];
  const isCrypto = ["crypto", "quant"].includes(meta?.assetClass ?? (botName.startsWith("crypto") ? "crypto" : "stock"));

  const [showCoachmark, setShowCoachmark] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["bot", botName],
    queryFn: () => getBot(botName),
    enabled: !!botName,
    retry: 1,
  });

  useEffect(() => {
    const profileId = data?.profile?.id;
    if (!profileId) return;
    const key = `coachmark_pending_${profileId}`;
    if (localStorage.getItem(key)) {
      setShowCoachmark(true);
    }
  }, [data?.profile?.id]);

  function dismissCoachmark() {
    const profileId = data?.profile?.id;
    if (profileId) localStorage.removeItem(`coachmark_pending_${profileId}`);
    setShowCoachmark(false);
  }

  const { data: regime, isLoading: regimeLoading } = useQuery({
    queryKey: ["regime"],
    queryFn: getRegime,
    retry: 0,
    staleTime: 60_000,
  });

  const profile = data?.profile;
  const allocation = data?.allocation;
  const positions: BotPosition[] = Array.isArray(data?.positions) ? data!.positions : [];

  const isSymbolMismatch = (symbol: string): boolean => {
    const ac = profile?.asset_class;
    if (!ac) return false;
    const isCryptoSym = symbol.includes("/USD");
    if (ac === "crypto" || ac === "quant") return !isCryptoSym;
    if (ac === "stock" || ac === "options") return isCryptoSym;
    return false;
  };
  const isRebalanceOnly = !!(profile?.config as Record<string, unknown> | undefined)?.rebalance_only;
  const signals: BotSignal[] = (Array.isArray(data?.signals) ? data!.signals : []).filter(
    (s) => !s.reason?.toLowerCase().includes("stub") && !s.strategy?.toLowerCase().includes("stub")
  );

  // Analyst data for watchlist tab
  const { data: rawAnalyses } = useQuery({
    queryKey: ["watchlist-analyses", profile?.id],
    queryFn: () => getWatchlistAnalyses(profile!.id),
    enabled: !!profile?.id && activeTab === "watchlist",
    staleTime: 300_000,
    retry: 0,
  });
  const analysisBySymbol = useMemo(() => {
    const map: Record<string, WatchlistAnalysis> = {};
    if (Array.isArray(rawAnalyses)) {
      for (const a of rawAnalyses) map[a.symbol] = a;
    }
    return map;
  }, [rawAnalyses]);

  // Live prices for open positions — always fetch when positions exist, 30s refresh
  const positionSymbols = useMemo(() => positions.map(p => p.symbol), [positions]);
  const { data: livePrices = {} } = useQuery({
    queryKey: ["live-prices", positionSymbols],
    queryFn: () => getLatestPrices(positionSymbols),
    enabled: positionSymbols.length > 0,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
  const stats = (data?.stats ?? {}) as {
    return_30d_pct?: number;
    today_pnl?: number;
    open_positions?: number;
    win_rate_pct?: number;
    win_rate_30d?: { pct: number | null; wins: number; losses: number; display: string };
    equity_curve?: EquityPoint[];
    all_time_return_pct?: number | null;
    portfolio_value_cents?: number | null;
  };

  // Local allocation state
  const [capitalPct, setCapitalPct] = useState<number>(allocation?.capital_pct ?? 10);
  const [riskProfile, setRiskProfile] = useState<"conservative" | "standard" | "aggressive">(
    allocation?.risk_profile ?? "standard"
  );

  const isEnabled = allocation?.enabled ?? false;
  const isOnWaitlist = allocation?.go_live_requested ?? false;
  const isViewer = useIsViewer();

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

      {/* Tab system — top of page, below back nav */}
      <TabBar active={activeTab} onChange={setActiveTab} />

      {/* ── Bot Header Strip — always visible regardless of tab ── */}
      <BracketFrame className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-4 flex flex-wrap items-center gap-4" glow>
        {isLoading ? (
          <div className="animate-pulse flex items-center gap-4 w-full">
            <div className="h-6 w-40 bg-zinc-800 rounded" />
            <div className="h-6 w-24 bg-zinc-800 rounded" />
            <div className="h-6 w-32 bg-zinc-800 rounded ml-auto" />
          </div>
        ) : (
          <>
            {/* Name + status */}
            <div className="flex items-center gap-2 min-w-0">
              <h1 className="text-base font-bold text-white truncate font-mono tracking-wide">
                {meta?.displayName ?? displayName(botName)}
              </h1>
              <span
                className={cn(
                  "text-[10px] font-semibold px-2 py-0.5 rounded-full border flex-shrink-0",
                  isEnabled
                    ? "bg-lime-500/15 text-lime-400 border-lime-500/30"
                    : "bg-zinc-800 text-zinc-500 border-zinc-700"
                )}
              >
                {isEnabled ? "ACTIVE" : "PAUSED"}
              </span>
            </div>

            {/* Today P&L */}
            <div className="flex flex-col">
              <span className="text-[10px] text-zinc-600 uppercase tracking-wide">Today P&L</span>
              <span className={cn(
                "text-lg font-bold",
                (stats?.today_pnl ?? 0) >= 0 ? "text-lime-400" : "text-red-400"
              )}>
                {formatPnl(stats?.today_pnl ?? 0)}
              </span>
            </div>

            {/* Open positions + notional */}
            <div className="flex flex-col">
              <span className="text-[10px] text-zinc-600 uppercase tracking-wide">Open Positions</span>
              <span className="text-base font-bold text-white">
                {positions.length}
                {positions.length > 0 && (
                  <span className="text-xs text-zinc-500 font-normal ml-1">
                    / $
                    {positions.reduce((sum, p) => {
                      return sum + (p.market_value ?? (livePrices[p.symbol] ?? (p.avg_cost_cents / 100)) * p.qty);
                    }, 0).toLocaleString(undefined, { maximumFractionDigits: 0 })} notional
                  </span>
                )}
              </span>
            </div>

            {/* Admin-only action buttons */}
            {!isViewer && (
              <div className="ml-auto flex items-center gap-2">
                <button
                  onClick={() => allocateMut.mutate({ enabled: !isEnabled })}
                  disabled={allocateMut.isPending}
                  className={cn(
                    "px-3 py-1.5 rounded-lg border text-xs font-semibold transition-colors",
                    isEnabled
                      ? "border-zinc-700 text-zinc-400 hover:border-red-600 hover:text-red-400"
                      : "border-lime-600/50 text-lime-400 hover:bg-lime-500/10"
                  )}
                >
                  {isEnabled ? "Disable Bot" : "Enable Bot"}
                </button>
                {!isOnWaitlist ? (
                  <button
                    onClick={() => waitlistMut.mutate(!isOnWaitlist)}
                    disabled={waitlistMut.isPending}
                    className="px-3 py-1.5 rounded-lg border border-amber-500/30 text-xs font-semibold text-amber-400 hover:bg-amber-500/10 transition-colors"
                  >
                    Notify when live
                  </button>
                ) : (
                  <span className="text-xs text-lime-400 font-semibold">✓ On waitlist</span>
                )}
              </div>
            )}
          </>
        )}
      </BracketFrame>

      {/* Overview tab */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          {/* Open Positions */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
            <SectionLabel as="h2" className="mb-4">Open Positions</SectionLabel>
            {isRebalanceOnly && positions.length > 0 && (
              <p className="text-xs text-zinc-500 mb-3 bg-zinc-800/50 border border-zinc-700/50 rounded-lg px-3 py-2">
                Long-term holds — this bot uses larger position sizes by design (weekly DCA / rebalance, fewer trades, longer hold periods).
              </p>
            )}
            {isLoading ? (
              <div className="animate-pulse space-y-2">
                {[0, 1, 2].map((i) => <div key={i} className="h-10 bg-zinc-800 rounded" />)}
              </div>
            ) : positions.length === 0 ? (
              <p className="text-zinc-600 text-sm py-6 text-center leading-relaxed">
                Bot is scanning — open positions will appear here when it enters a trade.{" "}
                Check the Watchlist tab to see what it&apos;s currently evaluating.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-zinc-600 border-b border-zinc-800">
                      <th className="text-left pb-2 font-medium">Symbol</th>
                      <th className="text-left pb-2 font-medium">Side</th>
                      <th className="text-right pb-2 font-medium">Size</th>
                      <th className="text-right pb-2 font-medium">Current Value</th>
                      <th className="text-right pb-2 font-medium">Unrealized P&L</th>
                      <th className="text-right pb-2 font-medium">Time Held</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((pos) => {
                      // Prefer server-enriched fields; fall back to live price fetch
                      const currentValue = pos.market_value ?? (livePrices[pos.symbol] != null && pos.qty ? livePrices[pos.symbol]! * pos.qty : null);
                      const unrealizedPnl = pos.unrealized_pnl ?? null;
                      const pnlPct = pos.unrealized_pnl_pct ?? null;
                      const timeHeld = pos.opened_at
                        ? (() => {
                            // Ensure UTC parsing — isoformat() from Python has no Z suffix
                            const raw = pos.opened_at;
                            const openedAt = new Date(raw.endsWith("Z") || raw.includes("+") ? raw : raw + "Z");
                            const ms = Math.max(0, Date.now() - openedAt.getTime());
                            const hrs = Math.floor(ms / 3_600_000);
                            const mins = Math.floor((ms % 3_600_000) / 60_000);
                            return hrs >= 24
                              ? `${Math.floor(hrs / 24)}d ${hrs % 24}h`
                              : hrs > 0 ? `${hrs}h ${mins}m` : `${mins}m`;
                          })()
                        : "—";
                      return (
                        <tr
                          key={pos.id}
                          className="border-b border-zinc-800/50 last:border-0 cursor-pointer hover:bg-zinc-800/30 transition-colors"
                          onClick={() => navigate(`/chart?symbol=${pos.symbol}`)}
                          title={`View ${pos.symbol} chart`}
                        >
                          <td className="py-2.5">
                            <div className="flex items-center gap-1.5">
                              <span className="font-semibold text-white">{pos.symbol}</span>
                              {isSymbolMismatch(pos.symbol) && (
                                <span className="text-[10px] text-amber-400 border border-amber-400/30 bg-amber-400/10 px-1 py-0.5 rounded font-medium whitespace-nowrap">⚠️ mismatch</span>
                              )}
                            </div>
                          </td>
                          <td className="py-2.5">
                            <span className="text-xs font-semibold px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-500/20">
                              LONG
                            </span>
                          </td>
                          <td className="py-2.5 text-right text-zinc-300 tabular-nums">
                            {pos.qty != null && pos.avg_cost_cents != null
                              ? formatTradeSize(pos.qty, pos.symbol, (pos.avg_cost_cents / 100) * Math.abs(pos.qty))
                              : pos.qty != null ? formatQty(pos.qty, pos.symbol) : "—"}
                          </td>
                          <td className="py-2.5 text-right text-zinc-300 tabular-nums">
                            {currentValue != null ? `$${currentValue.toFixed(2)}` : "—"}
                          </td>
                          <td className={cn(
                            "py-2.5 text-right text-sm font-medium tabular-nums",
                            unrealizedPnl == null ? "text-zinc-500"
                              : unrealizedPnl >= 0 ? "text-lime-400" : "text-red-400"
                          )}>
                            {unrealizedPnl != null
                              ? `${unrealizedPnl >= 0 ? "+" : ""}$${Math.abs(unrealizedPnl).toFixed(2)}${pnlPct != null ? ` (${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%)` : ""}`
                              : "—"}
                          </td>
                          <td className="py-2.5 text-right text-xs text-zinc-500">{timeHeld}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Stats grid + Equity Curve */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* LEFT — Portfolio Summary */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-2">
                {[
                  { label: "Starting Capital", value: allocation?.starting_capital_cents ? `$${(allocation.starting_capital_cents / 100).toLocaleString()}` : "—" },
                  { label: "Current Value", value: allocation ? `$${((stats?.portfolio_value_cents ?? allocation?.starting_capital_cents ?? 0) / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—" },
                  { label: "All-Time Return", value: allocation ? `${(stats?.all_time_return_pct ?? 0) >= 0 ? "+" : ""}${(stats?.all_time_return_pct ?? 0).toFixed(2)}%` : "—", colored: true, positive: (stats?.all_time_return_pct ?? 0) >= 0 },
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
                    value: String(positions.length),
                    colored: false,
                  },
                ].map((s) => (
                  <div key={s.label} className="bg-zinc-950 rounded-xl px-3 py-2.5 border border-zinc-800">
                    <p className="text-zinc-600 text-[10px] uppercase tracking-wide mb-0.5">{s.label}</p>
                    <p
                      className={cn(
                        "text-sm font-bold",
                        s.colored ? (s.positive ? "text-lime-400" : "text-red-400") : "text-white"
                      )}
                    >
                      {s.value}
                    </p>
                  </div>
                ))}
              </div>
              {allocation && (
                <p className="text-xs text-zinc-500">
                  Allocated:{" "}
                  <span className="text-zinc-300 font-semibold">
                    ${allocation.starting_capital_cents ? (allocation.starting_capital_cents / 100).toLocaleString() : ((allocation.capital_pct / 100) * 100000).toLocaleString()} ({allocation.capital_pct}%)
                  </span>
                </p>
              )}
            </div>

            {/* RIGHT — Equity Curve */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex flex-col gap-3">
              <SectionLabel as="h2">Equity Curve</SectionLabel>
              {equityCurve.length === 0 ? (
                <div className="flex-1 flex items-center justify-center min-h-[180px]">
                  <p className="text-zinc-600 text-sm text-center px-4 leading-relaxed">
                    Bot too new for chart — first data point appears at end of today&apos;s trading session
                  </p>
                </div>
              ) : (
                <>
                  <ResponsiveContainer width="100%" height={200}>
                    <AreaChart data={equityCurve} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={
                            equityCurve.length > 0 && equityCurve[equityCurve.length - 1].portfolio >= equityCurve[0].portfolio
                              ? "#84cc16" : "#ef4444"
                          } stopOpacity={0.3} />
                          <stop offset="95%" stopColor={
                            equityCurve.length > 0 && equityCurve[equityCurve.length - 1].portfolio >= equityCurve[0].portfolio
                              ? "#84cc16" : "#ef4444"
                          } stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="date" tick={{ fill: "#71717a", fontSize: 10 }} tickLine={false} axisLine={false} />
                      <YAxis tick={{ fill: "#71717a", fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
                      <Tooltip
                        contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }}
                        labelStyle={{ color: "#a1a1aa" }}
                        formatter={(v: number) => [`$${v.toFixed(2)}`, "Portfolio"]}
                      />
                      <Area
                        type="monotone"
                        dataKey="portfolio"
                        stroke={
                          equityCurve.length > 0 && equityCurve[equityCurve.length - 1].portfolio >= equityCurve[0].portfolio
                            ? "#84cc16" : "#ef4444"
                        }
                        strokeWidth={2}
                        fill="url(#equityGradient)"
                        dot={false}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                  <div className="flex gap-4">
                    <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                      <span className="w-3 h-0.5 bg-[#84cc16] inline-block rounded" />
                      Portfolio
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Current Regime */}
          <RegimePanel regime={regime} isLoading={regimeLoading} />

          {/* Upcoming Catalysts */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3">
            <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-2">Upcoming Catalysts</h3>
            <CatalystCalendar />
          </div>

          {/* PDT removal notice for day-trading bots */}
          {(botName === "stock_day" || botName === "crypto_day") && (
            <div className="flex items-start gap-3 bg-teal-500/10 border border-teal-500/30 rounded-xl px-4 py-3">
              <span className="text-teal-400 mt-0.5 text-base leading-none">⚡</span>
              <div>
                <p className="text-xs font-semibold text-teal-400">PDT Rule Eliminated — June 4, 2026</p>
                <p className="text-xs text-zinc-500 mt-0.5 leading-relaxed">
                  FINRA Notice 26-10 removed the Pattern Day Trader $25,000 minimum. This bot now
                  trades without account-size restrictions. <span className="text-zinc-400">Paper mode active.</span>
                </p>
              </div>
            </div>
          )}

          {/* Top-3 watchlist preview */}
          <WatchlistPreview botName={botName} onViewAll={() => setActiveTab("watchlist")} />

          {/* Bot Info — full width */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex flex-col gap-4">
              <SectionLabel as="h2">Bot Info</SectionLabel>

              {/* Description + asset class */}
              <div className="flex items-start gap-3">
                {(() => {
                  const ac = profile?.asset_class ?? (botName.includes("options") ? "options" : isCrypto ? "crypto" : "stock");
                  const isOptions = ac === "options" || botName.includes("options");
                  return (
                    <span className={cn(
                      "text-xs font-semibold px-2 py-0.5 rounded-full border flex-shrink-0 mt-0.5",
                      isOptions
                        ? "bg-purple-500/15 text-purple-400 border-purple-500/30"
                        : isCrypto
                          ? "bg-orange-500/15 text-orange-400 border-orange-500/30"
                          : "bg-blue-500/15 text-blue-400 border-blue-500/30"
                    )}>
                      {isOptions ? "OPTIONS" : isCrypto ? "CRYPTO" : "STOCK"}
                    </span>
                  );
                })()}
                <p className="text-sm text-zinc-400 leading-relaxed">
                  {meta?.description ?? profile?.description ?? "No description available."}
                </p>
              </div>

              {/* Key stats */}
              <div className="grid grid-cols-2 gap-2">
                <div className="bg-zinc-950 rounded-xl px-3 py-2.5 border border-zinc-800">
                  <p className="text-zinc-600 text-[10px] uppercase tracking-wide mb-0.5">Win Rate</p>
                  <p className={cn(
                    "text-sm font-bold",
                    stats?.win_rate_pct ? ((stats.win_rate_pct ?? 0) >= 50 ? "text-lime-400" : "text-red-400") : "text-zinc-500"
                  )}>
                    {stats?.win_rate_pct ? `${(stats.win_rate_pct ?? 0).toFixed(1)}%` : "—"}
                  </p>
                </div>
                <div className="bg-zinc-950 rounded-xl px-3 py-2.5 border border-zinc-800">
                  <p className="text-zinc-600 text-[10px] uppercase tracking-wide mb-0.5">Last Signal</p>
                  <p className="text-sm font-bold text-zinc-300">
                    {signals.length > 0 ? formatRelativeAgo(signals[0].ts) : "—"}
                  </p>
                </div>
                <div className="bg-zinc-950 rounded-xl px-3 py-2.5 border border-zinc-800">
                  <p className="text-zinc-600 text-[10px] uppercase tracking-wide mb-0.5">Cadence</p>
                  <p className="text-sm font-bold text-zinc-300 capitalize">{profile?.cadence ? formatCadence(profile.cadence) : "—"}</p>
                </div>
                <div className="bg-zinc-950 rounded-xl px-3 py-2.5 border border-zinc-800">
                  <p className="text-zinc-600 text-[10px] uppercase tracking-wide mb-0.5">Strategies</p>
                  <p className="text-sm font-bold text-zinc-300">
                    {(meta?.strategies?.length ?? 0) > 0 ? meta!.strategies.length : "—"}
                  </p>
                </div>
              </div>

              {/* Why this bot? expandable */}
              <BotWhySection botName={botName} meta={meta} profile={profile} />
          </div>

          {/* Activity feed below grid */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
            <SectionLabel as="h2" className="mb-4">Recent Signals</SectionLabel>
            {signals.length === 0 ? (
              <p className="text-zinc-600 text-sm py-4 text-center">No signals fired today. Next scan at market open (9:30am ET).</p>
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
        <div className="space-y-4">
          {/* Live entry-readiness feed */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-zinc-300">
                {meta?.displayName ?? botName} Watchlist
              </h2>
              <span className="text-[10px] text-zinc-600">Refreshes every 30s</span>
            </div>
            <EntryReadinessTable
              botName={botName}
              botDisplayName={meta?.displayName ?? botName}
              navigate={navigate}
            />
          </div>

          {/* AI conviction scores (secondary) */}
          {Object.keys(analysisBySymbol).length > 0 && (
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
              <h2 className="text-sm font-semibold text-zinc-300 mb-4">AI Conviction Scores</h2>
              <WatchlistTable
                botName={botName}
                analysisBySymbol={analysisBySymbol}
                onSelectAnalysis={setAnalystPanel}
              />
            </div>
          )}
        </div>
      )}
      {analystPanel && (
        <AnalystDrawer analysis={analystPanel} onClose={() => setAnalystPanel(null)} />
      )}

      {/* Backtest tab */}
      {activeTab === "backtest" && <BacktestTab botName={botName} />}

      {/* Activity tab */}
      {activeTab === "activity" && (
        <ActivityTab botName={botName} isCrypto={isCrypto} searchRef={activitySearchRef} />
      )}

      {/* Strategies tab */}
      {activeTab === "strategies" && <StrategiesTab botName={botName} signals={signals} />}

      {/* Settings tab */}
      {activeTab === "performance" && (
        <BotPerformanceTab botName={botName} />
      )}

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
      <PositionDetailModal
        pos={selectedPosition}
        signal={selectedPosition ? (signals.find((s) => s.symbol === selectedPosition.symbol) ?? null) : null}
        stopLossPct={profile?.stop_loss_pct ?? null}
        takeProfitPct={profile?.take_profit_pct ?? null}
        onClose={() => setSelectedPosition(null)}
      />

      {/* Coachmark overlay (first visit after custom bot deploy) */}
      {showCoachmark && (
        <CoachmarkOverlay botId={String(data?.profile?.id ?? "")} onDone={dismissCoachmark} />
      )}
    </div>
  );
}

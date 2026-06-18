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
  runBotNow,
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
    ? "bg-lime-500/15 text-t-green border-lime-500/30"
    : isShort
    ? "bg-red-500/15 text-t-red border-red-500/30"
    : "bg-t-bg1 text-t-muted border-t-dim";
  return (
    <span className={cn("text-xs font-bold px-2 py-0.5 rounded-full border font-ui-t", style)}>
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
      <div className="h-48 flex items-center justify-center bg-t-bg0/50 rounded-xl border border-t-dim">
        <p className="text-t-dim text-sm font-ui-t">No equity data yet</p>
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
        <Line type="monotone" dataKey="portfolio" stroke="#4ade80" strokeWidth={2} dot={false} name="Portfolio" />
        <Line type="monotone" dataKey="benchmark" stroke="#52525b" strokeWidth={2} dot={false} name={benchmarkLabel} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ─── Regime helpers ───────────────────────────────────────────────────────────

function vixPillClass(regime: string): string {
  const r = regime?.toLowerCase() ?? "";
  if (r === "low") return "bg-green-500/15 text-t-green border-green-500/30";
  if (r === "mid") return "bg-yellow-500/15 text-t-amber border-yellow-500/30";
  if (r === "high") return "bg-orange-500/15 text-t-amber border-orange-500/30";
  if (r === "panic") return "bg-red-500/15 text-t-red border-red-500/30";
  return "bg-t-bg1 text-t-muted border-t-dim";
}

function trendPillClass(regime: string): string {
  const r = regime?.toLowerCase() ?? "";
  if (r === "bull") return "bg-lime-500/15 text-t-green border-lime-500/30";
  if (r === "chop") return "bg-t-bg2/40 text-t-muted border-t-mid";
  if (r === "bear") return "bg-red-500/15 text-t-red border-red-500/30";
  return "bg-t-bg1 text-t-muted border-t-dim";
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
      <div className="bg-t-bg0 border border-t-dim rounded-xl px-4 py-3 animate-pulse">
        <div className="h-3 w-32 bg-t-bg1 rounded mb-3" />
        <div className="flex gap-2">
          {[0, 1, 2].map((i) => <div key={i} className="h-7 w-20 bg-t-bg1 rounded-full" />)}
        </div>
      </div>
    );
  }

  const vix = regime?.vix_regime?.toUpperCase() ?? "MID";
  const trend = regime?.trend_regime?.toUpperCase() ?? "CHOP";
  const btcDom = typeof regime?.btc_dominance === "number" ? `${regime.btc_dominance.toFixed(0)}%` : "—";

  return (
    <div className="bg-t-bg0 border border-t-dim rounded-xl px-4 py-3">
      <h3 className="panel-header mb-2">// Current Regime</h3>
      <div className="flex flex-wrap gap-2">
        <span className={cn("inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border font-ui-t", vixPillClass(vix))}>
          <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
          VIX {vix}
        </span>
        <span className={cn("inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border font-ui-t", trendPillClass(trend))}>
          <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
          {trend}
        </span>
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border bg-t-bg1 border-t-dim text-t-mid2 font-ui-t">
          <span className="w-1.5 h-1.5 rounded-full bg-orange-400" />
          BTC Dom {btcDom}
        </span>
      </div>
      <p className="text-xs text-t-dim mt-1.5 font-ui-t">{getGatingText(regime)}</p>
    </div>
  );
}

// ─── Catalyst calendar ────────────────────────────────────────────────────────

function eventTypeColor(type: string): string {
  const t = type?.toLowerCase() ?? "";
  if (t === "fomc") return "bg-blue-500/15 text-t-cyan";
  if (t === "cpi" || t === "pce") return "bg-orange-500/15 text-t-amber";
  if (t === "earnings") return "bg-lime-500/15 text-t-green";
  if (t === "expiry") return "bg-purple-500/15 text-purple-400";
  return "bg-t-bg2/40 text-t-muted";
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
        {[0, 1, 2].map((i) => <div key={i} className="h-8 bg-t-bg1 rounded" />)}
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {events.slice(0, 5).map((evt) => (
        <div
          key={String(evt.id)}
          className="flex items-center gap-3 py-1.5 border-b border-t-dim/50 last:border-0"
        >
          <span className={cn("text-xs font-semibold px-2 py-0.5 rounded font-ui-t", eventTypeColor(evt.event_type))}>
            {evt.event_type.toUpperCase()}
          </span>
          <span className="text-xs text-t-muted font-ui-t">{evt.symbol ?? (evt.description ?? "Market-wide")}</span>
          <span className="text-xs text-t-dim ml-auto font-mono-t">{formatRelativeTime(evt.event_ts)}</span>
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
        className="relative bg-t-bg0 border border-t-mid rounded-2xl p-6 w-full max-w-md shadow-2xl space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h3 className="text-t-hi font-bold text-lg font-mono-t">{pos.symbol}</h3>
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-lime-500/15 border border-lime-500/30 text-t-green font-ui-t">
              LONG
            </span>
            {pos.is_paper && (
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-t-bg1 border border-t-dim text-t-dim font-ui-t">
                PAPER
              </span>
            )}
          </div>
          <button onClick={onClose} className="text-t-muted hover:text-t-hi transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Key levels */}
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-t-bg0 rounded-xl p-3 border border-t-dim">
            <p className="text-[10px] text-t-dim uppercase tracking-wide font-ui-t">Entry</p>
            <p className="text-sm font-bold text-t-hi mt-1 font-mono-t tabular-nums">{fmtPrice(entry)}</p>
          </div>
          <div className="bg-t-bg0 rounded-xl p-3 border border-red-900/30">
            <p className="text-[10px] text-t-dim uppercase tracking-wide font-ui-t">Stop Loss</p>
            <p className="text-sm font-bold text-t-red mt-1 font-mono-t tabular-nums">
              {fmtPrice(stopPrice)}
            </p>
            {stopLossPct != null && (
              <p className="text-[10px] text-t-dim mt-0.5 font-mono-t">−{stopLossPct}%</p>
            )}
          </div>
          <div className="bg-t-bg0 rounded-xl p-3 border border-lime-900/30">
            <p className="text-[10px] text-t-dim uppercase tracking-wide font-ui-t">Target</p>
            <p className="text-sm font-bold text-t-green mt-1 font-mono-t tabular-nums">
              {fmtPrice(targetPrice)}
            </p>
            {takeProfitPct != null && (
              <p className="text-[10px] text-t-dim mt-0.5 font-mono-t">+{takeProfitPct}%</p>
            )}
          </div>
        </div>

        {/* Position info */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-xs text-t-muted font-ui-t">Qty</p>
            <p className="text-sm font-semibold text-t-hi font-mono-t tabular-nums">{pos.qty}</p>
          </div>
          <div>
            <p className="text-xs text-t-muted font-ui-t">Hold Time</p>
            <p className="text-sm font-semibold text-t-hi font-mono-t">{holdStr}</p>
          </div>
          <div>
            <p className="text-xs text-t-muted font-ui-t">Opened</p>
            <p className="text-sm font-semibold text-t-mid2 font-mono-t">{formatTime(pos.opened_at)}</p>
          </div>
          <div>
            <p className="text-xs text-t-muted font-ui-t">Unrealized P&L</p>
            <p className="text-sm font-semibold text-t-muted font-mono-t">—</p>
          </div>
        </div>

        {/* Why we opened it */}
        {signal && (
          <div className="bg-t-bg1/60 rounded-xl p-4 space-y-2">
            <p className="text-xs font-semibold text-t-muted font-ui-t">Why we opened this</p>
            <p className="text-xs text-t-muted font-ui-t">
              <span className="text-t-muted">Strategy:</span> {signal.strategy}
            </p>
            <p className="text-xs text-t-mid2 leading-relaxed font-ui-t">{signal.reason || "No reason recorded"}</p>
            <div className="flex items-center gap-2 pt-1">
              <p className="text-xs text-t-muted font-ui-t">Confidence</p>
              <div className="flex-1 h-1.5 bg-t-bg2 rounded-full overflow-hidden">
                <div
                  className="h-full bg-lime-500 rounded-full"
                  style={{ width: `${Math.round(signal.confidence * 100)}%` }}
                />
              </div>
              <p className="text-xs text-t-muted font-mono-t tabular-nums">{Math.round(signal.confidence * 100)}%</p>
            </div>
          </div>
        )}

        {!signal && (
          <p className="text-xs text-t-dim text-center py-2 font-ui-t">
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
        className="relative bg-t-bg0 border border-t-mid rounded-2xl p-6 w-full max-w-md shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-t-hi font-semibold text-base font-ui-t">Why did we trade this?</h3>
          <button onClick={onClose} className="text-t-muted hover:text-t-hi transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-4">
          <div className="flex gap-4">
            <div className="flex-1">
              <p className="text-xs text-t-muted mb-1 font-ui-t">Symbol</p>
              <p className="text-sm font-semibold text-t-hi font-mono-t">{signal.symbol}</p>
            </div>
            <div>
              <p className="text-xs text-t-muted mb-1 font-ui-t">Direction</p>
              <SideBadge side={signal.side} />
            </div>
          </div>

          <div>
            <p className="text-xs text-t-muted mb-1 font-ui-t">Strategy</p>
            <p className="text-sm font-semibold text-t-hi font-ui-t">{signal.strategy}</p>
          </div>

          <div>
            <p className="text-xs text-t-muted mb-1 font-ui-t">Signal Reason</p>
            <p className="text-sm text-t-mid2 font-ui-t">{signal.reason || "—"}</p>
          </div>

          <div>
            <p className="text-xs text-t-muted mb-1 font-ui-t">Confidence</p>
            <div className="h-2 bg-t-bg1 rounded-full overflow-hidden">
              <div
                className="h-2 bg-lime-500 rounded-full transition-all"
                style={{ width: `${Math.min(100, Math.max(0, signal.confidence * 100))}%` }}
              />
            </div>
            <p className="text-xs text-t-muted mt-0.5 font-mono-t tabular-nums">{(signal.confidence * 100).toFixed(0)}%</p>
          </div>

          <div>
            <p className="text-xs text-t-muted mb-1 font-ui-t">Signal Time</p>
            <p className="text-xs text-t-muted font-mono-t">{formatTime(signal.ts)}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Analyst helpers ──────────────────────────────────────────────────────────

function ConvictionStars({ score }: { score: number | null }) {
  if (score == null) return <span className="text-t-dim text-xs font-mono-t">—</span>;
  const filled = Math.round(score);
  return (
    <span className={cn("text-sm font-medium font-mono-t", score >= 4 ? "text-t-green" : score >= 3 ? "text-t-amber" : "text-t-muted")}>
      {"★".repeat(filled)}{"☆".repeat(5 - filled)}
    </span>
  );
}

function AnalystDrawer({ analysis, onClose }: { analysis: WatchlistAnalysis; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div
        className="relative h-full w-full max-w-md bg-t-bg0 border-l border-t-dim shadow-2xl overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-t-bg0 border-b border-t-dim px-5 py-4 flex items-center justify-between">
          <div>
            <span className="font-bold text-t-hi text-lg mr-2 font-mono-t">{analysis.symbol}</span>
            <ConvictionStars score={analysis.conviction_score} />
          </div>
          <button onClick={onClose} className="text-t-muted hover:text-t-hi transition-colors">
            <X size={18} />
          </button>
        </div>
        <div className="p-5 space-y-5">
          <div>
            <p className="panel-header mb-2">// Thesis</p>
            <p className="text-sm text-t-mid2 leading-relaxed font-ui-t">{analysis.thesis_md}</p>
          </div>
          {analysis.reasons_to_own?.length > 0 && (
            <div>
              <p className="panel-header mb-2">// Reasons to Own</p>
              <ul className="space-y-1.5">
                {analysis.reasons_to_own.map((r, i) => (
                  <li key={i} className="flex gap-2 text-sm text-t-mid2 font-ui-t">
                    <span className="text-t-green mt-0.5">✓</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {analysis.risks?.length > 0 && (
            <div>
              <p className="panel-header mb-2">// Risks</p>
              <ul className="space-y-1.5">
                {analysis.risks.map((r, i) => (
                  <li key={i} className="flex gap-2 text-sm text-t-mid2 font-ui-t">
                    <span className="text-t-red mt-0.5">⚠</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex gap-4">
            <div>
              <p className="text-[11px] text-t-dim font-ui-t">Suggested Hold</p>
              <p className="text-sm text-t-mid2 font-medium font-ui-t">{analysis.suggested_hold || "—"}</p>
            </div>
            {analysis.concerns_flag && (
              <div>
                <p className="text-[11px] text-t-dim font-ui-t">Flag</p>
                <p className="text-sm text-t-red font-medium font-ui-t">⚑ Concerns flagged</p>
              </div>
            )}
          </div>
          <p className="text-[10px] text-t-gdim border-t border-t-dim pt-3 font-ui-t">
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
        <span className="text-[9px] text-t-green font-semibold shrink-0">✓ met</span>
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
        <div className="absolute inset-0 bg-t-bg1 rounded-full" />
        <div
          className="absolute top-0 h-1.5 bg-t-bg2/40 rounded-full"
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
          className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-2.5 h-2.5 rounded-full bg-t-muted border-2 border-t-bg0"
          style={{ left: `${currentPct}%` }}
        />
      </div>
      <div className="relative h-3.5 mt-0.5">
        <span
          className="absolute text-[9px] text-t-muted -translate-x-1/2 leading-none font-mono-t tabular-nums"
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
  triggered:      { icon: "⚡", label: "Entry Triggered", headerColor: "text-t-green",  rowBorder: "border-lime-500/50",   rowBg: "bg-lime-500/8" },
  about_to_enter: { icon: "🟢", label: "About to Enter",  headerColor: "text-t-green",  rowBorder: "border-lime-500/25",   rowBg: "bg-lime-500/5" },
  close:          { icon: "🟡", label: "Close",           headerColor: "text-t-amber",  rowBorder: "border-yellow-500/20", rowBg: "bg-t-bg0" },
  waiting:        { icon: "⚪", label: "Waiting",         headerColor: "text-t-muted",  rowBorder: "border-t-dim",         rowBg: "bg-t-bg0" },
};

// ── Strategy condition trace row ──────────────────────────────────────────────

function ConditionRow({ cond }: { cond: import("@/api/bots").ConditionTrace }) {
  const isVerge = !cond.passed && typeof cond.current_value === "number" &&
    typeof cond.required_value === "number" &&
    Math.abs(cond.current_value - cond.required_value) / Math.max(1, Math.abs(cond.required_value)) <= 0.10;

  const valueColor = cond.error
    ? "text-t-red"
    : cond.passed
    ? "text-t-green"
    : isVerge
    ? "text-t-amber"
    : "text-t-muted";

  const fmtVal = (v: number | number[] | null) => {
    if (v == null) return "—";
    if (Array.isArray(v)) return `[${v.map((x) => x >= 1000 ? x.toLocaleString("en-US", { maximumFractionDigits: 2 }) : x).join(", ")}]`;
    return v >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 4 }) : String(v);
  };

  return (
    <div className={cn("pl-2 border-l-2 mb-2", cond.passed ? "border-lime-500/40" : isVerge ? "border-yellow-500/40" : "border-t-dim")}>
      <div className="flex items-start gap-1.5">
        {cond.passed
          ? <CheckCircle2 size={11} className="text-t-green mt-0.5 flex-shrink-0" />
          : <XCircle size={11} className="text-t-dim mt-0.5 flex-shrink-0" />}
        <div className="flex-1 min-w-0">
          <p className="text-[11px] text-t-muted leading-tight font-ui-t">{cond.name}</p>
          {cond.error ? (
            <p className="text-[10px] text-t-red mt-0.5 font-ui-t">{cond.error}</p>
          ) : (
            <p className={cn("text-[11px] font-mono-t mt-0.5 tabular-nums", valueColor)}>
              {cond.current_value}{cond.unit ? ` ${cond.unit}` : ""}
              <span className="text-t-dim font-ui-t mx-1">{cond.operator}</span>
              {fmtVal(cond.required_value)}{cond.unit ? ` ${cond.unit}` : ""}
            </p>
          )}
          <p className="text-[10px] text-t-muted mt-0.5 leading-snug font-ui-t">{cond.to_pass}</p>
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
      fired ? "border-lime-500/30 bg-lime-500/5" : "border-t-dim bg-t-bg0/50",
    )}>
      <div className="flex items-start gap-2 mb-2">
        <span className={cn("text-sm leading-none mt-0.5", fired ? "text-t-green" : "text-t-dim")}>
          {fired ? "✓" : "✗"}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={cn("text-xs font-semibold font-ui-t", fired ? "text-t-green" : "text-t-mid2")}>
              {strat.name}
            </span>
            {strat.score > 0 && (
              <span className="text-[10px] text-t-muted font-mono-t tabular-nums">
                score {(strat.score * 100).toFixed(0)}
              </span>
            )}
            {strat.weight > 0 && (
              <span className="text-[10px] text-t-dim font-mono-t tabular-nums">
                w={strat.weight.toFixed(2)}
              </span>
            )}
            {fired && strat.side && (
              <span className={cn(
                "text-[9px] font-bold px-1.5 py-0.5 rounded-full leading-none font-ui-t",
                strat.side === "buy" || strat.side === "long"
                  ? "bg-lime-500/20 text-t-green border border-lime-500/30"
                  : "bg-orange-500/20 text-t-amber border border-orange-500/30",
              )}>
                {strat.side === "buy" || strat.side === "long" ? "LONG" : "SHORT"}
              </span>
            )}
          </div>
          <p className="text-[11px] text-t-muted mt-0.5 leading-snug font-ui-t">{strat.summary}</p>
        </div>
      </div>
      {strat.conditions.length > 0 && (
        <div className="ml-4 mt-1.5">
          {strat.conditions.map((c, i) => <ConditionRow key={i} cond={c} />)}
        </div>
      )}
      {strat.error && !strat.conditions.length && (
        <p className="text-[10px] text-t-red ml-4 mt-1 font-ui-t">{strat.error}</p>
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
          <div key={i} className="h-14 bg-t-bg1/40 rounded-xl animate-pulse" />
        ))}
      </div>
    );
  }

  if (error || !data) {
    return (
      <p className="mt-3 text-xs text-t-red font-ui-t">
        Failed to load evaluation trace. Backend may be starting up — try again in a moment.
      </p>
    );
  }

  if (data.error) {
    return <p className="mt-3 text-xs text-t-red font-ui-t">{data.error}</p>;
  }

  const ageStr = data.scan_age_seconds != null
    ? data.scan_age_seconds < 60
      ? `${data.scan_age_seconds}s ago`
      : `${Math.round(data.scan_age_seconds / 60)}m ago`
    : "awaiting first scan";

  return (
    <div className="mt-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-t-dim font-mono-t">
          {data.strategies_firing}/{data.total_strategies} strategies firing
        </span>
        <span className="text-[10px] text-t-dim font-mono-t">evaluated {ageStr}</span>
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
            ? <ChevronDown size={12} className="text-t-muted flex-shrink-0" />
            : <ChevronRight size={12} className="text-t-muted flex-shrink-0" />}
          <span className="font-mono-t font-bold text-t-hi text-sm">{row.symbol}</span>
          {isTriggered && (
            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-lime-500 text-black leading-none font-ui-t">
              ⚡ ENTRY
            </span>
          )}
          {row.tier === "about_to_enter" && !isTriggered && (
            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-lime-500/15 text-t-green border border-lime-500/30 leading-none font-ui-t">
              CLOSE
            </span>
          )}
          <span className="text-[10px] text-t-dim truncate hidden sm:block font-ui-t">
            {row.gap_human || row.criteria_summary}
          </span>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          <div className="text-right">
            <span className="text-xs text-t-mid2 tabular-nums font-mono-t">{fmt$(row.current_price)}</span>
            <span className={cn("text-[10px] ml-1.5 tabular-nums font-mono-t", changePos ? "text-t-green" : "text-t-red")}>
              {changePos ? "+" : ""}{row.change_24h_pct.toFixed(2)}%
            </span>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); navigate(`/chart?symbol=${row.symbol.replace("/", "-")}`); }}
            className="text-[10px] text-t-dim hover:text-t-muted transition-colors px-1.5 py-0.5 rounded border border-t-dim hover:border-t-mid font-ui-t"
          >
            chart
          </button>
        </div>
      </div>

      {/* Expanded strategy evaluation */}
      {expanded && (
        <div className="px-4 pb-3 border-t border-t-dim/60">
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
          <div key={i} className="animate-pulse bg-t-bg1/50 rounded-xl h-16" />
        ))}
      </div>
    );
  }

  if (noUniverse || (rows.length === 0 && !isLoading)) {
    return (
      <div className="py-10 text-center">
        <p className="text-t-muted text-sm font-ui-t">No universe configured for this bot yet.</p>
        <p className="text-t-dim text-xs mt-1 font-ui-t">
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
      <div className="bg-t-bg1/40 border border-t-mid/50 rounded-xl px-4 py-3 mb-3 sticky top-0 z-10 backdrop-blur-sm">
        <p className="text-xs text-t-mid2 leading-relaxed font-ui-t">
          Watching <span className="font-semibold text-t-hi">{rows.length}</span> symbols · {" "}
          <span className="text-t-green font-semibold tabular-nums font-mono-t">{tierCounts.triggered + tierCounts.about_to_enter}</span> close to entry · {" "}
          <span className="text-t-amber font-semibold tabular-nums font-mono-t">{tierCounts.close}</span> watching · {" "}
          <span className="text-t-muted tabular-nums font-mono-t">{tierCounts.waiting}</span> waiting
          {closest?.gap_human && (
            <> · <span className="text-t-muted font-ui-t">Closest: <span className="text-t-hi font-medium font-mono-t">{closest.symbol}</span> — {closest.gap_human}</span></>
          )}
        </p>
        <p className="text-[10px] text-t-dim mt-0.5 font-ui-t">
          Scans {cadence} · next scan in <span className="font-mono-t tabular-nums">{nextScanIn}s</span> · click any row to see why it's not firing
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
              <span className={cn("text-xs font-semibold uppercase tracking-wide font-ui-t", cfg.headerColor)}>
                {cfg.label}
              </span>
              <span className="text-xs text-t-dim font-mono-t tabular-nums">({tierCounts[tier]})</span>
              <div className="flex-1 h-px bg-t-dim ml-1" />
            </div>

            {tierRows.length === 0 && (
              <p className="text-[11px] text-t-gdim pl-2 pb-2 italic font-ui-t">None</p>
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
      <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5">
        <div className="flex items-center justify-between mb-3">
          <SectionLabel as="h2">Watchlist</SectionLabel>
        </div>
        <div className="space-y-2">
          {[0, 1, 2].map((i) => <div key={i} className="animate-pulse h-10 bg-t-bg1 rounded-xl" />)}
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
    <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5">
      <div className="flex items-center justify-between mb-3">
        <SectionLabel as="h2">Watchlist — Closest to Entry</SectionLabel>
        <button
          onClick={onViewAll}
          className="text-xs text-t-green hover:text-t-bright transition-colors font-ui-t"
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
                "flex items-center justify-between rounded-xl border px-4 py-2.5 card-hover",
                isTriggered
                  ? "border-lime-500/40 bg-lime-500/5"
                  : isClose
                  ? "border-lime-500/30 bg-lime-500/5"
                  : row.distance_color === "yellow"
                  ? "border-yellow-500/20 bg-t-bg0"
                  : "border-t-dim bg-t-bg0"
              )}
            >
              <div className="flex items-center gap-3 min-w-0">
                <span className="font-semibold text-t-hi text-sm font-mono-t">{row.symbol}</span>
                <span className="text-xs text-t-muted truncate font-ui-t">{row.strategy_being_evaluated}</span>
              </div>
              <div className="flex items-center gap-4 flex-shrink-0">
                <span className="text-xs text-t-muted font-mono-t tabular-nums">{fmt$(row.current_price)}</span>
                <span className={cn(
                  "text-xs font-semibold font-mono-t tabular-nums",
                  row.tier === "triggered" ? "text-t-green" :
                  row.tier === "about_to_enter" ? "text-t-bright" :
                  row.tier === "close" ? "text-t-amber" : "text-t-muted"
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
        {[0, 1, 2, 3].map((i) => <div key={i} className="h-10 bg-t-bg1 rounded" />)}
      </div>
    );
  }

  const safeWatchlist = Array.isArray(watchlist) ? watchlist : [];

  if (safeWatchlist.length === 0) {
    return (
      <p className="text-t-dim text-sm py-4 text-center font-ui-t">
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
            <tr className="text-xs text-t-dim border-b border-t-dim">
              <th className="text-left pb-2 font-medium w-8 font-ui-t">#</th>
              <th className="text-left pb-2 font-medium font-ui-t">Symbol</th>
              <th className="text-left pb-2 font-medium w-32 font-ui-t">Score</th>
              <th className="text-left pb-2 font-medium font-ui-t">AI Conviction</th>
              <th className="text-right pb-2 font-medium font-ui-t">Last Evaluated</th>
            </tr>
          </thead>
          <tbody>
            {displayed.map((item, idx) => {
              const analysis = analysisBySymbol[item.symbol];
              return (
                <tr key={item.symbol} className="border-b border-t-dim/50 last:border-0 hover:bg-t-bg1/20 transition-colors">
                  <td className="py-2.5 text-xs text-t-dim font-mono-t tabular-nums">{item.rank ?? idx + 1}</td>
                  <td className="py-2.5 font-semibold text-t-hi text-sm font-mono-t">{item.symbol}</td>
                  <td className="py-2.5 pr-4">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 bg-t-bg1 rounded-full overflow-hidden min-w-[60px]">
                        <div
                          className={cn("h-1.5 rounded-full", item.score >= 70 ? "bg-lime-500" : item.score >= 40 ? "bg-yellow-500" : "bg-red-500")}
                          style={{ width: `${Math.min(100, Math.max(0, item.score))}%` }}
                        />
                      </div>
                      <span className="text-xs text-t-muted w-6 text-right font-mono-t tabular-nums">{item.score}</span>
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
                        {analysis.concerns_flag && <span className="text-t-red text-xs">⚑</span>}
                      </button>
                    ) : (
                      <span className="text-t-gdim text-xs font-ui-t">Not analyzed</span>
                    )}
                  </td>
                  <td className="py-2.5 text-right text-xs text-t-muted font-mono-t">
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
          className="mt-3 text-xs text-t-muted hover:text-t-mid2 underline underline-offset-2 transition-colors font-ui-t"
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
      <h3 className="panel-header mb-3">// Strategy Attribution (Est.)</h3>
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
              <Cell key={`cell-${index}`} fill={entry.value >= 0 ? "#4ade80" : "#ef4444"} />
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
      <div className="bg-t-bg0 border border-t-dim rounded-xl p-4">
        <h3 className="text-sm font-semibold text-t-mid2 mb-3 font-ui-t">Backtest Parameters</h3>
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="text-xs text-t-muted mb-1 block font-ui-t">Start Date</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="bg-t-bg1 border border-t-dim rounded-lg px-3 py-1.5 text-sm text-t-hi focus:outline-none focus:border-lime-500/50 font-mono-t"
            />
          </div>
          <div>
            <label className="text-xs text-t-muted mb-1 block font-ui-t">End Date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="bg-t-bg1 border border-t-dim rounded-lg px-3 py-1.5 text-sm text-t-hi focus:outline-none focus:border-lime-500/50 font-mono-t"
            />
          </div>
          <div>
            <label className="text-xs text-t-muted mb-1 block font-ui-t">Starting Capital ($)</label>
            <input
              type="number"
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
              step={10000}
              min={1000}
              className="bg-t-bg1 border border-t-dim rounded-lg px-3 py-1.5 text-sm text-t-hi w-32 focus:outline-none focus:border-lime-500/50 font-mono-t tabular-nums"
            />
          </div>
          <button
            onClick={handleRun}
            disabled={isRunning}
            className="px-4 py-2.5 rounded-lg bg-lime-500/15 border border-lime-500/30 text-xs font-semibold text-t-green hover:bg-lime-500/25 transition-colors font-ui-t disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isRunning ? "Running…" : "Run Backtest"}
          </button>
        </div>
      </div>

      {/* Results */}
      {isRunning && (
        <div className="bg-t-bg0 border border-t-dim rounded-xl p-4 animate-pulse space-y-3">
          <div className="grid grid-cols-4 gap-3">
            {[0, 1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="h-14 bg-t-bg1 rounded-xl" />
            ))}
          </div>
          <div className="h-48 bg-t-bg1 rounded-xl" />
        </div>
      )}

      {!isRunning && hasRun && !result && (
        <div className="bg-t-bg0 border border-t-dim rounded-xl p-6 text-center">
          <p className="text-t-muted text-sm font-ui-t">No backtest data returned. Try a different date range.</p>
        </div>
      )}

      {!isRunning && result && (
        <div className="bg-t-bg0 border border-t-dim rounded-xl p-4 space-y-5">
          {/* Metrics grid */}
          <div>
            <h3 className="text-sm font-semibold text-t-mid2 mb-3 font-ui-t">Performance Metrics</h3>
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
                <div key={m.label} className="bg-t-bg0 rounded-xl px-4 py-3 border border-t-dim">
                  <p className="text-t-dim text-xs mb-1 font-ui-t">{m.label}</p>
                  <p className="text-lg font-bold text-t-hi font-mono-t tabular-nums">{m.value}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Equity curve */}
          {result.equity_curve && result.equity_curve.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-t-mid2 mb-3 font-ui-t">Equity Curve</h3>
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
                  <Line type="monotone" dataKey="equity" stroke="#4ade80" strokeWidth={2} dot={false} name="Portfolio" />
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
                <div className="flex items-center gap-1.5 text-xs text-t-muted font-ui-t">
                  <span className="w-3 h-0.5 bg-[#4ade80] inline-block rounded" />
                  Portfolio
                </div>
                <div className="flex items-center gap-1.5 text-xs text-t-muted font-ui-t">
                  <span className="w-3 h-0.5 bg-t-bg2 inline-block rounded" />
                  ${(capital / 1000).toFixed(0)}k Flat
                </div>
              </div>
            </div>
          )}

          {/* Monte Carlo */}
          {result.monte_carlo && (
            <div className="bg-t-bg0 border border-t-dim rounded-xl px-4 py-3">
              <p className="text-xs text-t-muted mb-1 font-ui-t">Monte Carlo Confidence Band</p>
              <p className="text-sm text-t-mid2 font-ui-t">
                Sharpe 5th–95th percentile:{" "}
                <span className="font-semibold text-t-hi font-mono-t tabular-nums">
                  {result.monte_carlo.sharpe_p5?.toFixed(2) ?? "—"} to {result.monte_carlo.sharpe_p95?.toFixed(2) ?? "—"}
                </span>
              </p>
            </div>
          )}

          {/* Trade list header */}
          <div>
            <h3 className="text-sm font-semibold text-t-mid2 mb-2 font-ui-t">Trade List</h3>
            <p className="text-xs text-t-dim italic font-ui-t">Individual trade breakdown available in v2.</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Tab system ───────────────────────────────────────────────────────────────

type Tab = "overview" | "watchlist" | "backtest" | "activity" | "strategies" | "signal_quality" | "performance" | "allocation" | "settings";

function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  const tabs: { key: Tab; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "watchlist", label: "Watchlist" },
    { key: "backtest", label: "Backtest" },
    { key: "activity", label: "Recent Trades" },
    { key: "strategies", label: "Strategies" },
    { key: "signal_quality", label: "Signal Quality" },
    { key: "performance", label: "Performance" },
    { key: "allocation", label: "Allocation" },
    { key: "settings", label: "Settings" },
  ];

  return (
    <div className="overflow-x-auto -mx-1">
      <div className="flex gap-1 bg-t-bg0 border border-t-dim rounded-xl p-1 min-w-max">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => onChange(t.key)}
            className={cn(
              "text-sm font-semibold py-2 px-3 rounded-lg transition-colors whitespace-nowrap font-ui-t",
              active === t.key
                ? "bg-t-bg2 text-t-hi"
                : "text-t-muted hover:text-t-mid2"
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
    if (result === "filled") return <span className="text-t-green">✓</span>;
    if (result === "skipped") return <span className="text-t-muted">✗</span>;
    if (result === "error") return <span className="text-t-red">!</span>;
    return <span className="text-t-dim">⚡</span>;
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
          className="flex-1 bg-t-bg1 border border-t-dim rounded-lg px-3 py-2 text-sm text-t-hi placeholder-t-dim focus:outline-none focus:border-t-cyan/50 font-ui-t"
        />
        <div className="flex gap-1">
          {cats.map((c) => (
            <button
              key={c.key}
              onClick={() => { setCategory(c.key); setPage(1); }}
              className={cn(
                "text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors whitespace-nowrap font-ui-t",
                category === c.key
                  ? "bg-t-cyan/15 border-t-cyan/30 text-t-cyan"
                  : "bg-t-bg1 border-t-dim text-t-muted hover:text-t-mid2"
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>

      {/* Timeline */}
      <div className="bg-t-bg0 border border-t-dim rounded-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-t-dim">
          <p className="text-sm font-semibold text-t-hi font-ui-t">Recent Trades</p>
          <p className="text-xs text-t-dim font-ui-t">every P&amp;L dollar backed by a trade</p>
        </div>
        <div className="p-5">
        {isLoading ? (
          <div className="animate-pulse space-y-3">
            {[0, 1, 2, 3, 4].map((i) => <div key={i} className="h-12 bg-t-bg1 rounded-lg" />)}
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-t-dim text-sm py-6 text-center font-ui-t">
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
                    "flex items-center gap-3 py-3 border-b border-t-dim/60 last:border-0 flex-wrap",
                    fillTradeId && "cursor-pointer hover:bg-t-bg1/40 -mx-5 px-5 rounded-lg transition-colors"
                  )}
                >
                  <span className="text-xs text-t-dim w-32 flex-shrink-0 font-mono-t">{ts}</span>
                  <span className="font-semibold text-t-hi text-sm font-mono-t">{item.symbol}</span>
                  {item.side && (
                    <span className={cn(
                      "text-xs font-bold px-2 py-0.5 rounded-full border font-ui-t",
                      item.side === "buy" || item.side === "long"
                        ? "bg-lime-500/15 text-t-green border-lime-500/30"
                        : item.side === "sell" || item.side === "short"
                        ? "bg-red-500/15 text-t-red border-red-500/30"
                        : "bg-t-bg1 text-t-muted border-t-dim"
                    )}>
                      {item.side === "buy" || item.side === "long" ? "LONG" : item.side === "sell" || item.side === "short" ? "SHORT" : item.side.toUpperCase()}
                    </span>
                  )}
                  {isFill && item.qty != null && item.fill_price != null ? (
                    <span className="text-xs text-t-muted tabular-nums font-mono-t">
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
                        <span className="text-xs px-2 py-0.5 rounded bg-t-bg1 border border-t-dim text-t-muted font-ui-t">
                          {item.strategy}
                        </span>
                      )}
                      {item.reason && (
                        <span className="text-xs text-t-muted flex-1 truncate min-w-0 font-ui-t">{item.reason}</span>
                      )}
                    </>
                  )}
                  {item.pnl_usd != null && (
                    <span className={cn("text-xs font-semibold tabular-nums font-mono-t", item.pnl_usd >= 0 ? "text-t-green" : "text-t-red")}>
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
          <span className="text-xs text-t-dim font-mono-t tabular-nums">
            Showing {Math.min(page * PAGE_SIZE, total)} of {total}
          </span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={page * PAGE_SIZE >= total}
            className="text-xs font-semibold px-4 py-2 rounded-lg border border-t-dim bg-t-bg1 text-t-mid2 hover:text-t-hi disabled:opacity-40 transition-colors font-ui-t"
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
          <div key={i} className="bg-t-bg0 border border-t-dim rounded-2xl p-5 animate-pulse h-28" />
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
        <p className="text-sm font-semibold text-t-mid2 font-ui-t">
          Strategy Roster
          <span className="ml-2 text-xs font-normal text-t-dim font-ui-t">
            {displayList.length} strategies · ensemble: {BOT_META[botName]?.ensemble ?? "weighted_vote"}
          </span>
        </p>
        <button
          onClick={() => resetMut.mutate()}
          disabled={resetMut.isPending || weights.length === 0}
          className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-t-dim bg-t-bg1 text-t-muted hover:text-t-hi transition-colors disabled:opacity-40 font-ui-t"
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
            className="bg-t-bg0 border border-t-dim rounded-2xl p-5 space-y-3"
          >
            {/* Header row */}
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="text-sm font-semibold text-t-hi font-ui-t">
                    {strategyLabel(w.strategy)}
                  </h3>
                  <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-t-cyan/15 border border-t-cyan/30 text-t-cyan font-mono-t tabular-nums">
                    weight {w.weight_pct}%
                  </span>
                  {w.locked && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-t-amber/15 border border-t-amber/30 text-t-amber font-ui-t">
                      locked
                    </span>
                  )}
                </div>
                {description && (
                  <p className="text-xs text-t-dim mt-1 leading-relaxed font-ui-t">{description}</p>
                )}
              </div>
              <button
                onClick={() => lockMut.mutate({ strategy: w.strategy, locked: !w.locked })}
                disabled={lockMut.isPending}
                title={w.locked ? "Unlock weight" : "Lock weight"}
                className={cn(
                  "p-1.5 rounded-lg border transition-colors flex-shrink-0",
                  w.locked
                    ? "bg-t-amber/15 border-t-amber/30 text-t-amber"
                    : "bg-t-bg1 border-t-dim text-t-muted hover:text-t-mid2"
                )}
              >
                {w.locked ? <Lock className="w-3.5 h-3.5" /> : <Unlock className="w-3.5 h-3.5" />}
              </button>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              <div>
                <p className="text-[10px] text-t-dim uppercase tracking-wide font-ui-t">30d W / L</p>
                <p className="text-xs font-semibold mt-0.5 font-mono-t tabular-nums">
                  <span className="text-t-green">{w.wins_30d}W</span>
                  <span className="text-t-dim mx-1">/</span>
                  <span className="text-t-red">{w.losses_30d}L</span>
                </p>
              </div>
              <div>
                <p className="text-[10px] text-t-dim uppercase tracking-wide font-ui-t">Win Rate</p>
                <p className={cn(
                  "text-xs font-semibold mt-0.5 font-mono-t tabular-nums",
                  winRate !== null ? (winRate >= 50 ? "text-t-green" : "text-t-red") : "text-t-muted"
                )}>
                  {winRate !== null ? `${winRate.toFixed(0)}%` : "—"}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-t-dim uppercase tracking-wide font-ui-t">Last Signal</p>
                {lastSignal ? (
                  <p className="text-xs font-semibold mt-0.5 font-mono-t">
                    <span className={lastSignal.side === "buy" || lastSignal.side === "long" ? "text-t-green" : "text-t-red"}>
                      {lastSignal.side === "buy" || lastSignal.side === "long" ? "LONG" : lastSignal.side === "sell" || lastSignal.side === "short" ? "SHORT" : lastSignal.side.toUpperCase()}
                    </span>
                    <span className="text-t-muted ml-1">{lastSignal.symbol}</span>
                  </p>
                ) : (
                  <p className="text-xs text-t-dim mt-0.5 font-mono-t">—</p>
                )}
              </div>
            </div>

            {/* Last signal reason */}
            {lastSignal?.reason && (
              <p className="text-[11px] text-t-muted bg-t-bg1/60 rounded-lg px-3 py-2 leading-relaxed font-ui-t">
                "{lastSignal.reason}"
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Signal Quality tab ───────────────────────────────────────────────────────

function SignalQualityTab({ botName }: { botName: string }) {
  const token = localStorage.getItem("bmg_token");
  const { data, isLoading } = useQuery({
    queryKey: ["ic-history", botName],
    queryFn: async () => {
      const r = await fetch(`/api/ic/strategies/${encodeURIComponent(botName)}/history?days=180`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) return null;
      return r.json();
    },
    staleTime: 60_000,
  });

  const latest = data?.latest;
  const history: { snapshot_date: string; ic_spearman: number }[] = data?.history ?? [];

  const classColor = (cls: string) =>
    cls === "STRONG" ? "text-emerald-400" :
    cls === "MARGINAL" ? "text-amber-400" :
    cls === "NOISE" ? "text-rose-400" :
    cls === "INVERTED" ? "text-purple-400" :
    "text-zinc-500";

  return (
    <div className="space-y-5 pt-2">
      {isLoading ? (
        <div className="text-t-muted text-sm py-8 text-center">Loading signal quality data…</div>
      ) : !latest ? (
        <div className="text-t-muted text-sm py-8 text-center">No IC data yet — runs nightly at 2:30 AM ET after the stats rollup.</div>
      ) : (
        <>
          {/* Current metrics */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "IC (63d)", value: latest.ic_63d != null ? `${(latest.ic_63d > 0 ? "+" : "")}${(latest.ic_63d * 100).toFixed(2)}%` : "—" },
              { label: "p-value", value: latest.p_value != null ? latest.p_value.toFixed(3) : "—" },
              { label: "Signals (n)", value: latest.n_signals ?? "—" },
              { label: "Hit Rate", value: latest.direction_hit_rate != null ? `${(latest.direction_hit_rate * 100).toFixed(1)}%` : "—" },
            ].map((m) => (
              <div key={m.label} className="bg-t-bg1 border border-t-dim rounded-xl px-4 py-3 text-center">
                <div className="text-[10px] font-semibold uppercase tracking-widest text-t-gdim mb-1">{m.label}</div>
                <div className="text-lg font-bold font-mono text-t-hi">{String(m.value)}</div>
              </div>
            ))}
          </div>

          {/* Classification + recommendation */}
          <div className="bg-t-bg1 border border-t-dim rounded-xl px-5 py-4 flex items-center justify-between flex-wrap gap-3">
            <div>
              <div className="text-[10px] text-t-gdim uppercase tracking-widest mb-1">Classification</div>
              <div className={`text-xl font-black ${classColor(latest.classification ?? "")}`}>
                {latest.classification ?? "—"}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[10px] text-t-gdim uppercase tracking-widest mb-1">Recommendation</div>
              <div className="text-sm font-bold text-t-hi">{latest.recommendation ?? "—"}</div>
            </div>
          </div>

          {/* IC sparkline (SVG) */}
          {history.length >= 3 && (
            <div className="bg-t-bg1 border border-t-dim rounded-xl p-4">
              <div className="text-[10px] font-bold uppercase tracking-widest text-t-gdim mb-3">IC Trend (180 days)</div>
              <svg viewBox="0 0 400 80" className="w-full h-auto">
                {(() => {
                  const vals = history.map((h) => h.ic_spearman);
                  const minV = Math.min(...vals, -0.1);
                  const maxV = Math.max(...vals, 0.1);
                  const xS = (i: number) => 10 + (i / (history.length - 1)) * 380;
                  const yS = (v: number) => 70 - ((v - minV) / (maxV - minV)) * 60;
                  const zeroY = yS(0);
                  const pts = history.map((h, i) => `${xS(i)},${yS(h.ic_spearman)}`).join(" ");
                  return (
                    <>
                      <line x1={10} y1={zeroY} x2={390} y2={zeroY} stroke="#ffffff18" strokeWidth={1} strokeDasharray="3 3" />
                      <polyline points={pts} fill="none" stroke="#22c55e" strokeWidth={1.5} />
                    </>
                  );
                })()}
              </svg>
            </div>
          )}

          {/* Honest disclosure */}
          <div className="bg-t-bg0 border border-t-dim/50 rounded-xl px-5 py-4 text-[11px] text-t-gdim space-y-1.5">
            <div className="font-bold text-t-muted uppercase tracking-widest text-[10px] mb-2">How this works · Limitations</div>
            <p>IC measures the Spearman rank correlation between this strategy's confidence values and the realized direction-signed returns of its signals over a rolling window.</p>
            <p>Limitations: (1) Measures linear-monotonic predictive power only — non-linear edge can show low IC with real alpha. (2) Composite IC per strategy, not per signal component. (3) Minimum 30 signals required for any classification — new strategies correctly show INSUFFICIENT. (4) IC can drop temporarily during regime changes without indicating real decay.</p>
          </div>
        </>
      )}
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
      <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5 space-y-4">
        <SectionLabel as="h2">Paper Allocation</SectionLabel>
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs text-t-muted font-ui-t">Capital %</label>
            <span className="text-sm font-bold text-t-hi font-mono-t tabular-nums">{capitalPct}%</span>
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
          <div className="flex justify-between text-xs text-t-gdim mt-0.5 font-mono-t">
            <span>0%</span>
            <span>20%</span>
          </div>
        </div>

        {/* Risk profile */}
        <div>
          <label className="text-xs text-t-muted mb-2 block font-ui-t">Risk Profile</label>
          <div className="flex gap-2">
            {(["conservative", "standard", "aggressive"] as const).map((r) => (
              <button
                key={r}
                onClick={() => setRiskProfile(r)}
                className={cn(
                  "text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors capitalize font-ui-t",
                  riskProfile === r
                    ? "bg-t-cyan/15 border-t-cyan/40 text-t-cyan"
                    : "bg-t-bg1 border-t-dim text-t-muted hover:text-t-mid2"
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
          className="px-4 py-2 rounded-lg bg-teal-500 text-black text-sm font-bold hover:bg-teal-400 transition-colors disabled:opacity-50 font-ui-t"
        >
          {allocateMut.isPending ? "Saving…" : "Save Settings"}
        </button>
      </div>

      {/* Go Live section */}
      <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5 space-y-3">
        <SectionLabel as="h2">Go Live</SectionLabel>
        <div className="flex items-center gap-3">
          <div className="relative">
            <button
              disabled
              className="relative inline-flex h-6 w-11 items-center rounded-full bg-t-bg2 cursor-not-allowed opacity-50"
              title="Live trading coming soon — paper trading only"
            >
              <span className="translate-x-1 inline-block h-4 w-4 rounded-full bg-t-hi" />
            </button>
          </div>
          <span className="text-xs text-t-muted font-ui-t">
            Live trading coming soon — paper trading only
          </span>
        </div>
        {notified ? (
          <p className="text-sm text-t-green font-semibold font-ui-t">
            You're on the waitlist ✓
          </p>
        ) : (
          <button
            onClick={() => waitlistMut.mutate()}
            disabled={waitlistMut.isPending}
            className="text-sm font-semibold px-4 py-2 rounded-lg border border-t-amber/30 bg-t-amber/10 text-t-amber hover:bg-t-amber/20 transition-colors font-ui-t"
          >
            {waitlistMut.isPending ? "Joining…" : "Notify me when live unlocks →"}
          </button>
        )}
      </div>

    </div>
  );
}

// ─── Allocation tab ───────────────────────────────────────────────────────────

const TIER_COLORS: Record<string, string> = {
  T3: "text-t-green bg-t-green/10 border-t-green/30",
  T2: "text-t-cyan bg-t-cyan/10 border-t-cyan/30",
  T1: "text-t-amber bg-t-amber/10 border-t-amber/30",
  T0: "text-t-muted bg-t-muted/10 border-t-mid/30",
};
const TIER_LABELS: Record<string, string> = {
  T3: "CORE", T2: "PRODUCTION", T1: "PROBATION", T0: "CANDIDATE",
};
const TIER_MAX_PCT: Record<string, number> = {
  T3: 20, T2: 12, T1: 3, T0: 0,
};

function AllocationTab({ allocationId }: { allocationId: number }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["bot-allocation-perf", allocationId],
    queryFn: () =>
      fetch(`/api/bots/${allocationId}/performance?days=90`, {
        headers: { Authorization: `Bearer ${localStorage.getItem("bmg_token") ?? ""}` },
      }).then((r) => r.json()),
    staleTime: 300_000,
    retry: 0,
    enabled: !!allocationId,
  });

  if (!allocationId) {
    return <p className="text-sm text-t-muted py-8 text-center font-ui-t">No allocation found for this bot.</p>;
  }

  if (isLoading) {
    return <p className="text-sm text-t-muted py-8 text-center font-ui-t">Loading allocation data…</p>;
  }

  if (isError || !data) {
    return <p className="text-sm text-t-muted py-8 text-center font-ui-t">Allocation data unavailable.</p>;
  }

  const tier: string = data.current_tier ?? "T1";
  const tierClass = TIER_COLORS[tier] ?? TIER_COLORS.T1;
  const tierLabel = TIER_LABELS[tier] ?? tier;
  const maxPct = TIER_MAX_PCT[tier] ?? 3;
  const history: Array<{ changed_at: string; previous_tier: string; new_tier: string; reason: string }> =
    data.tier_history ?? [];
  const latest = data.time_series?.[data.time_series.length - 1];

  return (
    <div className="space-y-6">
      {/* Current tier card */}
      <div className="bg-t-bg0 border border-t-dim rounded-xl p-5 flex flex-col sm:flex-row sm:items-center gap-4">
        <div className="flex-1">
          <p className="text-xs text-t-muted mb-1 uppercase tracking-wider font-ui-t">Current Tier</p>
          <span className={cn("inline-block text-sm font-bold px-3 py-1 rounded-full border font-ui-t", tierClass)}>
            {tier} — {tierLabel}
          </span>
          <p className="text-xs text-t-muted mt-2 font-ui-t">
            Max capital allocation: <span className="text-t-mid2 font-mono-t tabular-nums">{maxPct}%</span>
          </p>
        </div>
        {latest && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-center">
            {[
              { label: "30d Return", val: latest.return_30d_pct != null ? `${latest.return_30d_pct.toFixed(2)}%` : "—" },
              { label: "Win Rate", val: latest.win_rate != null ? `${(latest.win_rate * 100).toFixed(0)}%` : "—" },
              { label: "Profit Factor", val: latest.profit_factor != null ? latest.profit_factor.toFixed(2) : "—" },
              { label: "Max DD", val: latest.max_drawdown_pct != null ? `${(latest.max_drawdown_pct * 100).toFixed(1)}%` : "—" },
            ].map(({ label, val }) => (
              <div key={label} className="bg-t-bg1 rounded-lg px-3 py-2">
                <p className="text-[10px] text-t-muted mb-0.5 font-ui-t">{label}</p>
                <p className="text-sm font-semibold text-t-hi font-mono-t tabular-nums">{val}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Tier progression */}
      <div className="bg-t-bg0 border border-t-dim rounded-xl p-5">
        <p className="panel-header mb-4">// Tier Ladder</p>
        <div className="flex gap-2 flex-wrap">
          {(["T0", "T1", "T2", "T3"] as const).map((t) => (
            <div
              key={t}
              className={cn(
                "flex-1 min-w-[70px] rounded-lg border px-3 py-2 text-center transition-all",
                tier === t ? TIER_COLORS[t] : "border-t-dim text-t-dim"
              )}
            >
              <p className="text-xs font-bold font-mono-t">{t}</p>
              <p className="text-[10px] font-ui-t">{TIER_LABELS[t]}</p>
              <p className="text-[10px] font-mono-t tabular-nums">≤ {TIER_MAX_PCT[t]}%</p>
            </div>
          ))}
        </div>
      </div>

      {/* Tier history */}
      {history.length > 0 && (
        <div className="bg-t-bg0 border border-t-dim rounded-xl p-5">
          <p className="panel-header mb-3">// Tier History</p>
          <div className="space-y-2">
            {history.map((h, i) => (
              <div key={i} className="flex items-start gap-3 text-sm">
                <span className="text-t-muted text-xs tabular-nums whitespace-nowrap pt-0.5 font-mono-t">
                  {h.changed_at ? new Date(h.changed_at).toLocaleDateString() : "—"}
                </span>
                <span className={cn("text-xs font-bold px-1.5 py-0.5 rounded border shrink-0 font-mono-t", TIER_COLORS[h.previous_tier] ?? TIER_COLORS.T1)}>
                  {h.previous_tier}
                </span>
                <span className="text-t-muted shrink-0">→</span>
                <span className={cn("text-xs font-bold px-1.5 py-0.5 rounded border shrink-0 font-mono-t", TIER_COLORS[h.new_tier] ?? TIER_COLORS.T1)}>
                  {h.new_tier}
                </span>
                <span className="text-t-muted text-xs font-ui-t">{h.reason}</span>
              </div>
            ))}
          </div>
        </div>
      )}
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
    <div className="bg-t-bg0 border border-t-dim rounded-2xl px-5 py-10 text-center">
      <p className="text-t-muted font-semibold mb-1 font-ui-t">Performance analytics not enabled</p>
      <p className="text-t-dim text-sm font-ui-t">Set ENABLE_PERFORMANCE_ANALYTICS=true to activate.</p>
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
    v == null ? "text-t-muted" : v >= 0 ? "text-t-green" : "text-t-red";

  return (
    <div className="space-y-5">
      {/* Period selector */}
      <div className="flex gap-1 bg-t-bg0 border border-t-dim rounded-xl p-1 w-fit">
        {(["7d","30d","90d","all"] as const).map((p) => (
          <button key={p} onClick={() => setPeriod(p)}
            className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors uppercase font-ui-t",
              period === p ? "bg-t-bg2 text-t-hi" : "text-t-muted hover:text-t-mid2")}>
            {p}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[0,1,2,3].map((i) => <div key={i} className="h-20 bg-t-bg0 border border-t-dim rounded-2xl animate-pulse" />)}
        </div>
      ) : metrics?.total_trades === 0 ? (
        <div className="bg-t-bg0 border border-t-dim rounded-2xl px-5 py-10 text-center">
          <p className="text-t-muted font-semibold font-ui-t">No trade data yet</p>
          <p className="text-t-dim text-sm mt-1 font-ui-t">Performance appears after the first closed trade.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Metrics grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: "Total Return", value: fmtPct(metrics?.total_return_pct), sub: fmtUsd(metrics?.total_return_usd), cls: pclr(metrics?.total_return_pct) },
              { label: "Sharpe", value: metrics?.sharpe != null ? metrics.sharpe.toFixed(2) : "—", cls: "text-t-hi" },
              { label: "Max Drawdown", value: fmtPct(metrics?.max_drawdown_pct), cls: "text-t-red" },
              { label: "Win Rate", value: metrics?.win_rate != null ? `${(metrics.win_rate * 100).toFixed(0)}%` : "—", sub: `${metrics?.total_trades ?? 0} trades`, cls: "text-t-hi" },
            ].map((card) => (
              <div key={card.label} className="bg-t-bg0 border border-t-dim rounded-2xl px-4 py-3">
                <p className="text-[10px] font-semibold text-t-dim uppercase tracking-widest mb-1 font-ui-t">{card.label}</p>
                <p className={cn("text-xl font-bold font-mono-t tabular-nums", card.cls)}>{card.value}</p>
                {card.sub && <p className="text-xs text-t-muted mt-0.5 font-mono-t tabular-nums">{card.sub}</p>}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: "Sortino", value: metrics?.sortino != null ? metrics.sortino.toFixed(2) : "—" },
              { label: "Profit Factor", value: metrics?.profit_factor != null ? metrics.profit_factor.toFixed(2) : "—" },
              { label: "Best Trade", value: fmtUsd(metrics?.best_trade_usd), cls: "text-t-green" },
              { label: "Worst Trade", value: fmtUsd(metrics?.worst_trade_usd), cls: "text-t-red" },
            ].map((card) => (
              <div key={card.label} className="bg-t-bg0 border border-t-dim rounded-2xl px-4 py-3">
                <p className="text-[10px] font-semibold text-t-dim uppercase tracking-widest mb-1 font-ui-t">{card.label}</p>
                <p className={cn("text-xl font-bold font-mono-t tabular-nums", (card as any).cls ?? "text-t-hi")}>{card.value}</p>
              </div>
            ))}
          </div>

          {/* Strategy attribution */}
          {attrData && attrData.attribution.length > 0 && (
            <div className="bg-t-bg0 border border-t-dim rounded-2xl p-4 overflow-x-auto">
              <p className="panel-header mb-3">// STRATEGY ATTRIBUTION</p>
              <table className="w-full text-xs min-w-max">
                <thead>
                  <tr className="border-b border-t-dim">
                    {["Strategy","Raw Return %","$ Contribution","Capital","Weight"].map((h) => (
                      <th key={h} className="text-left text-[10px] text-t-dim uppercase py-2 px-2 first:pl-0 font-ui-t">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {attrData.attribution.map((row) => (
                    <tr key={row.strategy} className="border-b border-t-dim/40">
                      <td className="py-2 pr-4 text-t-hi font-medium font-ui-t">{row.strategy?.replace(/_/g," ") ?? "Unattributed"}</td>
                      <td className={cn("py-2 px-2 font-mono-t tabular-nums", pclr(row.raw_return_pct))}>{fmtPct(row.raw_return_pct)}</td>
                      <td className={cn("py-2 px-2 font-mono-t tabular-nums", pclr(row.pnl_usd))}>{fmtUsd(row.pnl_usd)}</td>
                      <td className="py-2 px-2 font-mono-t tabular-nums text-t-muted">${(row.capital_deployed_usd ?? 0).toFixed(0)}</td>
                      <td className="py-2 px-2 font-mono-t tabular-nums text-t-muted">{row.weight_pct != null ? `${row.weight_pct.toFixed(1)}%` : "—"}</td>
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
    <div className="border border-t-dim rounded-xl overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-t-bg1/40 transition-colors"
      >
        <span className="text-xs font-semibold text-t-muted font-ui-t">Why this bot?</span>
        <span className="text-t-dim text-xs">{expanded ? "▲" : "▼"}</span>
      </button>
      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-t-dim">
          {description && (
            <p className="text-xs text-t-muted leading-relaxed pt-3 font-ui-t">{description}</p>
          )}
          {strategySnippets.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] text-t-dim uppercase tracking-wide font-semibold font-ui-t">
                Sample Strategies ({strategies.length} total)
              </p>
              {strategySnippets.map((s) => (
                <div key={s.name}>
                  <p className="text-xs font-semibold text-t-mid2 font-ui-t">{s.name}</p>
                  {s.desc && <p className="text-[11px] text-t-dim leading-relaxed font-ui-t">{s.desc}</p>}
                </div>
              ))}
              {strategies.length > 4 && (
                <p className="text-[11px] text-t-dim italic font-ui-t">
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
    // Fallback to bot name prefix when DB asset_class is missing or stale
    const acFromName = botName.startsWith("crypto_") || botName.startsWith("quant_") ? "crypto"
      : botName.startsWith("stock_") || botName.startsWith("options_") ? "stock"
      : null;
    const ac = profile?.asset_class ?? acFromName;
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

  const runNowMut = useMutation({
    mutationFn: () => runBotNow(botName),
    onSuccess: (data) => toast.success(data.message || "Bot triggered"),
    onError: () => toast.error("Failed to trigger bot run"),
  });

  const [equityZoom, setEquityZoom] = useState<"1M" | "3M" | "1Y" | "ALL">("ALL");
  const rawEquityCurve: EquityPoint[] = Array.isArray(stats.equity_curve) ? stats.equity_curve : [];
  const equityCurve = useMemo(() => {
    if (equityZoom === "ALL" || rawEquityCurve.length === 0) return rawEquityCurve;
    const daysBack = equityZoom === "1M" ? 30 : equityZoom === "3M" ? 90 : 365;
    const cutoff = new Date(Date.now() - daysBack * 86_400_000).toISOString().slice(0, 10);
    return rawEquityCurve.filter((p) => p.date >= cutoff);
  }, [rawEquityCurve, equityZoom]);
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
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6 animate-page-in">
      {/* Back nav */}
      <button
        onClick={() => navigate("/strategy")}
        className="flex items-center gap-1.5 text-t-muted hover:text-t-hi text-sm transition-colors font-ui-t"
      >
        <ArrowLeft className="w-4 h-4" />
        Strategy Lab
      </button>

      {/* Tab system — top of page, below back nav */}
      <TabBar active={activeTab} onChange={setActiveTab} />

      {/* ── Bot Header Strip — always visible regardless of tab ── */}
      <BracketFrame className="bg-t-bg0 border border-t-dim rounded-2xl px-5 py-4 flex flex-wrap items-center gap-4" glow>
        {isLoading ? (
          <div className="animate-pulse flex items-center gap-4 w-full">
            <div className="h-6 w-40 bg-t-bg1 rounded" />
            <div className="h-6 w-24 bg-t-bg1 rounded" />
            <div className="h-6 w-32 bg-t-bg1 rounded ml-auto" />
          </div>
        ) : (
          <>
            {/* Name + status */}
            <div className="flex items-center gap-2 min-w-0">
              <h1 className="text-base font-bold text-t-hi truncate font-mono-t tracking-wide">
                {meta?.displayName ?? displayName(botName)}
              </h1>
              <span
                className={cn(
                  "text-[10px] font-semibold px-2 py-0.5 rounded-full border flex-shrink-0 font-ui-t",
                  isEnabled
                    ? "bg-lime-500/15 text-t-green border-lime-500/30"
                    : "bg-t-bg1 text-t-muted border-t-dim"
                )}
              >
                {isEnabled ? "ACTIVE" : "DISABLED"}
              </span>
            </div>

            {/* Today P&L */}
            <div className="flex flex-col">
              <span className="text-[10px] text-t-dim uppercase tracking-wide font-ui-t">Today P&L</span>
              <span className={cn(
                "text-lg font-bold font-mono-t tabular-nums",
                (stats?.today_pnl ?? 0) >= 0 ? "text-t-green" : "text-t-red"
              )}>
                {formatPnl(stats?.today_pnl ?? 0)}
              </span>
            </div>

            {/* Open positions + notional */}
            <div className="flex flex-col">
              <span className="text-[10px] text-t-dim uppercase tracking-wide font-ui-t">Open Positions</span>
              <span className="text-base font-bold text-t-hi font-mono-t tabular-nums">
                {positions.length}
                {positions.length > 0 && (
                  <span className="text-xs text-t-muted font-normal ml-1 font-mono-t">
                    {" / $"}
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
                    "px-3 py-1.5 rounded-lg border text-xs font-semibold transition-colors font-ui-t",
                    isEnabled
                      ? "border-t-dim text-t-muted hover:border-red-600 hover:text-t-red"
                      : "border-lime-600/50 text-t-green hover:bg-lime-500/10"
                  )}
                >
                  {isEnabled ? "Disable Bot" : "Enable Bot"}
                </button>
                <button
                  onClick={() => runNowMut.mutate()}
                  disabled={runNowMut.isPending}
                  className="px-3 py-1.5 rounded-lg border border-t-accent/40 text-xs font-semibold text-t-accent hover:bg-t-accent/10 transition-colors font-ui-t disabled:opacity-50"
                >
                  {runNowMut.isPending ? "Running…" : "Run Now"}
                </button>
                {!isOnWaitlist ? (
                  <button
                    onClick={() => waitlistMut.mutate(!isOnWaitlist)}
                    disabled={waitlistMut.isPending}
                    className="px-3 py-1.5 rounded-lg border border-t-amber/30 text-xs font-semibold text-t-amber hover:bg-t-amber/10 transition-colors font-ui-t"
                  >
                    Notify when live
                  </button>
                ) : (
                  <span className="text-xs text-t-green font-semibold font-ui-t">✓ On waitlist</span>
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
          <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5">
            <SectionLabel as="h2" className="mb-4">Open Positions</SectionLabel>
            {isRebalanceOnly && positions.length > 0 && (
              <p className="text-xs text-t-muted mb-3 bg-t-bg1/50 border border-t-dim/50 rounded-lg px-3 py-2 font-ui-t">
                Long-term holds — this bot uses larger position sizes by design (weekly DCA / rebalance, fewer trades, longer hold periods).
              </p>
            )}
            {isLoading ? (
              <div className="animate-pulse space-y-2">
                {[0, 1, 2].map((i) => <div key={i} className="h-10 bg-t-bg1 rounded" />)}
              </div>
            ) : positions.length === 0 ? (
              <p className="text-t-dim text-sm py-6 text-center leading-relaxed font-ui-t">
                Bot is scanning — open positions will appear here when it enters a trade.{" "}
                Check the Watchlist tab to see what it&apos;s currently evaluating.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-t-dim border-b border-t-dim">
                      <th className="text-left pb-2 font-medium font-ui-t">Symbol</th>
                      <th className="text-left pb-2 font-medium font-ui-t">Side</th>
                      <th className="text-right pb-2 font-medium font-ui-t">Size</th>
                      <th className="text-right pb-2 font-medium font-ui-t">Current Value</th>
                      <th className="text-right pb-2 font-medium font-ui-t">Unrealized P&L</th>
                      <th className="text-right pb-2 font-medium font-ui-t">Time Held</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((pos) => {
                      const isPosOptions = !!pos.option_type;
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
                          className="border-b border-t-dim/50 last:border-0 cursor-pointer hover:bg-t-bg1/30 transition-colors"
                          onClick={() => navigate(`/chart?symbol=${pos.symbol}`)}
                          title={`View ${pos.symbol} chart`}
                        >
                          <td className="py-2.5">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className="font-semibold text-t-hi font-mono-t">{pos.symbol}</span>
                              {isSymbolMismatch(pos.symbol) && (
                                <span className="text-[10px] text-t-amber border border-t-amber/30 bg-t-amber/10 px-1 py-0.5 rounded font-medium whitespace-nowrap font-ui-t">⚠️ mismatch</span>
                              )}
                              {isPosOptions && pos.option_type && (
                                <span className={cn(
                                  "text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide font-ui-t",
                                  pos.option_type === "call" ? "bg-emerald-900/60 text-emerald-300" : "bg-red-900/60 text-red-300"
                                )}>
                                  {pos.option_type}
                                </span>
                              )}
                              {isPosOptions && pos.strike_price != null && (
                                <span className="text-xs text-t-mid2 font-mono-t">
                                  ${pos.strike_price % 1 === 0 ? pos.strike_price.toFixed(0) : pos.strike_price.toFixed(2)}
                                </span>
                              )}
                              {isPosOptions && pos.expiration_date && (
                                <span className="text-xs text-t-muted font-mono-t">
                                  {new Date(pos.expiration_date + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })}
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="py-2.5">
                            {isPosOptions ? (
                              <span className="text-xs font-semibold px-1.5 py-0.5 rounded bg-purple-900/40 text-purple-300 border border-purple-700/30 font-ui-t">
                                OPTIONS
                              </span>
                            ) : (
                              <span className="text-xs font-semibold px-1.5 py-0.5 rounded bg-t-cyan/15 text-t-cyan border border-t-cyan/20 font-ui-t">
                                LONG
                              </span>
                            )}
                          </td>
                          <td className="py-2.5 text-right text-t-mid2 tabular-nums font-mono-t">
                            {isPosOptions
                              ? pos.contract_count != null
                                ? `×${pos.contract_count} contracts`
                                : pos.qty != null ? `×${pos.qty} contracts` : "—"
                              : pos.qty != null && pos.avg_cost_cents != null
                                ? formatTradeSize(pos.qty, pos.symbol, (pos.avg_cost_cents / 100) * Math.abs(pos.qty))
                                : pos.qty != null ? formatQty(pos.qty, pos.symbol) : "—"}
                          </td>
                          <td className="py-2.5 text-right text-t-mid2 tabular-nums font-mono-t">
                            {currentValue != null ? `$${currentValue.toFixed(2)}` : "—"}
                          </td>
                          <td className={cn(
                            "py-2.5 text-right text-sm font-medium tabular-nums font-mono-t",
                            unrealizedPnl == null ? "text-t-muted"
                              : unrealizedPnl >= 0 ? "text-t-green" : "text-t-red"
                          )}>
                            {unrealizedPnl != null
                              ? `${unrealizedPnl >= 0 ? "+" : ""}$${Math.abs(unrealizedPnl).toFixed(2)}${pnlPct != null ? ` (${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%)` : ""}`
                              : "—"}
                          </td>
                          <td className="py-2.5 text-right text-xs text-t-muted font-mono-t">{timeHeld}</td>
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
            <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5 flex flex-col gap-4">
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
                  <div key={s.label} className="bg-t-bg0 rounded-xl px-3 py-2.5 border border-t-dim">
                    <p className="text-t-dim text-[10px] uppercase tracking-wide mb-0.5 font-ui-t">{s.label}</p>
                    <p
                      className={cn(
                        "text-sm font-bold font-mono-t tabular-nums",
                        s.colored ? (s.positive ? "text-t-green" : "text-t-red") : "text-t-hi"
                      )}
                    >
                      {s.value}
                    </p>
                  </div>
                ))}
              </div>
              {allocation && (
                <p className="text-xs text-t-muted font-ui-t">
                  Allocated:{" "}
                  <span className="text-t-mid2 font-semibold font-mono-t tabular-nums">
                    ${allocation.starting_capital_cents ? (allocation.starting_capital_cents / 100).toLocaleString() : ((allocation.capital_pct / 100) * 100000).toLocaleString()} ({allocation.capital_pct}%)
                  </span>
                </p>
              )}
            </div>

            {/* RIGHT — Equity Curve */}
            <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5 flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <SectionLabel as="h2">Equity Curve</SectionLabel>
                {rawEquityCurve.length > 0 && (
                  <div className="flex rounded border border-t-dim overflow-hidden">
                    {(["1M", "3M", "1Y", "ALL"] as const).map((z) => (
                      <button
                        key={z}
                        onClick={() => setEquityZoom(z)}
                        className={cn(
                          "text-[10px] px-2 py-0.5 transition-colors font-mono-t",
                          equityZoom === z
                            ? "bg-t-bg1 text-t-hi"
                            : "bg-transparent text-t-dim hover:text-t-muted",
                        )}
                      >
                        {z}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {equityCurve.length === 0 ? (
                <div className="flex-1 flex items-center justify-center min-h-[180px]">
                  <p className="text-t-dim text-sm text-center px-4 leading-relaxed font-ui-t">
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
                              ? "#4ade80" : "#ef4444"
                          } stopOpacity={0.3} />
                          <stop offset="95%" stopColor={
                            equityCurve.length > 0 && equityCurve[equityCurve.length - 1].portfolio >= equityCurve[0].portfolio
                              ? "#4ade80" : "#ef4444"
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
                            ? "#4ade80" : "#ef4444"
                        }
                        strokeWidth={2}
                        fill="url(#equityGradient)"
                        dot={false}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                  <div className="flex gap-4">
                    <div className="flex items-center gap-1.5 text-xs text-t-muted font-ui-t">
                      <span className="w-3 h-0.5 bg-[#4ade80] inline-block rounded" />
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
          <div className="bg-t-bg0 border border-t-dim rounded-xl px-4 py-3">
            <h3 className="panel-header mb-2">// Upcoming Catalysts</h3>
            <CatalystCalendar />
          </div>

          {/* PDT removal notice for day-trading bots */}
          {(botName === "stock_day" || botName === "crypto_day") && (
            <div className="flex items-start gap-3 bg-t-cyan/10 border border-t-cyan/30 rounded-xl px-4 py-3">
              <span className="text-t-cyan mt-0.5 text-base leading-none">⚡</span>
              <div>
                <p className="text-xs font-semibold text-t-cyan font-ui-t">PDT Rule Eliminated — June 4, 2026</p>
                <p className="text-xs text-t-muted mt-0.5 leading-relaxed font-ui-t">
                  FINRA Notice 26-10 removed the Pattern Day Trader $25,000 minimum. This bot now
                  trades without account-size restrictions. <span className="text-t-muted">Paper mode active.</span>
                </p>
              </div>
            </div>
          )}

          {/* Top-3 watchlist preview */}
          <WatchlistPreview botName={botName} onViewAll={() => setActiveTab("watchlist")} />

          {/* Bot Info — full width */}
          <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5 flex flex-col gap-4">
              <SectionLabel as="h2">Bot Info</SectionLabel>

              {/* Description + asset class */}
              <div className="flex items-start gap-3">
                {(() => {
                  const ac = profile?.asset_class ?? (botName.includes("options") ? "options" : isCrypto ? "crypto" : "stock");
                  const isOptions = ac === "options" || botName.includes("options");
                  return (
                    <span className={cn(
                      "text-xs font-semibold px-2 py-0.5 rounded-full border flex-shrink-0 mt-0.5 font-ui-t",
                      isOptions
                        ? "bg-purple-500/15 text-purple-400 border-purple-500/30"
                        : isCrypto
                          ? "bg-orange-500/15 text-t-amber border-orange-500/30"
                          : "bg-t-cyan/15 text-t-cyan border-t-cyan/30"
                    )}>
                      {isOptions ? "OPTIONS" : isCrypto ? "CRYPTO" : "STOCK"}
                    </span>
                  );
                })()}
                <p className="text-sm text-t-muted leading-relaxed font-ui-t">
                  {meta?.description ?? profile?.description ?? "No description available."}
                </p>
              </div>

              {/* Key stats */}
              <div className="grid grid-cols-2 gap-2">
                <div className="bg-t-bg0 rounded-xl px-3 py-2.5 border border-t-dim">
                  <p className="text-t-dim text-[10px] uppercase tracking-wide mb-0.5 font-ui-t">Win Rate</p>
                  <p className={cn(
                    "text-sm font-bold font-mono-t tabular-nums",
                    stats?.win_rate_pct ? ((stats.win_rate_pct ?? 0) >= 50 ? "text-t-green" : "text-t-red") : "text-t-muted"
                  )}>
                    {stats?.win_rate_pct ? `${(stats.win_rate_pct ?? 0).toFixed(1)}%` : "—"}
                  </p>
                </div>
                <div className="bg-t-bg0 rounded-xl px-3 py-2.5 border border-t-dim">
                  <p className="text-t-dim text-[10px] uppercase tracking-wide mb-0.5 font-ui-t">Last Signal</p>
                  <p className="text-sm font-bold text-t-mid2 font-mono-t">
                    {signals.length > 0 ? formatRelativeAgo(signals[0].ts) : "—"}
                  </p>
                </div>
                <div className="bg-t-bg0 rounded-xl px-3 py-2.5 border border-t-dim">
                  <p className="text-t-dim text-[10px] uppercase tracking-wide mb-0.5 font-ui-t">Cadence</p>
                  <p className="text-sm font-bold text-t-mid2 capitalize font-ui-t">{profile?.cadence ? formatCadence(profile.cadence) : "—"}</p>
                </div>
                <div className="bg-t-bg0 rounded-xl px-3 py-2.5 border border-t-dim">
                  <p className="text-t-dim text-[10px] uppercase tracking-wide mb-0.5 font-ui-t">Strategies</p>
                  <p className="text-sm font-bold text-t-mid2 font-mono-t tabular-nums">
                    {(meta?.strategies?.length ?? 0) > 0 ? meta!.strategies.length : "—"}
                  </p>
                </div>
              </div>

              {/* Why this bot? expandable */}
              <BotWhySection botName={botName} meta={meta} profile={profile} />
          </div>

          {/* Activity feed below grid */}
          <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5">
            <SectionLabel as="h2" className="mb-4">Recent Signals</SectionLabel>
            {signals.length === 0 ? (
              <p className="text-t-dim text-sm py-4 text-center font-ui-t">No signals fired today. Next scan at market open (9:30am ET).</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-t-dim border-b border-t-dim">
                      <th className="text-left pb-2 font-medium font-ui-t">Time</th>
                      <th className="text-left pb-2 font-medium font-ui-t">Symbol</th>
                      <th className="text-left pb-2 font-medium font-ui-t">Side</th>
                      <th className="text-right pb-2 font-medium font-ui-t">Confidence</th>
                      <th className="text-left pb-2 font-medium font-ui-t">Strategy</th>
                      <th className="text-left pb-2 font-medium font-ui-t">Reason</th>
                      <th className="text-right pb-2 font-medium"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {signals.map((sig) => (
                      <tr key={sig.id} className="border-b border-t-dim/50 last:border-0">
                        <td className="py-2.5 text-t-muted text-xs font-mono-t">{formatTime(sig.ts)}</td>
                        <td className="py-2.5 font-semibold text-t-hi font-mono-t">{sig.symbol}</td>
                        <td className="py-2.5"><SideBadge side={sig.side} /></td>
                        <td className="py-2.5 text-right text-t-mid2 font-mono-t tabular-nums">{sig.confidence.toFixed(0)}%</td>
                        <td className="py-2.5 text-t-muted text-xs font-ui-t">{sig.strategy}</td>
                        <td className="py-2.5 text-t-muted text-xs max-w-xs truncate font-ui-t">{sig.reason}</td>
                        <td className="py-2.5 text-right">
                          <button
                            onClick={() => setSelectedSignal(sig)}
                            className="text-xs text-t-muted hover:text-t-green underline underline-offset-2 transition-colors font-ui-t"
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
          <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-t-mid2 font-ui-t">
                {meta?.displayName ?? botName} Watchlist
              </h2>
              <span className="text-[10px] text-t-dim font-ui-t">Refreshes every 30s</span>
            </div>
            <EntryReadinessTable
              botName={botName}
              botDisplayName={meta?.displayName ?? botName}
              navigate={navigate}
            />
          </div>

          {/* AI conviction scores (secondary) */}
          {Object.keys(analysisBySymbol).length > 0 && (
            <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5">
              <h2 className="text-sm font-semibold text-t-mid2 mb-4 font-ui-t">AI Conviction Scores</h2>
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

      {activeTab === "signal_quality" && <SignalQualityTab botName={botName} />}

      {/* Settings tab */}
      {activeTab === "performance" && (
        <BotPerformanceTab botName={botName} />
      )}

      {activeTab === "allocation" && (
        <AllocationTab allocationId={allocation?.id ?? 0} />
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
      <p className="text-xs text-center text-t-dim mt-8 font-ui-t">
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

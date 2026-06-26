import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { BracketFrame, SectionLabel } from "@/components/design";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate, Link } from "react-router-dom";
import SymbolChartDrawer from "@/components/ui/SymbolChartDrawer";
import AllocationDonut from "@/components/ui/AllocationDonut";
import DeploymentSummary from "@/components/DeploymentSummary";
import { toast } from "sonner";
import {
  getBots,
  allocateBot,
  joinWaitlist,
  leaveWaitlist,
  migrateLegacyPositions,
  getRegime,
  pauseAllBots,
  resumeAllBots,
  activateAllBots,
  getPortfolios,
  setupPortfolios,
  getPendingReviews,
  getStrategyLabPortfolio,
  getStrategyLabCandidates,
  getOpenPositions,
  runBotNow,
  type BotListItem,
  type RegimeData,
  type PendingReview,
  type PortfolioData,
  type StrategyPortfolio,
  type OpenPosition,
} from "@/api/bots";
import { getAutopilotActivity, type AutopilotAction } from "@/api/autopilot";
import { getCrossBotWatchlist, type CrossBotWatchlistItem } from "@/api/bots";
import { getSetups, getSignals as getScoutSignals, type ScoutSignal } from "@/api/scout";
import { getForgeBots, getForgeSignals, type ForgeSignal } from "@/api/forge";
import { getAnalystSummary, type AnalystSummaryItem } from "@/api/analyst";
import { cn } from "@/lib/utils";
import { formatSleeveSubtitle } from "@/lib/formatAllocation";
import { useIsViewer } from "@/store/authStore";

// ─── Candidate metadata ───────────────────────────────────────────────────────

const CANDIDATE_META = [
  {
    id: "cross_sectional_momentum",
    name: "Cross-Sectional Momentum",
    assetClass: "equity" as const,
    style: "momentum" as const,
    reference: "Jegadeesh & Titman (1993)",
    expectedSharpe: "0.4–0.8",
    description: "Ranks universe by 12-1M return, buys top quintile, sells bottom quintile.",
  },
  {
    id: "time_series_momentum",
    name: "Time-Series Momentum",
    assetClass: "multi" as const,
    style: "momentum" as const,
    reference: "Moskowitz, Ooi & Pedersen (2012)",
    expectedSharpe: "0.5–1.0",
    description: "Each asset evaluated independently; long if 12M trailing return positive. Sized by inverse vol.",
  },
  {
    id: "crypto_dual_momentum",
    name: "Crypto Dual Momentum",
    assetClass: "crypto" as const,
    style: "momentum" as const,
    reference: "Liu & Tsyvinski (2021) + Antonacci (2014)",
    expectedSharpe: "0.6–1.2",
    description: "Combines absolute momentum vs. cash with relative momentum across top-N crypto. Long-only.",
  },
  {
    id: "overnight_gap_fade",
    name: "Overnight Gap Fade",
    assetClass: "equity" as const,
    style: "mean_reversion" as const,
    reference: "Branch & Ma (2008)",
    expectedSharpe: "0.3–0.7",
    description: "Fades overnight gaps > 1.5%. Gap-up stocks tend to pull back; gap-down stocks tend to recover.",
  },
  {
    id: "rsi2_mean_reversion",
    name: "RSI-2 Mean Reversion",
    assetClass: "equity" as const,
    style: "mean_reversion" as const,
    reference: "Connors & Alvarez (2009)",
    expectedSharpe: "0.4–0.9",
    description: "Buys when RSI(2) < 10 above the 200-day MA. Exits when RSI(2) closes above 70.",
  },
  {
    id: "cash_and_carry",
    name: "Cash-and-Carry Basis",
    assetClass: "crypto" as const,
    style: "arbitrage" as const,
    reference: "Futures basis trade",
    expectedSharpe: "1.0–2.5",
    description: "Delta-neutral: long spot + short perp. Collects positive funding rate as carry.",
  },
  {
    id: "liquidation_cascade",
    name: "Liquidation Cascade",
    assetClass: "crypto" as const,
    style: "event_driven" as const,
    reference: "Coinglass heatmap + Binance forceOrders",
    expectedSharpe: "0.6–1.4",
    description: "Ride mode follows cascades at heatmap clusters; fade mode fades exhausted cascades.",
  },
  {
    id: "insider_cluster_buying",
    name: "Insider Cluster Buying",
    assetClass: "equity" as const,
    style: "event_driven" as const,
    reference: "Lakonishok & Lee (2001) — SEC Form 4",
    expectedSharpe: "0.5–1.1",
    description: "Detects 3+ insiders buying open-market (≥$500k) within a 30-day window.",
  },
  {
    id: "cross_asset_momentum",
    name: "Cross-Asset Momentum",
    assetClass: "multi" as const,
    style: "cross_asset_momentum" as const,
    reference: "Antonacci (2014) Global Equities Momentum",
    expectedSharpe: "0.7–1.0",
    description: "10-ETF monthly rotation into top-3 by blended momentum. Only holds assets above absolute trend filter. Credit spread gate cuts sizing in stress.",
  },
  {
    id: "earnings_vol_premium",
    name: "Earnings Vol Premium",
    assetClass: "equity" as const,
    style: "short_volatility" as const,
    reference: "Augustin, Brenner & Subrahmanyam (2014)",
    expectedSharpe: "1.0–1.6",
    description: "Sells iron condors 7 days before earnings on stocks where IV rank ≥ 70% and implied move ≥ 5%. Captures post-earnings IV crush.",
  },
  {
    id: "quality_momentum_screen",
    name: "Quality Momentum Screen",
    assetClass: "equity" as const,
    style: "quality_momentum" as const,
    reference: "Asness, Frazzini & Pedersen (2019) QMJ",
    expectedSharpe: "0.7–1.5",
    description: "Monthly rebalance into top-25 stocks ranked by QMJ quality (SimFin), 12-1M momentum, and low beta. Flattens to cash when credit spreads are red.",
  },
  {
    id: "options_iv_premium_filter",
    name: "Options IV Premium Filter",
    assetClass: "equity" as const,
    style: "short_volatility" as const,
    reference: "Israelov & Nielsen (2014)",
    expectedSharpe: "0.7–1.1",
    description: "Sells cash-secured puts or covered calls only when IV Rank ≥ 50. Captures the volatility risk premium with an IVR gate to avoid selling into low-vol regimes.",
  },
];

// ─── Bot metadata ─────────────────────────────────────────────────────────────

const BOT_META: Record<
  string,
  { displayName: string; description: string; assetClass: "stock" | "crypto" | "quant" | "options" }
> = {
  stock_swing: {
    displayName: "Stock Swing",
    description: "Russell 1000 momentum plays, 1-30 day holds",
    assetClass: "stock",
  },
  stock_day: {
    displayName: "Stock Day",
    description: "Intraday gappers & earnings momentum, EOD flat",
    assetClass: "stock",
  },
  stock_lt: {
    displayName: "Stock Long-Term",
    description: "S&P 500 factor model, monthly rebalance",
    assetClass: "stock",
  },
  crypto_swing: {
    displayName: "Crypto Swing",
    description: "Top 20 crypto by mcap, 1-30 day holds",
    assetClass: "crypto",
  },
  crypto_day: {
    displayName: "Crypto Day",
    description: "BTC/ETH/SOL intraday momentum, 8h force-close",
    assetClass: "crypto",
  },
  crypto_lt: {
    displayName: "Crypto L-T DCA",
    description: "BTC/ETH + majors, weekly DCA & monthly rebalance",
    assetClass: "crypto",
  },
  crypto_quant_aggressive: {
    displayName: "Crypto Quant Aggressive",
    description: "5-signal high-turnover quant · 20-coin universe · $100k paper sub-account",
    assetClass: "quant",
  },
  crypto_quant_mean_reversion: {
    displayName: "Quant Mean Rev",
    description: "Multi-signal mean-reversion on top-10 crypto by market cap",
    assetClass: "quant",
  },
  crypto_quant_scalper: {
    displayName: "Quant Scalper",
    description: "High-frequency scalper on BTC/ETH/SOL with 15-min cooldown",
    assetClass: "quant",
  },
  crypto_meanrev_2163: {
    displayName: "Mean Rev 2163",
    description: "Experimental mean-reversion variant, paper-only deployment",
    assetClass: "quant",
  },
  crypto_onchain: {
    displayName: "Crypto Onchain",
    description: "On-chain flow analysis — large wallet movements, DEX volume anomalies, L2 bridge activity",
    assetClass: "crypto",
  },
  options_income: {
    displayName: "Options Income",
    description: "Equity income — quality stocks, dividend + growth focus",
    assetClass: "stock",
  },
  options_directional: {
    displayName: "Options Directional",
    description: "Equity directional — tactical momentum & mean-reversion",
    assetClass: "stock",
  },
};

const BOT_ORDER = [
  "stock_day",
  "stock_swing",
  "stock_lt",
  "crypto_day",
  "crypto_swing",
  "crypto_lt",
  "crypto_onchain",
  "crypto_quant_aggressive",
  "crypto_quant_mean_reversion",
  "crypto_quant_scalper",
  "crypto_meanrev_2163",
  "options_income",
  "options_directional",
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatPnl(val: number): string {
  const abs = Math.abs(val);
  const sign = val >= 0 ? "+" : "-";
  if (abs >= 1_000_000_000) return `${sign}$${(abs / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000)     return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000)         return `${sign}$${(abs / 1_000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(2)}`;
}

// "ALLOCATED" dollar formatter for the BotCard Capital Allocated stat.
// Whole-dollar formatting with commas at >= $1000; 2-decimal precision below.
// Returns null when value is missing or non-positive — caller falls through.
function formatDollarsWhole(usd: number | null | undefined): string | null {
  if (usd == null || !isFinite(usd) || usd <= 0) return null;
  if (usd >= 1000) {
    return `$${Math.round(usd).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  }
  return `$${usd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatPct(val: number): string {
  const sign = val >= 0 ? "+" : "";
  return `${sign}${val.toFixed(2)}%`;
}

function displayName(name: string): string {
  return BOT_META[name]?.displayName ?? name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatCadence(cadence: string): string {
  const MAP: Record<string, string> = {
    "* 9-15 * * 1-5":  "Trades intraday, Mon–Fri",
    "5 16 * * 1-5":    "Runs at 4:05 PM ET, Mon–Fri",
    "0 10 1-7 * 2":    "Rebalances 1st Tuesday/month",
    "* * * * *":       "Trades 24/7",
    "intraday":        "Trades intraday, Mon–Fri",
    "weekly":          "Rebalances weekly",
    "daily":           "Runs daily",
  };
  return MAP[cadence] ?? cadence.replace(/_/g, " ");
}

// ─── Regime status bar ────────────────────────────────────────────────────────

function vixColor(regime: string): string {
  const r = regime.toLowerCase();
  if (r === "low") return "bg-t-green/15 text-t-green border-t-green/30";
  if (r === "mid") return "bg-t-amber/15 text-t-amber border-t-amber/30";
  if (r === "high") return "bg-t-amber/10 text-t-amber border-t-amber/30";
  if (r === "panic") return "bg-t-red/15 text-t-red border-t-red/30";
  return "bg-t-bg1 text-t-muted border-t-dim";
}

function trendColor(regime: string): string {
  const r = regime.toLowerCase();
  if (r === "bull") return "bg-t-green/15 text-t-green border-t-green/30";
  if (r === "chop") return "bg-t-bg2/40 text-t-muted border-t-dim";
  if (r === "bear") return "bg-t-red/15 text-t-red border-t-red/30";
  return "bg-t-bg1 text-t-muted border-t-dim";
}

function RegimePill({ dot, label, value, colorClass }: { dot: string; label: string; value: string; colorClass: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border font-ui-t", colorClass)}>
      <span className={cn("w-1.5 h-1.5 rounded-full", dot)} />
      <span className="text-t-dim">{label}</span>
      <span>{value}</span>
    </span>
  );
}

function RegimeBar({ regime, isLoading }: { regime: RegimeData | undefined; isLoading: boolean }) {
  if (isLoading || !regime) {
    return (
      <div className="flex gap-2 items-center animate-pulse">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-7 w-24 bg-t-bg1 rounded-full" />
        ))}
      </div>
    );
  }

  const vix = regime.vix_regime?.toUpperCase() ?? "MID";
  const trend = regime.trend_regime?.toUpperCase() ?? "CHOP";
  const btcDom = typeof regime.btc_dominance === "number" ? `${regime.btc_dominance.toFixed(0)}%` : "—";

  return (
    <div className="flex flex-wrap gap-2 items-center">
      <RegimePill
        dot={vix === "LOW" ? "bg-t-green" : vix === "PANIC" ? "bg-t-red" : vix === "HIGH" ? "bg-t-amber" : "bg-t-amber"}
        label="VIX"
        value={vix}
        colorClass={vixColor(vix)}
      />
      <RegimePill
        dot={trend === "BULL" ? "bg-t-green" : trend === "BEAR" ? "bg-t-red" : "bg-t-muted"}
        label="Trend"
        value={trend}
        colorClass={trendColor(trend)}
      />
      <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border bg-t-bg1 border-t-dim text-t-mid2 font-ui-t">
        <span className="w-1.5 h-1.5 rounded-full bg-t-amber" />
        <span className="text-t-dim">BTC Dom</span>
        <span>{btcDom}</span>
      </span>
    </div>
  );
}

// ─── Open Positions Panel ─────────────────────────────────────────────────────

type SortKey = "recent" | "pnl" | "bot" | "symbol";
type AssetFilter = "all" | "stock" | "crypto" | "options" | "quant";

function fmtHeld(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (seconds < 86_400) return m > 0 ? `${h}h ${m}m` : `${h}h`;
  const d = Math.floor(seconds / 86_400);
  const rh = Math.floor((seconds % 86_400) / 3600);
  return rh > 0 ? `${d}d ${rh}h` : `${d}d`;
}

function fmtQty(qty: number, symbol: string): string {
  if (symbol.includes("/")) {
    if (qty < 0.001) return qty.toFixed(6);
    if (qty < 1) return qty.toFixed(4);
    return qty.toFixed(4);
  }
  return qty % 1 === 0 ? String(Math.round(qty)) : qty.toFixed(2);
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

function PositionRowSkeleton() {
  return (
    <div className="flex items-center gap-2 px-3 py-2.5 animate-pulse">
      <div className="w-16 h-3.5 bg-t-bg1 rounded" />
      <div className="w-20 h-5 bg-t-bg1 rounded-full" />
      <div className="w-10 h-5 bg-t-bg1 rounded-full" />
      <div className="w-12 h-3 bg-t-bg1 rounded ml-auto" />
      <div className="w-16 h-3 bg-t-bg1 rounded" />
      <div className="w-16 h-3 bg-t-bg1 rounded" />
      <div className="w-20 h-3 bg-t-bg1 rounded" />
      <div className="w-10 h-3 bg-t-bg1 rounded" />
    </div>
  );
}

function OpenPositionsPanel() {
  const [sortBy, setSortBy] = useState<SortKey>("recent");
  const [filterClass, setFilterClass] = useState<AssetFilter>("all");

  const { data, isLoading } = useQuery({
    queryKey: ["open-positions"],
    queryFn: getOpenPositions,
    refetchInterval: 30_000,
    staleTime: 25_000,
    retry: 0,
  });

  const positions = useMemo<OpenPosition[]>(() => {
    let list = [...(data?.positions ?? [])];
    if (filterClass !== "all") {
      list = list.filter((p) => p.asset_class === filterClass);
    }
    switch (sortBy) {
      case "pnl":    list.sort((a, b) => b.unrealized_pnl_usd - a.unrealized_pnl_usd); break;
      case "bot":    list.sort((a, b) => a.bot_name.localeCompare(b.bot_name)); break;
      case "symbol": list.sort((a, b) => a.symbol.localeCompare(b.symbol)); break;
      default:       list.sort((a, b) => new Date(b.opened_at).getTime() - new Date(a.opened_at).getTime());
    }
    return list;
  }, [data, sortBy, filterClass]);

  const totalUsd    = data?.total_unrealized_usd ?? 0;
  const totalPos    = data?.position_count ?? 0;
  const distinctBots = data?.distinct_bots ?? 0;
  const totalIsPos  = totalUsd >= 0;

  // Determine which filter chips are non-empty
  const assetCounts = useMemo(() => {
    const map: Partial<Record<AssetFilter, number>> = { all: data?.positions?.length ?? 0 };
    for (const p of data?.positions ?? []) {
      map[p.asset_class as AssetFilter] = (map[p.asset_class as AssetFilter] ?? 0) + 1;
    }
    return map;
  }, [data]);

  const FILTER_CHIPS: { key: AssetFilter; label: string }[] = [
    { key: "all",     label: "All" },
    { key: "stock",   label: "Stocks" },
    { key: "crypto",  label: "Crypto" },
    { key: "options", label: "Options" },
    { key: "quant",   label: "Quant" },
  ];

  const SORT_OPTS: { key: SortKey; label: string }[] = [
    { key: "recent", label: "▼ Recent" },
    { key: "pnl",    label: "P&L" },
    { key: "bot",    label: "Bot" },
    { key: "symbol", label: "Symbol" },
  ];

  return (
    <div className="pt-3 border-t border-t-dim">
      {/* Header row */}
      <div className="flex items-center justify-between mb-1.5">
        <SectionLabel as="p">Open Positions</SectionLabel>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortKey)}
          className="text-[10px] bg-t-bg0 border border-t-dim rounded px-1.5 py-0.5 text-t-muted cursor-pointer focus:outline-none font-ui-t"
        >
          {SORT_OPTS.map((o) => (
            <option key={o.key} value={o.key}>{o.label}</option>
          ))}
        </select>
      </div>

      {/* Summary line */}
      {!isLoading && (
        <p className="text-[11px] text-t-dim mb-2 font-ui-t">
          {totalPos} position{totalPos !== 1 ? "s" : ""} · {distinctBots} bot{distinctBots !== 1 ? "s" : ""}
          {totalPos > 0 && (
            <> · Total unrealized:{" "}
              <span className={totalIsPos ? "text-t-green" : "text-t-red"}>
                {totalIsPos ? "+" : "−"}${Math.abs(totalUsd).toFixed(2)}
              </span>
            </>
          )}
        </p>
      )}

      {/* Filter chips */}
      {!isLoading && (data?.positions?.length ?? 0) > 0 && (
        <div className="flex gap-1 mb-2 flex-wrap">
          {FILTER_CHIPS.filter((c) => c.key === "all" || (assetCounts[c.key] ?? 0) > 0).map((chip) => (
            <button
              key={chip.key}
              onClick={() => setFilterClass(chip.key)}
              className={cn(
                "text-[10px] px-2 py-0.5 rounded-full border transition-colors font-ui-t",
                filterClass === chip.key
                  ? "bg-t-green/15 text-t-green border-t-green/30"
                  : "text-t-dim border-t-dim hover:text-t-mid2 hover:border-t-mid"
              )}
            >
              {chip.label}
              {chip.key !== "all" && assetCounts[chip.key] ? ` (${assetCounts[chip.key]})` : ""}
            </button>
          ))}
        </div>
      )}

      {/* Table header */}
      {!isLoading && positions.length > 0 && (
        <div className="grid gap-x-2 px-3 pb-1 text-[9px] font-semibold text-t-gdim uppercase tracking-wide font-ui-t"
          style={{ gridTemplateColumns: "5rem 1fr 2.5rem 4rem 4rem 4.5rem 5.5rem 3rem" }}>
          <span>Symbol</span>
          <span>Bot</span>
          <span>Side</span>
          <span className="text-right">Qty</span>
          <span className="text-right">Entry</span>
          <span className="text-right">Curr Val</span>
          <span className="text-right">Unrealized</span>
          <span className="text-right">Held</span>
        </div>
      )}

      {/* Loading skeletons */}
      {isLoading && (
        <div className="space-y-0.5">
          {[0, 1, 2].map((i) => <PositionRowSkeleton key={i} />)}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && positions.length === 0 && (
        <p className="text-t-gdim text-xs py-4 text-center font-ui-t">
          {filterClass !== "all"
            ? `No open ${filterClass} positions.`
            : "No open positions. Bots scan continuously — next signal could land any minute."}
        </p>
      )}

      {/* Position rows */}
      {!isLoading && positions.length > 0 && (
        <div className="space-y-0.5">
          {positions.map((pos) => {
            const pnlPos = pos.unrealized_pnl_usd >= 0;
            const pnlSign = pnlPos ? "+" : "−";
            return (
              <Link
                key={pos.position_id}
                to={`/strategy/trade/${pos.trade_id}`}
                className="grid gap-x-2 px-3 py-2 rounded-xl bg-t-bg1/40 hover:bg-t-bg1 border border-t-dim/60 hover:border-t-mid transition-colors items-center card-hover"
                style={{ gridTemplateColumns: "5rem 1fr 2.5rem 4rem 4rem 4.5rem 5.5rem 3rem" }}
              >
                {/* Symbol */}
                <span className="text-xs font-bold text-t-hi truncate font-mono-t">{pos.symbol}</span>

                {/* Bot pill */}
                <span
                  className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded-full w-fit truncate font-mono-t"
                  style={{ background: `${pos.bot_color}22`, color: pos.bot_color, border: `1px solid ${pos.bot_color}44` }}
                >
                  {pos.bot_display}
                </span>

                {/* Side pill */}
                <span className={cn(
                  "text-[9px] font-bold px-1.5 py-0.5 rounded-full w-fit font-ui-t",
                  pos.side === "buy"
                    ? "bg-t-green/15 text-t-green border border-t-green/30"
                    : "bg-t-red/15 text-t-red border border-t-red/30"
                )}>
                  {pos.side.toUpperCase()}
                </span>

                {/* Qty */}
                <span className="text-[11px] text-t-muted text-right tabular-nums font-mono-t">
                  {fmtQty(pos.qty, pos.symbol)}
                </span>

                {/* Entry */}
                <span className="text-[11px] text-t-dim text-right tabular-nums font-mono-t">
                  {fmtPrice(pos.entry_price)}
                </span>

                {/* Current Value = qty × current_price */}
                <span className="text-[11px] text-t-hi text-right tabular-nums font-mono-t flex items-center justify-end gap-0.5">
                  {pos.price_source === "stale" && (
                    <span title="Price last updated — live ticker temporarily unavailable" className="text-[9px] text-t-amber cursor-help">⚠</span>
                  )}
                  ${(pos.current_value_usd ?? pos.current_price * pos.qty).toFixed(2)}
                </span>

                {/* Unrealized P&L — two stacked lines */}
                <div className="text-right">
                  <div className={cn(
                    "text-[11px] font-semibold tabular-nums leading-tight font-mono-t",
                    pos.unrealized_pnl_usd > 0 ? "text-t-green"
                    : pos.unrealized_pnl_usd < 0 ? "text-t-red"
                    : "text-t-dim"
                  )}>
                    {pos.unrealized_pnl_usd > 0 ? "+" : pos.unrealized_pnl_usd < 0 ? "-" : ""}
                    ${Math.abs(pos.unrealized_pnl_usd).toFixed(2)}
                  </div>
                  <div className={cn(
                    "text-[9px] tabular-nums leading-tight font-mono-t",
                    pos.unrealized_pnl_pct > 0 ? "text-t-green/70"
                    : pos.unrealized_pnl_pct < 0 ? "text-t-red/70"
                    : "text-t-gdim"
                  )}>
                    {pos.unrealized_pnl_pct > 0 ? "+" : pos.unrealized_pnl_pct < 0 ? "-" : ""}
                    {Math.abs(pos.unrealized_pnl_pct).toFixed(2)}%
                  </div>
                </div>

                {/* Held */}
                <span className="text-[10px] text-t-gdim text-right font-mono-t">
                  {fmtHeld(pos.held_seconds)}
                </span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Portfolio hero ────────────────────────────────────────────────────────────

function dollars(cents: number): string {
  const usd = cents / 100;
  const abs = Math.abs(usd);
  if (abs >= 1_000_000_000) return `$${(abs / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000)     return `$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000)         return `$${(abs / 1_000).toFixed(1)}k`;
  return `$${abs.toFixed(2)}`;
}

function PortfolioHeroSkeleton() {
  return (
    <div className="bg-t-bg0 border border-t-dim rounded-2xl p-6 animate-pulse space-y-5">
      <div className="h-4 w-40 bg-t-bg1 rounded" />
      <div className="grid grid-cols-3 gap-6">
        {[0, 1, 2].map((i) => (
          <div key={i} className="space-y-2">
            <div className="h-8 w-32 bg-t-bg1 rounded" />
            <div className="h-3 w-24 bg-t-bg1 rounded" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-4 gap-4 pt-4 border-t border-t-dim">
        {[0, 1, 2, 3].map((i) => <div key={i} className="h-8 bg-t-bg1 rounded" />)}
      </div>
      <div className="h-28 bg-t-bg1 rounded-xl" />
      <div className="space-y-2 pt-4 border-t border-t-dim">
        {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="h-9 bg-t-bg1 rounded-xl" />)}
      </div>
    </div>
  );
}

function PortfolioHero({ onNavigateBot }: { onNavigateBot: (name: string) => void }) {
  const [chartSymbol, setChartSymbol] = useState<string | null>(null);
  const tabSectionRef = useRef<HTMLDivElement>(null);

  const { data: p, isLoading } = useQuery({
    queryKey: ["strategy-lab-portfolio"],
    queryFn: getStrategyLabPortfolio,
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 0,
  });

  const { data: portsData } = useQuery({
    queryKey: ["strategy-portfolios"],
    queryFn: getPortfolios,
    staleTime: 60_000,
    retry: 0,
  });

  // Shared cache key with OpenPositionsPanel — no extra network request
  const { data: openPosData } = useQuery({
    queryKey: ["open-positions"],
    queryFn: getOpenPositions,
    refetchInterval: 60_000,
    staleTime: 25_000,
    retry: 0,
  });

  const { data: rawWatchlists } = useQuery<CrossBotWatchlistItem[]>({
    queryKey: ["cross-bot-watchlist"],
    queryFn: getCrossBotWatchlist,
    refetchInterval: 120_000,
    staleTime: 60_000,
  });
  const watchlistItems: CrossBotWatchlistItem[] = Array.isArray(rawWatchlists) ? rawWatchlists : [];

  if (isLoading) return <PortfolioHeroSkeleton />;

  const totalVal   = (p?.total_value_cents ?? 0) / 100;
  const yestVal    = (p?.yesterday_value_cents ?? 0) / 100;
  const todayPnl   = (p?.today_pnl_cents ?? 0) / 100;
  const todayPos   = todayPnl >= 0;
  const ret30      = p?.return_30d_pct ?? 0;
  const ret30Pos   = ret30 >= 0;
  const retAll     = p?.return_all_time_pct ?? 0;

  return (
    <>
    <BracketFrame className="rounded-2xl p-6 space-y-5 bg-t-bg0 border border-t-dim" glow>
      {/* Header */}
      <div className="flex items-center justify-between">
        <SectionLabel as="h2">Strategy Lab Portfolio</SectionLabel>
        <span className="text-[10px] text-t-gdim font-ui-t">Live · refreshes every 60 s</span>
      </div>

      {/* Primary metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        <div>
          <p className="text-3xl font-bold text-t-hi tabular-nums font-mono-t">
            ${totalVal.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </p>
          <p className="text-xs text-t-dim mt-1 font-ui-t">Total Portfolio Value</p>
          {yestVal > 0 && (
            <p className="text-[11px] text-t-gdim mt-0.5 font-ui-t">
              from ${yestVal.toLocaleString("en-US", { minimumFractionDigits: 2 })} yesterday
            </p>
          )}
        </div>
        <div>
          <p className={cn("text-3xl font-bold tabular-nums font-mono-t", todayPos ? "text-t-green" : "text-t-red")}>
            {todayPos ? "+" : "−"}${Math.abs(todayPnl).toLocaleString("en-US", { minimumFractionDigits: 2 })}
          </p>
          <p className="text-xs text-t-dim mt-1 font-ui-t">Today's P&L</p>
          <p className="text-[11px] text-t-gdim mt-0.5 font-ui-t">across {p?.leaderboard?.length ?? 6} bots</p>
        </div>
        <div>
          <p className={cn("text-3xl font-bold tabular-nums font-mono-t", ret30Pos ? "text-t-green" : "text-t-red")}>
            {formatPct(ret30)}
          </p>
          <p className="text-xs text-t-dim mt-1 font-ui-t">30d Return</p>
          {(p?.return_30d_value_cents ?? 0) !== 0 && (
            <p className="text-[11px] text-t-gdim mt-0.5 font-ui-t">
              {dollars(Math.abs(p!.return_30d_value_cents))} {ret30Pos ? "gain" : "loss"}
            </p>
          )}
        </div>
      </div>

      {/* Secondary metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 pt-3 border-t border-t-dim">
        {[
          { label: "All-time Return", val: formatPct(retAll), color: retAll >= 0 ? "text-t-green" : "text-t-red", onClick: undefined },
          { label: "Open Positions",  val: String(p?.total_open_positions ?? 0), color: "text-t-hi", onClick: undefined },
          {
            label: "Watchlists", val: `${p?.total_watchlist_count ?? 0} names`, color: "text-t-green",
            onClick: () => {
              setTimeout(() => tabSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
            },
          },
        ].map(({ label, val, color, onClick }) => (
          <div key={label} onClick={onClick} className={onClick ? "cursor-pointer group" : ""}>
            <p className="text-[11px] text-t-gdim font-ui-t">{label}</p>
            <p className={cn("text-sm font-semibold mt-0.5 font-mono-t tabular-nums", color, onClick && "group-hover:underline underline-offset-2")}>{val}</p>
          </div>
        ))}
      </div>

      {/* Allocation donut — deployed capital by asset class vs cash */}
      {(p?.total_value_cents ?? 0) > 0 && (() => {
        const totalCents = p!.total_value_cents;
        const openPos = openPosData?.positions ?? [];
        const byClass: Record<string, number> = {};
        for (const pos of openPos) {
          const cls = pos.asset_class ?? "other";
          byClass[cls] = (byClass[cls] ?? 0) + Math.round((pos.current_value_usd ?? 0) * 100);
        }
        const deployedCents = Object.values(byClass).reduce((s, v) => s + v, 0);
        const cashCents = Math.max(0, totalCents - deployedCents);
        const slices = [
          ...Object.entries(byClass).filter(([, v]) => v > 0).map(([key, value_cents]) => ({ key, value_cents })),
          ...(cashCents > 0 ? [{ key: "cash", value_cents: cashCents }] : []),
        ];
        if (slices.length === 0) return null;
        return (
          <div className="pt-3 border-t border-t-dim">
            <SectionLabel as="p" className="mb-3">Capital Allocation</SectionLabel>
            <AllocationDonut totalCents={totalCents} slices={slices} />
          </div>
        );
      })()}

      {/* Open Positions — replaces equity curve until we have multi-day history */}
      <OpenPositionsPanel />

      {/* Watchlist */}
      <div ref={tabSectionRef} className="pt-3 border-t border-t-dim">
        <SectionLabel as="p" className="mb-3">
          Watchlist — {watchlistItems.length} name{watchlistItems.length !== 1 ? "s" : ""}
        </SectionLabel>
        {watchlistItems.length === 0 ? (
          <p className="text-t-gdim text-xs py-3 text-center font-ui-t">Watchlist rebuilds at 8:30am ET. Check back after market open.</p>
        ) : (
          <div className="space-y-1">
            {watchlistItems.map((item) => (
              <div
                key={item.symbol}
                onClick={() => setChartSymbol(item.symbol)}
                className="flex items-center gap-2 px-3 py-2 rounded-xl bg-t-bg1/50 border border-t-dim/80 cursor-pointer hover:bg-t-bg2/50 hover:border-t-mid transition-colors card-hover"
              >
                <span className="text-xs font-bold text-t-hi w-14 flex-shrink-0 font-mono-t">{item.symbol}</span>
                <span className="text-[10px] text-t-dim flex-1 font-ui-t">{item.bots_watching.map((b) => b.replace(/_/g, " ")).join(", ")}</span>
                <span className="text-[10px] text-t-dim w-16 text-right capitalize font-ui-t">{item.status}</span>
                <span className="text-[10px] text-t-dim w-14 text-right tabular-nums font-mono-t">score {item.score.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </BracketFrame>
    <SymbolChartDrawer symbol={chartSymbol} onClose={() => setChartSymbol(null)} />
    </>
  );
}

// ─── Standalone Bot Leaderboard ──────────────────────────────────────────────

function BotLeaderboardSection({ onNavigateBot }: { onNavigateBot: (name: string) => void }) {
  const { data: p } = useQuery({
    queryKey: ["strategy-lab-portfolio"],
    queryFn: getStrategyLabPortfolio,
    staleTime: 30_000,
    retry: 0,
  });
  const entries = p?.leaderboard ?? [];
  if (!entries.length) return null;

  return (
    <div>
      <p className="panel-header mb-3">// BOT LEADERBOARD</p>
      <div className="bg-t-bg0 border border-t-dim rounded-2xl overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-t-dim/50 bg-t-bg1/40">
          <span className="w-4 flex-shrink-0" />
          <span className="w-1.5 h-1.5 flex-shrink-0" />
          <span className="flex-1" />
          <span className="text-[10px] uppercase tracking-widest text-t-gdim font-mono-t w-20 text-right">All-Time</span>
          <span className="w-24" />
          <span className="text-[10px] uppercase tracking-widest text-t-gdim font-mono-t w-28 text-right">Deployed</span>
          <span className="w-14" />
        </div>
        <div className="space-y-0">
          {entries.map((entry) => {
            const ret30 = entry.return_30d_pct ?? null;
            const ePos = (ret30 ?? 0) >= 0;
            const tPnl = entry.today_pnl_cents / 100;
            const tPos = tPnl >= 0;
            const isCrypto = entry.profile.includes("crypto");
            const isOptions = entry.profile.includes("options") && !["options_income", "options_directional"].includes(entry.profile);
            // deployed_cents + starting_capital_cents added in canonical.py
            // but not yet typed on PortfolioLeaderboardEntry — cast to read.
            const ext = entry as unknown as {
              deployed_cents?: number;
              starting_capital_cents?: number;
            };
            const deployedCents = ext.deployed_cents ?? 0;
            const startingCents = ext.starting_capital_cents ?? 0;
            const deployedPct = startingCents > 0 ? (deployedCents / startingCents) * 100 : 0;
            const startingUsd = startingCents / 100;
            const startingLabel = startingUsd >= 1_000_000
              ? `$${(startingUsd / 1_000_000).toFixed(2)}M`
              : startingUsd >= 1_000
              ? `$${(startingUsd / 1_000).toFixed(0)}k`
              : `$${startingUsd.toFixed(0)}`;
            return (
              <button
                key={entry.profile}
                onClick={() => onNavigateBot(entry.profile)}
                className="w-full flex items-center gap-2 px-4 py-2.5 border-b border-t-dim/50 last:border-0 hover:bg-t-bg1/60 transition-colors text-left card-hover"
              >
                <span className="text-[10px] font-bold text-t-gdim w-4 flex-shrink-0 font-mono-t">#{entry.rank}</span>
                <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", isOptions ? "bg-purple-400" : isCrypto ? "bg-t-amber" : entry.profile.includes("quant") ? "bg-violet-400" : "bg-t-cyan")} />
                <span className="flex-1 text-xs font-semibold text-t-hi truncate font-ui-t">{entry.name}</span>
                <span className={cn("text-xs font-bold w-20 text-right tabular-nums font-mono-t", ret30 != null ? (ePos ? "text-t-green" : "text-t-red") : "text-t-gdim")}>
                  {ret30 != null ? `${ret30 >= 0 ? "+" : ""}${ret30.toFixed(2)}%` : "—"}
                </span>
                <span className={cn("text-xs w-24 text-right tabular-nums font-mono-t", tPos ? "text-t-green" : "text-t-red")}>
                  {tPos ? "+" : "−"}${Math.abs(tPnl).toFixed(2)} today
                </span>
                <span className="text-[10px] w-28 text-right tabular-nums font-mono-t text-t-mid2">
                  {startingCents > 0
                    ? `${deployedPct.toFixed(0)}% of ${startingLabel}`
                    : "—"}
                </span>
                <span className="text-[10px] text-t-gdim w-14 text-right flex-shrink-0 font-ui-t">
                  {entry.watchlist_count > 0 ? `${entry.watchlist_count} names` : "—"}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ─── Portfolio panel ──────────────────────────────────────────────────────────

function PortfolioTab({ portfolio }: { portfolio: StrategyPortfolio }) {
  const navigate = useNavigate();
  const currentUsd = portfolio.current_value_cents / 100;
  // Sleeve cards show TODAY's P&L so they line up with the per-bot leaderboard
  // below (also today). Previously read pnl_cents which is all-time — that's
  // what made "today" sleeves total -$5.5K while the leaderboard summed to -$114.
  const todayCents = portfolio.today_pnl_cents ?? portfolio.pnl_cents;
  const todayPct   = portfolio.today_pnl_pct   ?? portfolio.pnl_pct;
  const pnlUsd = todayCents / 100;
  const isPositive = todayPct >= 0;

  return (
    <button
      onClick={() => navigate(`/strategy/portfolio/${portfolio.asset_class}`)}
      className="flex-1 min-w-0 rounded-2xl border-2 border-t-dim bg-t-bg0 p-4 text-left transition-all duration-150 hover:border-t-mid hover:bg-t-bg1/60 group card-hover"
      style={{ "--accent": portfolio.color_hex } as React.CSSProperties}
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xl">{portfolio.emoji}</span>
        <span className="font-bold text-t-hi text-sm group-hover:text-t-hi font-ui-t">{portfolio.name}</span>
        <span className="ml-auto text-t-gdim group-hover:text-t-muted text-xs">→</span>
      </div>
      <div className="text-lg font-bold text-t-hi leading-tight tabular-nums font-mono-t">
        ${currentUsd.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
      </div>
      <div className={cn("text-xs font-medium mt-0.5 tabular-nums font-mono-t", isPositive ? "text-t-green" : "text-t-red")}>
        {isPositive ? "+" : ""}{pnlUsd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        {" "}({isPositive ? "+" : ""}{todayPct.toFixed(2)}% today)
      </div>
      <div className="text-[11px] text-t-gdim mt-1 font-ui-t">
        {formatSleeveSubtitle(portfolio.bots)}
      </div>
    </button>
  );
}

// ─── Skeleton card ────────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5 animate-pulse">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="h-5 w-32 bg-t-bg1 rounded mb-2" />
          <div className="h-3 w-48 bg-t-bg1 rounded" />
        </div>
        <div className="h-6 w-6 bg-t-bg1 rounded-full" />
      </div>
      <div className="flex gap-2 mb-4">
        <div className="h-5 w-14 bg-t-bg1 rounded-full" />
        <div className="h-5 w-16 bg-t-bg1 rounded-full" />
        <div className="h-5 w-16 bg-t-bg1 rounded-full" />
      </div>
      <div className="grid grid-cols-2 gap-3 mb-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i}>
            <div className="h-3 w-20 bg-t-bg1 rounded mb-1" />
            <div className="h-5 w-14 bg-t-bg1 rounded" />
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <div className="h-8 flex-1 bg-t-bg1 rounded-lg" />
        <div className="h-8 flex-1 bg-t-bg1 rounded-lg" />
      </div>
    </div>
  );
}

// ─── Bot card ─────────────────────────────────────────────────────────────────

interface BotCardProps {
  item: BotListItem;
  onNavigate: (name: string) => void;
  isViewer?: boolean;
  tier?: string;
}

const _TIER_BADGE: Record<string, string> = {
  T3: "text-t-green border-t-green/30 bg-t-green/10",
  T2: "text-t-cyan border-t-cyan/30 bg-t-cyan/10",
  T1: "text-t-amber border-t-amber/30 bg-t-amber/10",
  T0: "text-t-muted border-t-mid/30 bg-t-bg2/10",
};

function BotCard({ item, onNavigate, isViewer, tier }: BotCardProps) {
  const { profile, allocation, stats } = item;
  const meta = BOT_META[profile.name];
  const qc = useQueryClient();
  const assetClass = meta?.assetClass ?? profile.asset_class;

  const allocateMut = useMutation({
    mutationFn: (enabled: boolean) =>
      allocateBot(profile.name, {
        capital_pct: allocation?.capital_pct ?? 10,
        risk_profile: allocation?.risk_profile ?? "standard",
        enabled,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bots-v2"] });
      toast.success(
        allocation?.enabled ? `${displayName(profile.name)} disabled` : `${displayName(profile.name)} enabled`
      );
    },
    onError: () => toast.error("Failed to update bot"),
  });

  const waitlistMut = useMutation({
    mutationFn: (joining: boolean) =>
      joining ? joinWaitlist(profile.name) : leaveWaitlist(profile.name),
    onSuccess: (_data, joining) => {
      qc.invalidateQueries({ queryKey: ["bots-v2"] });
      toast.success(joining ? "Added to live waitlist" : "Removed from waitlist");
    },
    onError: () => toast.error("Failed to update waitlist"),
  });

  const runNowMut = useMutation({
    mutationFn: () => runBotNow(profile.name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bots-v2"] });
      toast.success(`${displayName(profile.name)} executed a trade cycle`);
    },
    onError: () => toast.error("Run failed — check that the bot is enabled"),
  });

  const isEnabled = allocation?.enabled ?? false;
  const isComingSoon = allocation?.paused_reason === "coming_soon";
  const isAdminLocked = allocation?.paused_reason === "admin_lock" || allocation?.paused_reason === "health_halt";
  const isOnWaitlist = allocation?.go_live_requested ?? false;

  const pnlPositive = (stats?.today_pnl ?? 0) >= 0;
  const returnPositive = (stats?.return_30d_pct ?? 0) >= 0;

  // Left border color by asset class
  const leftBorderClass = assetClass === "options"
    ? "border-l-4 border-l-purple-500/60"
    : assetClass === "quant"
      ? "border-l-4 border-l-violet-500/60"
      : assetClass === "crypto"
        ? "border-l-4 border-l-t-amber/60"
        : "border-l-4 border-l-t-cyan/60";

  return (
    <div
      className={cn(
        "bg-t-bg0 border border-t-dim rounded-2xl p-5 cursor-pointer hover:border-t-mid transition-colors group card-hover",
        leftBorderClass
      )}
      onClick={() => onNavigate(profile.name)}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-t-hi font-semibold text-base leading-snug font-ui-t">
            {meta?.displayName ?? displayName(profile.name)}
          </h3>
          <p className="text-t-dim text-xs mt-0.5 leading-relaxed font-ui-t">
            {meta?.description ?? profile.description}
          </p>
        </div>
        <span
          className={cn(
            "text-xs font-semibold px-2 py-0.5 rounded-full font-ui-t",
            isComingSoon
              ? "bg-purple-500/15 text-purple-400 border border-purple-500/30"
              : isAdminLocked
                ? "bg-amber-500/15 text-amber-400 border border-amber-500/30"
                : isEnabled
                  ? "bg-t-green/15 text-t-green border border-t-green/30"
                  : "bg-t-bg1 text-t-dim border border-t-dim"
          )}
        >
          {isComingSoon ? "COMING SOON" : isAdminLocked ? "frozen · historical" : isEnabled ? "ACTIVE" : "DISABLED"}
        </span>
      </div>

      {/* Badges */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        <span
          className={cn(
            "text-xs font-semibold px-2 py-0.5 rounded-full font-ui-t",
            assetClass === "stock"
              ? "bg-t-cyan/15 text-t-cyan border border-t-cyan/30"
              : assetClass === "quant"
                ? "bg-violet-500/15 text-violet-400 border border-violet-500/30"
                : "bg-t-amber/15 text-t-amber border border-t-amber/30"
          )}
        >
          {assetClass.toUpperCase()}
        </span>
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-t-bg1 text-t-muted border border-t-dim font-ui-t">
          {formatCadence(profile.cadence)}
        </span>
        {tier && (
          <span className={cn("text-xs font-bold px-2 py-0.5 rounded-full border font-ui-t", _TIER_BADGE[tier] ?? _TIER_BADGE.T1)}>
            {tier}
          </span>
        )}
      </div>

      {/* All-time P&L banner */}
      {stats?.all_time_pnl_pct != null ? (
        <div className={cn(
          "flex items-center justify-between px-3 py-2 rounded-lg mb-3 border",
          stats.all_time_pnl_pct >= 0
            ? "bg-t-green/5 border-t-green/20"
            : "bg-t-red/5 border-t-red/20"
        )}>
          <span className="text-xs font-medium text-t-dim font-ui-t">ALL-TIME</span>
          <span className={cn(
            "text-sm font-bold tabular-nums font-mono-t",
            stats.all_time_pnl_pct >= 0 ? "text-t-green" : "text-t-red"
          )}>
            {stats.all_time_pnl_pct >= 0 ? "+" : ""}{stats.all_time_pnl_pct.toFixed(2)}%
          </span>
          {stats.all_time_pnl_usd != null && (
            <span className={cn(
              "text-xs tabular-nums font-mono-t",
              stats.all_time_pnl_usd >= 0 ? "text-t-green/70" : "text-t-red/70"
            )}>
              {formatPnl(stats.all_time_pnl_usd)}
            </span>
          )}
        </div>
      ) : (
        <div className="flex items-center justify-between px-3 py-2 rounded-lg mb-3 border border-t-dim bg-t-bg0/40">
          <span className="text-xs font-medium text-t-dim font-ui-t">ALL-TIME</span>
          <span className="text-xs text-t-gdim italic font-ui-t">Not live yet</span>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <p className="text-t-gdim text-xs mb-0.5 font-ui-t">Today P&L (paper)</p>
          <p
            className={cn(
              "text-sm font-semibold tabular-nums font-mono-t",
              pnlPositive ? "text-t-green" : "text-t-red"
            )}
          >
            {formatPnl(stats?.today_pnl ?? 0)}
          </p>
        </div>
        <div>
          <p className="text-t-gdim text-xs mb-0.5 font-ui-t">30d Return</p>
          <p
            className={cn(
              "text-sm font-semibold tabular-nums font-mono-t",
              returnPositive ? "text-t-green" : "text-t-red"
            )}
          >
            {formatPct(stats?.return_30d_pct ?? 0)}
          </p>
        </div>
        <div>
          <p className="text-t-gdim text-xs mb-0.5 font-ui-t">Open Positions</p>
          <p className="text-sm font-semibold text-t-hi tabular-nums font-mono-t">
            {stats?.open_positions ?? 0}
          </p>
        </div>
        <div>
          <p className="text-t-gdim text-xs mb-0.5 font-ui-t">Capital Allocated</p>
          <p className="text-sm font-semibold text-t-hi tabular-nums font-mono-t">
            {(() => {
              if (!allocation) return "—";
              const dollars = formatDollarsWhole(stats?.starting_capital_usd ?? null);
              const sleevePct = allocation.sleeve_pct;
              if (dollars && sleevePct != null) {
                return `${dollars} · ${sleevePct.toFixed(1)}% of sleeve`;
              }
              if (dollars) return dollars;
              if (sleevePct != null) return `${sleevePct.toFixed(1)}% of sleeve`;
              // Fallback to legacy stale field only when both canonical values are unavailable
              return `${allocation.capital_pct}%`;
            })()}
          </p>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
        {!isViewer && (
          <>
            <button
              onClick={() => allocateMut.mutate(!isEnabled)}
              disabled={allocateMut.isPending}
              className={cn(
                "flex-1 text-xs font-semibold py-2 rounded-lg border transition-colors font-ui-t",
                isEnabled
                  ? "bg-t-bg1 border-t-dim text-t-mid2 hover:border-t-red/70 hover:text-t-red"
                  : "bg-t-green/10 border-t-green/30 text-t-green hover:bg-t-green/20"
              )}
            >
              {allocateMut.isPending ? "…" : isEnabled ? "Disable" : "Enable"}
            </button>
            {isEnabled && (
              <button
                onClick={() => runNowMut.mutate()}
                disabled={runNowMut.isPending}
                className="text-xs font-semibold py-2 px-3 rounded-lg border border-t-cyan/30 bg-t-cyan/10 text-t-cyan hover:bg-t-cyan/20 transition-colors disabled:opacity-50 font-ui-t"
                title="Manually trigger a trade cycle"
              >
                {runNowMut.isPending ? "…" : "▶ Run"}
              </button>
            )}
          </>
        )}
        <button
          onClick={() => waitlistMut.mutate(!isOnWaitlist)}
          disabled={waitlistMut.isPending}
          className={cn(
            "flex-1 text-xs font-semibold py-2 rounded-lg border transition-colors font-ui-t",
            isOnWaitlist
              ? "bg-t-amber/10 border-t-amber/30 text-t-amber hover:bg-t-amber/20"
              : "bg-t-bg1 border-t-dim text-t-muted hover:border-t-amber/60 hover:text-t-amber"
          )}
        >
          {waitlistMut.isPending ? "…" : isOnWaitlist ? "✓ Notified" : "Notify when live"}
        </button>
      </div>
    </div>
  );
}

// ─── Comparison table ─────────────────────────────────────────────────────────

type CompSortKey = "name" | "status" | "return_30d" | "sharpe" | "max_dd" | "uptime";
type SortDir = "asc" | "desc";

function ComparisonTable({ bots, tierByAllocId = {} }: { bots: BotListItem[]; tierByAllocId?: Record<number, string> }) {
  const [sortKey, setSortKey] = useState<CompSortKey>("return_30d");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function handleSort(key: CompSortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  const sortedBots = [...bots].sort((a, b) => {
    let aVal: string | number = 0;
    let bVal: string | number = 0;
    switch (sortKey) {
      case "name":
        aVal = displayName(a.profile.name);
        bVal = displayName(b.profile.name);
        break;
      case "status":
        aVal = a.allocation?.enabled ? 1 : 0;
        bVal = b.allocation?.enabled ? 1 : 0;
        break;
      case "return_30d":
        aVal = a.stats?.return_30d_pct ?? 0;
        bVal = b.stats?.return_30d_pct ?? 0;
        break;
      case "sharpe":
        // Demo: deterministic from return
        aVal = (a.stats?.return_30d_pct ?? 0) / 8;
        bVal = (b.stats?.return_30d_pct ?? 0) / 8;
        break;
      case "max_dd":
        aVal = a.stats?.return_30d_pct ?? 0;
        bVal = b.stats?.return_30d_pct ?? 0;
        break;
      case "uptime":
        aVal = a.stats?.win_rate_pct ?? 0;
        bVal = b.stats?.win_rate_pct ?? 0;
        break;
    }
    if (typeof aVal === "string" && typeof bVal === "string") {
      return sortDir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    }
    return sortDir === "asc" ? (aVal as number) - (bVal as number) : (bVal as number) - (aVal as number);
  });

  function SortHeader({ label, colKey }: { label: string; colKey: CompSortKey }) {
    const active = sortKey === colKey;
    return (
      <th
        className="text-left pb-2 font-medium cursor-pointer select-none hover:text-t-mid2 transition-colors font-ui-t"
        onClick={() => handleSort(colKey)}
      >
        <span className="flex items-center gap-1">
          {label}
          <span className="text-t-gdim">
            {active ? (sortDir === "asc" ? "↑" : "↓") : "↕"}
          </span>
        </span>
      </th>
    );
  }

  return (
    <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5">
      <h2 className="panel-header mb-4">// Side-by-Side Comparison</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-t-gdim border-b border-t-dim">
              <SortHeader label="Bot" colKey="name" />
              <SortHeader label="Status" colKey="status" />
              <SortHeader label="Tier" colKey="name" />
              <SortHeader label="30d Return" colKey="return_30d" />
              <SortHeader label="Max DD" colKey="max_dd" />
              <SortHeader label="Uptime" colKey="uptime" />
            </tr>
          </thead>
          <tbody>
            {sortedBots.filter((item) => item.allocation?.paused_reason !== "coming_soon").map((item) => {
              const isEnabled = item.allocation?.enabled ?? false;
              const ret30 = item.stats?.return_30d_pct ?? 0;
              const maxDd: string | null = null; // populated when backend exposes max_drawdown_pct
              const winRate = item.stats?.win_rate_pct ?? 0;
              const assetClass = BOT_META[item.profile.name]?.assetClass ?? item.profile.asset_class;

              return (
                <tr key={item.profile.name} className="border-b border-t-dim/50 last:border-0 hover:bg-t-bg1/20 transition-colors">
                  <td className="py-2.5">
                    <div className="flex items-center gap-2">
                      <span className={cn("w-2 h-2 rounded-full flex-shrink-0", assetClass === "options" ? "bg-purple-400" : assetClass === "quant" ? "bg-violet-400" : assetClass === "crypto" ? "bg-t-amber" : "bg-t-cyan")} />
                      <span className="font-semibold text-t-hi text-xs font-ui-t">{displayName(item.profile.name)}</span>
                    </div>
                  </td>
                  <td className="py-2.5">
                    <span className={cn(
                      "text-xs font-bold px-1.5 py-0.5 rounded-full border font-ui-t",
                      isEnabled
                        ? "bg-t-green/15 text-t-green border-t-green/30"
                        : "bg-t-bg1 text-t-dim border-t-dim"
                    )}>
                      {isEnabled ? "ACTIVE" : "DISABLED"}
                    </span>
                  </td>
                  <td className="py-2.5">
                    {item.allocation?.id != null && tierByAllocId[item.allocation.id] ? (
                      <span className={cn("text-xs font-bold px-1.5 py-0.5 rounded-full border font-ui-t", _TIER_BADGE[tierByAllocId[item.allocation.id]] ?? _TIER_BADGE.T1)}>
                        {tierByAllocId[item.allocation.id]}
                      </span>
                    ) : (
                      <span className="text-xs text-t-gdim font-ui-t">—</span>
                    )}
                  </td>
                  <td className={cn("py-2.5 font-semibold text-xs tabular-nums font-mono-t", ret30 >= 0 ? "text-t-green" : "text-t-red")}>
                    {formatPct(ret30)}
                  </td>
                  <td className="py-2.5 text-xs text-t-red tabular-nums font-mono-t">
                    {maxDd != null ? `-${maxDd}%` : "—"}
                  </td>
                  <td className="py-2.5 text-xs text-t-mid2 tabular-nums font-mono-t">
                    {winRate > 0 ? `${winRate.toFixed(1)}%` : "—"}
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

// ─── Candidate cards ──────────────────────────────────────────────────────────

type CandidateAssetClass = "equity" | "crypto" | "multi";
type CandidateStyle = "momentum" | "mean_reversion" | "event_driven" | "arbitrage" | "cross_asset_momentum" | "quality_momentum" | "short_volatility";

interface CandidateEntry {
  id: string;
  name: string;
  assetClass: CandidateAssetClass;
  style: CandidateStyle;
  reference: string;
  expectedSharpe: string;
  description: string;
}

const _ASSET_CHIP: Record<CandidateAssetClass, string> = {
  equity: "bg-t-cyan/10 text-t-cyan border-t-cyan/20",
  crypto: "bg-t-amber/10 text-t-amber border-t-amber/20",
  multi:  "bg-violet-500/10 text-violet-400 border-violet-500/20",
};
const _ASSET_LABEL: Record<CandidateAssetClass, string> = {
  equity: "Equity",
  crypto: "Crypto",
  multi:  "Multi-Asset",
};
const _STYLE_CHIP: Record<CandidateStyle, string> = {
  momentum:             "bg-t-green/10 text-t-green border-t-green/20",
  mean_reversion:       "bg-t-cyan/10 text-t-cyan border-t-cyan/20",
  event_driven:         "bg-t-amber/10 text-t-amber border-t-amber/20",
  arbitrage:            "bg-pink-500/10 text-pink-400 border-pink-500/20",
  cross_asset_momentum: "bg-violet-500/10 text-violet-400 border-violet-500/20",
  quality_momentum:     "bg-t-bright/10 text-t-bright border-t-bright/20",
  short_volatility:     "bg-t-red/10 text-t-red border-t-red/20",
};
const _STYLE_LABEL: Record<CandidateStyle, string> = {
  momentum:             "Momentum",
  mean_reversion:       "Mean Rev",
  event_driven:         "Event",
  arbitrage:            "Arbitrage",
  cross_asset_momentum: "Cross-Asset",
  quality_momentum:     "Quality",
  short_volatility:     "Short Vol",
};

function CandidateCard({ c }: { c: CandidateEntry }) {
  return (
    <div className="relative rounded-2xl border border-dashed border-t-dim/60 bg-t-bg0/60 p-4 flex flex-col gap-3 hover:border-t-mid/80 transition-colors">
      {/* Watermark */}
      <div className="absolute top-2 right-3 text-[9px] font-bold tracking-widest text-t-gdim uppercase select-none font-ui-t">
        INCUBATING
      </div>

      {/* Header */}
      <div className="flex items-start gap-2 pr-16">
        <div>
          <p className="text-sm font-semibold text-t-mid2 leading-snug font-ui-t">{c.name}</p>
          <p className="text-[10px] text-t-gdim mt-0.5 font-mono-t">{c.reference}</p>
        </div>
      </div>

      {/* Chips */}
      <div className="flex flex-wrap gap-1.5">
        <span className={cn("text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border font-ui-t", _ASSET_CHIP[c.assetClass])}>
          {_ASSET_LABEL[c.assetClass]}
        </span>
        <span className={cn("text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border font-ui-t", _STYLE_CHIP[c.style])}>
          {_STYLE_LABEL[c.style]}
        </span>
        <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border bg-t-amber/10 text-t-amber border-t-amber/20 font-ui-t">
          T0 CANDIDATE
        </span>
      </div>

      {/* Description */}
      <p className="text-xs text-t-dim leading-relaxed font-ui-t">{c.description}</p>

      {/* Sharpe range */}
      <div className="flex items-center justify-between text-[10px]">
        <span className="text-t-gdim font-ui-t">Expected Sharpe</span>
        <span className="font-mono-t tabular-nums text-t-muted">{c.expectedSharpe}</span>
      </div>

      {/* Promotion criteria */}
      <div className="rounded-lg bg-t-bg0/60 border border-t-dim px-3 py-2">
        <p className="text-[9px] font-semibold text-t-gdim uppercase tracking-wider mb-0.5 font-ui-t">Promotes to T1 when</p>
        <p className="text-[10px] text-t-dim font-ui-t">30 days live · 20 trades · Sharpe &gt; 0.3</p>
      </div>
    </div>
  );
}

function CandidatesSection() {
  const { data: candidatesData } = useQuery({
    queryKey: ["strategy-lab-candidates"],
    queryFn: getStrategyLabCandidates,
    staleTime: 300_000,
    retry: 0,
  });
  const incubationCount = candidatesData?.candidates?.length ?? CANDIDATE_META.length;

  return (
    <div>
      {/* Section header */}
      <div className="flex items-center gap-3 mb-3">
        <div className="flex-1 h-px border-t border-dashed border-t-dim" />
        <p className="text-[10px] font-semibold text-t-dim uppercase tracking-widest whitespace-nowrap font-ui-t">
          // CANDIDATES (paper-shadow, not live)
        </p>
        <div className="flex-1 h-px border-t border-dashed border-t-dim" />
      </div>
      <p className="text-xs text-t-gdim mb-4 font-ui-t">
        {incubationCount} strategies in incubation. Tracked in paper mode only.
        Manual graduation required to promote to live trading.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {CANDIDATE_META.map((c) => (
          <CandidateCard key={c.id} c={c} />
        ))}
      </div>
    </div>
  );
}

// ─── Fallback bot list (when API returns null/error) ──────────────────────────

function makeFallbackBots(): BotListItem[] {
  return BOT_ORDER.map((name, idx) => ({
    profile: {
      id: idx + 1,
      name,
      description: BOT_META[name]?.description ?? "",
      asset_class: BOT_META[name]?.assetClass ?? "stock",
      position_cap: 10,
      cadence: name.includes("_day") ? "intraday" : name.includes("_lt") ? "weekly" : "daily",
      stop_loss_pct: null,
      take_profit_pct: null,
      paper_only: true,
      enabled: false,
    },
    allocation: null,
    stats: {
      return_30d_pct: 0,
      today_pnl: 0,
      open_positions: 0,
      total_trades: 0,
      win_rate_pct: 0,
      all_time_pnl_pct: null,
      all_time_pnl_usd: null,
      starting_capital_usd: null,
      current_equity_usd: null,
    },
  }));
}

// ─── Activity feed time format ────────────────────────────────────────────────

function timeAgo(ts: string): string {
  try {
    const diff = Date.now() - new Date(ts).getTime();
    const m = Math.floor(diff / 60000);
    const h = Math.floor(diff / 3600000);
    const d = Math.floor(diff / 86400000);
    if (d >= 1) return `${d}d ago`;
    if (h >= 1) return `${h}h ago`;
    if (m >= 1) return `${m}m ago`;
    return "just now";
  } catch {
    return "";
  }
}

// ─── Right-rail activity feed ─────────────────────────────────────────────────

function ActivityRail({ onClose }: { onClose: () => void }) {
  const { data: feed = [], isLoading } = useQuery({
    queryKey: ["autopilot-activity-feed"],
    queryFn: () => getAutopilotActivity({ page: 1 }),
    refetchInterval: 30_000,
    staleTime: 20_000,
    retry: 0,
  });

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-t-muted uppercase tracking-wide font-ui-t">
          Activity
        </span>
        <button
          onClick={onClose}
          className="text-t-gdim hover:text-t-hi text-xs transition-colors font-ui-t"
        >
          ‹ Hide
        </button>
      </div>
      {isLoading ? (
        <div className="space-y-2 animate-pulse">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="h-10 bg-t-bg1 rounded-lg" />
          ))}
        </div>
      ) : feed.length === 0 ? (
        <p className="text-t-gdim text-xs text-center py-6 font-ui-t">No activity yet. The execution engine runs daily at 10 AM ET on weekdays.</p>
      ) : (
        <div className="space-y-1 overflow-y-auto flex-1">
          {feed.slice(0, 20).map((item: AutopilotAction) => (
            <div
              key={item.id}
              className="bg-t-bg0 border border-t-dim rounded-lg px-3 py-2 text-xs"
            >
              <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                <span className="px-1.5 py-0.5 rounded bg-t-bg1 border border-t-dim text-t-muted font-medium text-xs font-ui-t">
                  {item.category?.replace(/_/g, " ")}
                </span>
                {item.asset && (
                  <span className="font-semibold text-t-hi font-mono-t">{item.asset}</span>
                )}
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-t-dim truncate font-ui-t">
                  {item.action_type?.replace(/_/g, " ")}
                </span>
                <span className="text-t-gdim whitespace-nowrap flex-shrink-0 font-mono-t">
                  {timeAgo(item.created_at)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Today's Questions ────────────────────────────────────────────────────────

interface TodaysQuestionsProps {
  onAskCoPilot: (question: string) => void;
}

function TodaysQuestions({ onAskCoPilot }: TodaysQuestionsProps) {
  const [dismissed, setDismissed] = useState<Set<string | number>>(new Set());

  const { data: reviews = [] } = useQuery({
    queryKey: ["pending-reviews"],
    queryFn: getPendingReviews,
    retry: 0,
    staleTime: 60_000,
  });

  const visible = reviews.filter((r: PendingReview) => !dismissed.has(r.id));

  function dismiss(id: string | number) {
    setDismissed((prev) => new Set([...prev, id]));
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold text-t-mid2 font-ui-t">
          Today's questions for you
          {visible.length > 0 && (
            <span className="ml-2 text-xs font-bold px-1.5 py-0.5 rounded-full bg-t-amber/15 border border-t-amber/30 text-t-amber font-ui-t">
              {visible.length}
            </span>
          )}
        </h2>
      </div>

      {visible.length === 0 ? (
        <div className="bg-t-bg0 border border-t-dim rounded-xl px-4 py-6 text-center">
          <p className="text-t-dim text-sm font-ui-t">No questions today ✓</p>
          <p className="text-t-gdim text-xs mt-1 font-ui-t">All borderline signals have been reviewed.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {visible.map((r: PendingReview) => {
            const display = r.bot_name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
            const confPct = Math.round((r.confidence ?? 0) * 100);
            const timeStr = (() => {
              try {
                return new Date(r.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
              } catch {
                return r.ts;
              }
            })();
            const coPilotQ = `Why did ${display} consider ${r.side === "buy" ? "buying" : "selling"} ${r.symbol} at ${timeStr} with ${confPct}% confidence?`;

            return (
              <div
                key={r.id}
                className="bg-t-bg0 border border-t-dim rounded-xl px-4 py-3"
              >
                <p className="text-sm text-t-mid2 mb-2 font-ui-t">
                  <span className="font-semibold text-t-hi">{display}</span> considered{" "}
                  {r.side === "buy" ? "buying" : "selling"}{" "}
                  <span className="font-semibold text-t-hi font-mono-t">{r.symbol}</span> at {timeStr} —{" "}
                  confidence{" "}
                  <span className="text-t-amber font-semibold tabular-nums font-mono-t">{confPct}%</span>. Review?
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => dismiss(r.id)}
                    className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-t-dim bg-t-bg1 text-t-mid2 hover:text-t-hi transition-colors font-ui-t"
                  >
                    Looks good
                  </button>
                  <button
                    onClick={() => {
                      dismiss(r.id);
                      onAskCoPilot(coPilotQ);
                    }}
                    className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-t-cyan/30 bg-t-cyan/10 text-t-cyan hover:bg-t-cyan/20 transition-colors font-ui-t"
                  >
                    Ask Co-Pilot
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Mobile bottom nav ────────────────────────────────────────────────────────

interface BottomNavProps {
  onOpenActivity: () => void;
  onOpenCoPilot: () => void;
}

function ConvictionStars({ score }: { score: number | null }) {
  if (score == null) return <span className="text-t-gdim text-xs">—</span>;
  const filled = Math.round(score);
  return (
    <span className={score >= 4 ? "text-t-green" : score >= 3 ? "text-t-amber" : "text-t-dim"}>
      {"★".repeat(filled)}{"☆".repeat(5 - filled)}
    </span>
  );
}

function AnalystHighlights() {
  const { data: summary, isLoading } = useQuery({
    queryKey: ["analyst-summary"],
    queryFn: getAnalystSummary,
    staleTime: 300_000,
    retry: 0,
  });

  if (isLoading) {
    return (
      <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5 animate-pulse">
        <div className="h-4 w-40 bg-t-bg1 rounded mb-4" />
        <div className="grid grid-cols-3 gap-3">
          {[0, 1, 2].map(i => <div key={i} className="h-16 bg-t-bg1 rounded-xl" />)}
        </div>
      </div>
    );
  }

  const picks = summary?.top_picks ?? [];
  const concerns = summary?.concerns ?? [];
  const hasData = picks.length > 0 || concerns.length > 0;

  if (!hasData) return null;

  function SummaryCard({ item, flag }: { item: AnalystSummaryItem; flag?: boolean }) {
    return (
      <Link to="/strategy/analyst" className="block bg-t-bg1/50 border border-t-dim/50 rounded-xl p-3 hover:border-t-mid transition-colors card-hover">
        <div className="flex items-center justify-between mb-1">
          <span className="font-semibold text-t-hi text-sm font-mono-t">{item.symbol}</span>
          {flag
            ? <span className="text-xs text-t-red font-semibold font-ui-t">⚑ Flagged</span>
            : <ConvictionStars score={item.conviction_score} />}
        </div>
        <p className="text-[11px] text-t-dim leading-tight line-clamp-2 font-ui-t">{item.thesis_preview}</p>
        <p className="text-[10px] text-t-gdim mt-1 font-ui-t">{item.bot_name.replace(/_/g, " ")} · {item.suggested_hold}</p>
      </Link>
    );
  }

  return (
    <div className="bg-t-bg0 border border-t-dim rounded-2xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="panel-header">// AI Analyst Highlights</h3>
        <Link to="/strategy/analyst" className="text-xs text-t-green hover:text-t-green/80 underline underline-offset-2 font-ui-t">
          Full report →
        </Link>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {picks.length > 0 && (
          <div>
            <p className="text-[11px] text-t-dim uppercase tracking-wide font-semibold mb-2 font-ui-t">Top Picks</p>
            <div className="space-y-2">
              {picks.slice(0, 3).map(p => <SummaryCard key={p.id} item={p} />)}
            </div>
          </div>
        )}
        {concerns.length > 0 && (
          <div>
            <p className="text-[11px] text-t-dim uppercase tracking-wide font-semibold mb-2 font-ui-t">Concerns</p>
            <div className="space-y-2">
              {concerns.slice(0, 3).map(c => <SummaryCard key={c.id} item={c} flag />)}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function BottomNav({ onOpenActivity, onOpenCoPilot }: BottomNavProps) {
  const navigate = useNavigate();
  return (
    <nav className="fixed bottom-0 inset-x-0 bg-t-bg0 border-t border-t-mid md:hidden z-40">
      <div className="grid grid-cols-4 h-16">
        <button
          onClick={() => navigate("/strategy")}
          className="flex flex-col items-center justify-center gap-1 text-t-muted hover:text-t-hi transition-colors"
        >
          <span className="text-lg">⊞</span>
          <span className="text-[10px] font-medium font-ui-t">Bots</span>
        </button>
        <button
          onClick={onOpenActivity}
          className="flex flex-col items-center justify-center gap-1 text-t-muted hover:text-t-hi transition-colors"
        >
          <span className="text-lg">⚡</span>
          <span className="text-[10px] font-medium font-ui-t">Activity</span>
        </button>
        <button
          onClick={onOpenCoPilot}
          className="flex flex-col items-center justify-center gap-1 text-t-muted hover:text-t-hi transition-colors"
        >
          <span className="text-lg">⌘</span>
          <span className="text-[10px] font-medium font-ui-t">Co-Pilot</span>
        </button>
        <button
          onClick={() => navigate("/settings")}
          className="flex flex-col items-center justify-center gap-1 text-t-muted hover:text-t-hi transition-colors"
        >
          <span className="text-lg">⚙</span>
          <span className="text-[10px] font-medium font-ui-t">Settings</span>
        </button>
      </div>
    </nav>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function StrategyLab() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const isViewer = useIsViewer();
  // null = unknown (first load), true = paused, false = running
  const [allPaused, setAllPaused] = useState<boolean | null>(null);
  const [railOpen, setRailOpen] = useState(false);
  // Dispatch a custom event so the global CoPilot (rendered in App) can open with a prefill
  const openCoPilot = useCallback((q?: string) => {
    window.dispatchEvent(new CustomEvent("copilot:open", { detail: { query: q ?? "" } }));
  }, []);

  // "bots-v2" busts any persisted localStorage cache with old flat data shape
  const { data, isLoading, isError } = useQuery({
    queryKey: ["bots-v2"],
    queryFn: getBots,
    retry: 1,
  });

  // Allocation tier overview — keyed by allocation_id
  const { data: allocOverview } = useQuery({
    queryKey: ["bots-allocation-overview"],
    queryFn: () =>
      fetch("/api/bots/allocation", {
        headers: { Authorization: `Bearer ${localStorage.getItem("bmg_token") ?? ""}` },
      }).then((r) => r.json()).catch(() => ({ allocations: [] })),
    staleTime: 300_000,
    retry: 0,
  });
  const tierByAllocId: Record<number, string> = Object.fromEntries(
    (allocOverview?.allocations ?? []).map((a: { allocation_id: number; tier: string }) => [a.allocation_id, a.tier])
  );

  // Setup portfolios on mount (idempotent)
  useEffect(() => {
    setupPortfolios().catch(() => {});
  }, []);

  const { data: portfolioData, isLoading: portfoliosLoading } = useQuery({
    queryKey: ["strategy-portfolios"],
    queryFn: getPortfolios,
    staleTime: 60_000,
    retry: 0,
  });
  const portfolios: StrategyPortfolio[] = portfolioData?.portfolios ?? [];

  // Canonical headline number — same source as Dashboard + PortfolioHero.
  // /api/bots/portfolios sums per-StrategyPortfolio only and silently drops
  // orphan allocations (allocs not bound to a portfolio row), which is why
  // the per-portfolio sum can underreport vs. the canonical aggregate. We
  // read total_value_cents from /api/strategy-lab/portfolio (which routes
  // through compute_strategy_lab_aggregate → per-allocation totals) so the
  // headline always matches the rest of the app.
  const { data: labAggregate } = useQuery({
    queryKey: ["strategy-lab-portfolio"],
    queryFn: getStrategyLabPortfolio,
    staleTime: 30_000,
    retry: 0,
  });

  const { data: regime, isLoading: regimeLoading } = useQuery({
    queryKey: ["regime"],
    queryFn: getRegime,
    retry: 0,
    staleTime: 60_000,
  });

  const globalWaitlistMut = useMutation({
    mutationFn: () => joinWaitlist("*"),
    onSuccess: () => toast.success("Added to live trading waitlist"),
    onError: () => toast.error("Failed to join waitlist"),
  });

  const migrateMut = useMutation({
    mutationFn: migrateLegacyPositions,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["bots-v2"] });
      toast.success(data.message);
    },
    onError: () => toast.error("Migration failed — check console"),
  });

  const pauseAllMut = useMutation({
    mutationFn: pauseAllBots,
    onSuccess: () => {
      setAllPaused(true);
      qc.invalidateQueries({ queryKey: ["bots-v2"] });
      toast.success("All bots paused");
    },
    onError: () => toast.error("Failed to pause all bots"),
  });

  const resumeAllMut = useMutation({
    mutationFn: resumeAllBots,
    onSuccess: () => {
      setAllPaused(false);
      qc.invalidateQueries({ queryKey: ["bots-v2"] });
      toast.success("All bots resumed");
    },
    onError: () => toast.error("Failed to resume all bots"),
  });

  const activateAllMut = useMutation({
    mutationFn: activateAllBots,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["bots-v2"] });
      toast.success(res.activated > 0 ? `${res.activated} bot${res.activated > 1 ? "s" : ""} activated` : "All bots already active");
    },
    onError: () => toast.error("Failed to activate bots"),
  });

  // Auto-activate: whenever any bot has no active allocation, call activate-all.
  // Uses isSuccess to prevent repeat calls within the same page session.
  useEffect(() => {
    if (!data?.bots || isLoading || activateAllMut.isPending || activateAllMut.isSuccess) return;
    const anyDisabled = data.bots.some(
      (b: BotListItem) => !b.allocation?.enabled && b.allocation?.paused_reason !== "coming_soon"
    );
    if (anyDisabled) {
      activateAllMut.mutate();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.bots, isLoading]);

  // Aha moment: one-time toast after bots load
  useEffect(() => {
    if (!data?.bots || isLoading) return;
    if (localStorage.getItem("bmg_aha_shown")) return;
    const timer = setTimeout(() => {
      toast("Stock Swing just analyzed 847 signals. We're watching META, NVDA, MSFT for you.");
      localStorage.setItem("bmg_aha_shown", "true");
    }, 1500);
    return () => clearTimeout(timer);
  }, [data, isLoading]);

  // Build the ordered bot list — fall back to hardcoded if anything goes wrong
  let bots: BotListItem[] = [];
  if (isLoading) {
    bots = [];
  } else if (isError || !data?.bots || !Array.isArray(data.bots) || data.bots.length === 0) {
    bots = makeFallbackBots();
  } else {
    try {
      const byName = new Map(
        data.bots
          .filter((b): b is BotListItem => !!b?.profile?.name)
          .map((b) => [b.profile.name, b])
      );
      bots = BOT_ORDER.map(
        (name) => byName.get(name) ?? makeFallbackBots().find((b) => b.profile.name === name)!
      ).filter((item): item is BotListItem => !!item?.profile?.name);
    } catch {
      bots = makeFallbackBots();
    }
  }

  const isPauseOrResumePending = pauseAllMut.isPending || resumeAllMut.isPending;

  const { data: scoutSetupsData } = useQuery({
    queryKey: ["scout-setups"],
    queryFn: getSetups,
    staleTime: 60_000,
    retry: 0,
  });
  const activeScoutCount = (scoutSetupsData?.setups ?? []).filter((s) => s.status === "active").length;

  const { data: forgeBotsData } = useQuery({
    queryKey: ["forge-bots"],
    queryFn: getForgeBots,
    staleTime: 60_000,
    retry: 0,
  });
  const activeForgeCount = (forgeBotsData?.bots ?? []).filter((b) => b.status === "active").length;

  const { data: scoutSignalsData } = useQuery({
    queryKey: ["scout-signals"],
    queryFn: getScoutSignals,
    staleTime: 30_000,
    retry: 0,
    refetchInterval: 60_000,
  });
  const { data: forgeSignalsData } = useQuery({
    queryKey: ["forge-signals"],
    queryFn: getForgeSignals,
    staleTime: 30_000,
    retry: 0,
    refetchInterval: 60_000,
  });

  type CombinedSignal = (ScoutSignal & { source: "scout" }) | (ForgeSignal & { source: "forge" });
  const mySignals: CombinedSignal[] = [
    ...(scoutSignalsData?.signals ?? []).map((s) => ({ ...s, source: "scout" as const })),
    ...(forgeSignalsData?.signals ?? []).map((s) => ({ ...s, source: "forge" as const })),
  ]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 15);

  return (
    <>
      {/* Outer layout: content area + optional right rail */}
      <div className={cn("flex gap-6 max-w-7xl mx-auto px-4 py-6 pb-20 md:pb-6 animate-page-in")}>
        {/* Main content */}
        <div className="flex-1 min-w-0 space-y-6">
          {/* Title row */}
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-2xl font-bold text-t-hi font-ui-t">Strategy Lab</h1>
              <p className="text-t-dim text-sm mt-1 font-ui-t">
                Four independent portfolios — Stocks, Crypto, Options, and Quant — each running dedicated bots on real market data.
              </p>
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              {/* Strategy Library link */}
              <Link
                to="/strategy/library"
                className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-t-cyan/15 border border-t-cyan/30 text-t-cyan hover:bg-t-cyan/25 transition-colors whitespace-nowrap font-ui-t"
              >
                Strategy Library →
              </Link>
              {/* Portfolio View link */}
              <Link
                to="/net-portfolio"
                className="text-xs text-t-cyan hover:text-t-cyan/80 underline underline-offset-2 transition-colors whitespace-nowrap font-ui-t"
              >
                Portfolio View →
              </Link>
              {/* Activity rail toggle (desktop) */}
              <button
                onClick={() => setRailOpen((v) => !v)}
                className="hidden md:inline-flex text-xs text-t-muted hover:text-t-hi border border-t-dim rounded-lg px-3 py-1.5 transition-colors whitespace-nowrap font-ui-t"
              >
                {railOpen ? "‹ Activity" : "Activity ›"}
              </button>
              {bots.some((b) => !b.allocation?.enabled) && (
                <button
                  onClick={() => activateAllMut.mutate()}
                  disabled={activateAllMut.isPending}
                  className="flex-shrink-0 px-5 py-2.5 rounded-xl bg-t-green text-black text-sm font-bold hover:bg-t-green/80 transition-colors disabled:opacity-50 shadow-lg shadow-t-green/20 font-ui-t"
                >
                  {activateAllMut.isPending ? "Activating…" : "Activate All 9 Bots"}
                </button>
              )}
              {!isViewer && (allPaused ? (
                <button
                  onClick={() => resumeAllMut.mutate()}
                  disabled={isPauseOrResumePending}
                  className="flex-shrink-0 px-5 py-2.5 rounded-xl bg-t-green text-black text-sm font-bold hover:bg-t-green/80 transition-colors disabled:opacity-50 shadow-lg shadow-t-green/20 font-ui-t"
                >
                  {resumeAllMut.isPending ? "Resuming…" : "Resume All Bots"}
                </button>
              ) : (
                <button
                  onClick={() => pauseAllMut.mutate()}
                  disabled={isPauseOrResumePending}
                  className="flex-shrink-0 px-5 py-2.5 rounded-xl bg-t-red text-t-hi text-sm font-bold hover:bg-t-red/80 transition-colors disabled:opacity-50 shadow-lg shadow-t-red/20 font-ui-t"
                >
                  {pauseAllMut.isPending ? "Pausing…" : "Pause All Bots"}
                </button>
              ))}
            </div>
          </div>

          {/* 1. Portfolio value header — canonical total from
              compute_strategy_lab_aggregate (matches Dashboard + Portfolio). */}
          {!portfoliosLoading && portfolios.length > 0 && (() => {
            // Prefer canonical aggregate; fall back to per-sleeve sum only if
            // the aggregate hasn't loaded yet (avoids a 0 flash on first paint).
            const aggregateUsd = (labAggregate?.total_value_cents ?? 0) / 100;
            const fallbackUsd = portfolios.reduce((s, p) => s + (p.current_value_cents || 0), 0) / 100;
            const totalUsd = aggregateUsd > 0 ? aggregateUsd : fallbackUsd;
            return (
              <div className="bg-t-bg0 border border-t-dim rounded-xl px-5 py-4 flex items-center justify-between gap-4">
                <div>
                  <p className="panel-header mb-1">// PORTFOLIO VALUE</p>
                  <p className="text-4xl font-bold text-t-hi tabular-nums font-mono-t">
                    ${totalUsd.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                  </p>
                  <p className="text-xs text-t-muted mt-1 font-ui-t">Canonical aggregate · updates every 60s</p>
                </div>
              </div>
            );
          })()}

          {/* 2. Capital pods (sleeve cards) */}
          {portfoliosLoading ? (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-28 rounded-2xl bg-t-bg0 border border-t-dim animate-pulse" />
              ))}
            </div>
          ) : portfolios.length > 0 ? (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {portfolios.map((port) => (
                <PortfolioTab key={port.id} portfolio={port} />
              ))}
            </div>
          ) : null}

          {/* 3. Bot Leaderboard */}
          <BotLeaderboardSection onNavigateBot={(name) => navigate(`/strategy/${name}`)} />

          {/* 4. Market Regime */}
          <div className="bg-t-bg0 border border-t-dim rounded-xl px-4 py-3">
            <p className="panel-header mb-2">// Market Regime</p>
            <RegimeBar regime={regime} isLoading={regimeLoading} />
          </div>

          {/* 5. Candidates in incubation */}
          <CandidatesSection />

          {/* 6. LAB MODULES quick-nav */}
          <div>
            <p className="panel-header mb-2">// LAB MODULES</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {([
                { to: "/strategy/scout",       label: "SCOUT",       badge: `${activeScoutCount} armed` },
                { to: "/strategy/forge",        label: "FORGE",       badge: `${activeForgeCount} active` },
                { to: "/strategy/performance",  label: "ANALYTICS",   badge: null },
                { to: "/strategy/leaderboard",  label: "LEADERBOARD", badge: null },
              ] as const).map(({ to, label, badge }) => (
                <Link
                  key={to}
                  to={to}
                  className="bg-t-bg1 border border-t-dim rounded-xl px-4 py-3 hover:border-t-mid hover:bg-t-bg2/40 transition-all duration-150 flex flex-col gap-1.5"
                >
                  <span className="font-mono-t text-[10px] uppercase tracking-widest text-t-gdim">// {label}</span>
                  {badge !== null && (
                    <span className="font-mono-t text-sm font-bold text-t-hi tabular-nums">{badge}</span>
                  )}
                </Link>
              ))}
            </div>
          </div>

          {/* 7. Prebuilt bot tiles */}
          {isLoading ? (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
                <div key={i} className="h-36 rounded-2xl bg-t-bg0 border border-t-dim animate-pulse" />
              ))}
            </div>
          ) : (
            <div className={cn(
              "grid gap-4",
              railOpen
                ? "grid-cols-1 sm:grid-cols-2"
                : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-4"
            )}>
              {bots.map((item) => (
                <BotCard
                  key={item.profile.name}
                  item={item}
                  onNavigate={(name) => navigate(`/strategy/${name}`)}
                  isViewer={isViewer}
                  tier={item.allocation?.id != null ? tierByAllocId[item.allocation.id] : undefined}
                />
              ))}
            </div>
          )}

          {/* My Signals feed — Scout + Forge combined */}
          {mySignals.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <p className="panel-header">// MY SIGNALS</p>
                <div className="flex gap-2">
                  <Link to="/strategy/scout" className="text-xs text-t-gdim hover:text-t-muted transition-colors font-ui-t">Scout →</Link>
                  <Link to="/strategy/forge" className="text-xs text-t-gdim hover:text-t-muted transition-colors font-ui-t">Forge →</Link>
                </div>
              </div>
              <div className="bg-t-bg0 border border-t-dim rounded-2xl overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-2 border-b border-t-dim">
                  <span className="text-[10px] font-semibold text-t-gdim uppercase w-12 font-ui-t">Source</span>
                  <span className="text-[10px] font-semibold text-t-gdim uppercase w-10 font-ui-t">Side</span>
                  <span className="text-[10px] font-semibold text-t-gdim uppercase w-20 font-ui-t">Ticker</span>
                  <span className="text-[10px] font-semibold text-t-gdim uppercase flex-1 font-ui-t">Strategy</span>
                  <span className="text-[10px] font-semibold text-t-gdim uppercase w-10 text-right font-ui-t">Conf</span>
                  <span className="text-[10px] font-semibold text-t-gdim uppercase w-14 text-right font-ui-t">When</span>
                </div>
                {mySignals.map((sig) => {
                  const isLong = sig.side === "buy" || sig.side === "long" || sig.side === "cover";
                  const isShort = sig.side === "sell" || sig.side === "short";
                  const diff = Date.now() - new Date(sig.created_at).getTime();
                  const mins = Math.floor(diff / 60_000);
                  const ago = mins < 1 ? "now" : mins < 60 ? `${mins}m` : `${Math.floor(mins / 60)}h`;
                  const displayName = sig.display_name;
                  return (
                    <div key={`${sig.source}-${sig.id}`} className="flex items-center gap-2 px-4 py-2.5 hover:bg-t-bg1/40 transition-colors border-b border-t-dim/50 last:border-0 card-hover">
                      <span className={cn(
                        "text-[10px] font-semibold px-1.5 py-0.5 rounded border w-12 text-center font-ui-t",
                        sig.source === "scout"
                          ? "bg-violet-500/10 border-violet-500/20 text-violet-400"
                          : "bg-t-amber/10 border-t-amber/20 text-t-amber"
                      )}>
                        {sig.source === "scout" ? "SCOUT" : "FORGE"}
                      </span>
                      <span className={cn(
                        "text-xs font-bold w-10 uppercase font-mono-t",
                        isLong ? "text-t-green" : isShort ? "text-t-red" : "text-t-muted"
                      )}>
                        {sig.side}
                      </span>
                      <span className="text-xs font-mono-t text-t-hi w-20 truncate">{sig.ticker}</span>
                      <span className="text-xs text-t-muted flex-1 truncate font-ui-t">{displayName}</span>
                      <span className="text-xs font-semibold text-t-hi w-10 text-right tabular-nums font-mono-t">
                        {Math.round(sig.confidence * 100)}%
                      </span>
                      <span className="text-xs text-t-gdim w-14 text-right font-mono-t">{ago}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 8. Capital Allocation + Open Positions detail (at bottom) */}
          <PortfolioHero onNavigateBot={(name) => navigate(`/strategy/${name}`)} />

          {/* 8b. Deployment summary — allocated / deployed / cash */}
          <DeploymentSummary />

          {/* Comparison table */}
          {!isLoading && bots.length > 0 && <ComparisonTable bots={bots} tierByAllocId={tierByAllocId} />}

          {/* AI Analyst highlights */}
          <AnalystHighlights />

          {/* Today's Questions */}
          <TodaysQuestions
            onAskCoPilot={(q) => openCoPilot(q)}
          />

          {/* Footer */}
          <div className="flex items-center justify-between mt-8">
            <p className="text-xs text-t-gdim font-ui-t">
              Paper trading. Not investment advice. Not a registered investment adviser.
            </p>
            <button
              onClick={() => migrateMut.mutate()}
              disabled={migrateMut.isPending}
              title="Import open positions and watchlist from the old Strategy Lab into Stock Swing & Crypto Swing"
              className="text-xs text-t-dim hover:text-t-mid2 underline underline-offset-2 transition-colors disabled:opacity-40 font-ui-t"
            >
              {migrateMut.isPending ? "Importing…" : "Import legacy positions →"}
            </button>
          </div>
        </div>

        {/* Right rail (desktop only) */}
        {railOpen && (
          <aside className="hidden md:flex flex-col w-72 flex-shrink-0 bg-t-bg0 border border-t-dim rounded-2xl p-4 self-start sticky top-20 max-h-[calc(100vh-6rem)] overflow-hidden">
            <ActivityRail onClose={() => setRailOpen(false)} />
          </aside>
        )}
      </div>

      {/* Mobile bottom nav */}
      <BottomNav
        onOpenActivity={() => setRailOpen(true)}
        onOpenCoPilot={() => openCoPilot()}
      />
    </>
  );
}

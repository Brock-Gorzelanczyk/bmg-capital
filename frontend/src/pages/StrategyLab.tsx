import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate, Link } from "react-router-dom";
import SymbolChartDrawer from "@/components/ui/SymbolChartDrawer";
import AllocationDonut from "@/components/ui/AllocationDonut";
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
import { getAnalystSummary, type AnalystSummaryItem } from "@/api/analyst";
import { cn } from "@/lib/utils";
import { useIsViewer } from "@/store/authStore";

// ─── Bot metadata ─────────────────────────────────────────────────────────────

const BOT_META: Record<
  string,
  { displayName: string; description: string; assetClass: "stock" | "crypto" | "quant" }
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
  crypto_onchain: {
    displayName: "Crypto Onchain",
    description: "On-chain flow analysis — large wallet movements, DEX volume anomalies, L2 bridge activity",
    assetClass: "crypto",
  },
  options_income: {
    displayName: "Options Income",
    description: "Wheel, covered calls, CSPs, iron condors — premium collection",
    assetClass: "stock",
  },
  options_directional: {
    displayName: "Options Directional",
    description: "Credit spreads, debit spreads, LEAPS — directional options plays",
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
  if (r === "low") return "bg-green-500/15 text-green-400 border-green-500/30";
  if (r === "mid") return "bg-yellow-500/15 text-yellow-400 border-yellow-500/30";
  if (r === "high") return "bg-orange-500/15 text-orange-400 border-orange-500/30";
  if (r === "panic") return "bg-red-500/15 text-red-400 border-red-500/30";
  return "bg-zinc-800 text-zinc-400 border-zinc-700";
}

function trendColor(regime: string): string {
  const r = regime.toLowerCase();
  if (r === "bull") return "bg-lime-500/15 text-lime-400 border-lime-500/30";
  if (r === "chop") return "bg-zinc-700/40 text-zinc-400 border-zinc-600";
  if (r === "bear") return "bg-red-500/15 text-red-400 border-red-500/30";
  return "bg-zinc-800 text-zinc-400 border-zinc-700";
}

function RegimePill({ dot, label, value, colorClass }: { dot: string; label: string; value: string; colorClass: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border", colorClass)}>
      <span className={cn("w-1.5 h-1.5 rounded-full", dot)} />
      <span className="text-zinc-500">{label}</span>
      <span>{value}</span>
    </span>
  );
}

function RegimeBar({ regime, isLoading }: { regime: RegimeData | undefined; isLoading: boolean }) {
  if (isLoading || !regime) {
    return (
      <div className="flex gap-2 items-center animate-pulse">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-7 w-24 bg-zinc-800 rounded-full" />
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
        dot={vix === "LOW" ? "bg-green-400" : vix === "PANIC" ? "bg-red-400" : vix === "HIGH" ? "bg-orange-400" : "bg-yellow-400"}
        label="VIX"
        value={vix}
        colorClass={vixColor(vix)}
      />
      <RegimePill
        dot={trend === "BULL" ? "bg-lime-400" : trend === "BEAR" ? "bg-red-400" : "bg-zinc-400"}
        label="Trend"
        value={trend}
        colorClass={trendColor(trend)}
      />
      <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border bg-zinc-800 border-zinc-700 text-zinc-300">
        <span className="w-1.5 h-1.5 rounded-full bg-orange-400" />
        <span className="text-zinc-500">BTC Dom</span>
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
      <div className="w-16 h-3.5 bg-zinc-800 rounded" />
      <div className="w-20 h-5 bg-zinc-800 rounded-full" />
      <div className="w-10 h-5 bg-zinc-800 rounded-full" />
      <div className="w-12 h-3 bg-zinc-800 rounded ml-auto" />
      <div className="w-16 h-3 bg-zinc-800 rounded" />
      <div className="w-16 h-3 bg-zinc-800 rounded" />
      <div className="w-20 h-3 bg-zinc-800 rounded" />
      <div className="w-10 h-3 bg-zinc-800 rounded" />
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
    <div className="pt-3 border-t border-zinc-800">
      {/* Header row */}
      <div className="flex items-center justify-between mb-1.5">
        <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wide">Open Positions</p>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortKey)}
          className="text-[10px] bg-zinc-900 border border-zinc-700 rounded px-1.5 py-0.5 text-zinc-400 cursor-pointer focus:outline-none"
        >
          {SORT_OPTS.map((o) => (
            <option key={o.key} value={o.key}>{o.label}</option>
          ))}
        </select>
      </div>

      {/* Summary line */}
      {!isLoading && (
        <p className="text-[11px] text-zinc-500 mb-2">
          {totalPos} position{totalPos !== 1 ? "s" : ""} · {distinctBots} bot{distinctBots !== 1 ? "s" : ""}
          {totalPos > 0 && (
            <> · Total unrealized:{" "}
              <span className={totalIsPos ? "text-lime-400" : "text-red-400"}>
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
                "text-[10px] px-2 py-0.5 rounded-full border transition-colors",
                filterClass === chip.key
                  ? "bg-lime-500/15 text-lime-400 border-lime-500/30"
                  : "text-zinc-500 border-zinc-700 hover:text-zinc-300 hover:border-zinc-600"
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
        <div className="grid gap-x-2 px-3 pb-1 text-[9px] font-semibold text-zinc-600 uppercase tracking-wide"
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
        <p className="text-zinc-600 text-xs py-4 text-center">
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
                className="grid gap-x-2 px-3 py-2 rounded-xl bg-zinc-800/40 hover:bg-zinc-800 border border-zinc-800/60 hover:border-zinc-700 transition-colors items-center"
                style={{ gridTemplateColumns: "5rem 1fr 2.5rem 4rem 4rem 4.5rem 5.5rem 3rem" }}
              >
                {/* Symbol */}
                <span className="text-xs font-bold text-white truncate">{pos.symbol}</span>

                {/* Bot pill */}
                <span
                  className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded-full w-fit truncate"
                  style={{ background: `${pos.bot_color}22`, color: pos.bot_color, border: `1px solid ${pos.bot_color}44` }}
                >
                  {pos.bot_display}
                </span>

                {/* Side pill */}
                <span className={cn(
                  "text-[9px] font-bold px-1.5 py-0.5 rounded-full w-fit",
                  pos.side === "buy"
                    ? "bg-lime-500/15 text-lime-400 border border-lime-500/30"
                    : "bg-red-500/15 text-red-400 border border-red-500/30"
                )}>
                  {pos.side.toUpperCase()}
                </span>

                {/* Qty */}
                <span className="text-[11px] text-zinc-400 text-right tabular-nums">
                  {fmtQty(pos.qty, pos.symbol)}
                </span>

                {/* Entry */}
                <span className="text-[11px] text-zinc-500 text-right tabular-nums">
                  {fmtPrice(pos.entry_price)}
                </span>

                {/* Current Value = qty × current_price */}
                <span className="text-[11px] text-white text-right tabular-nums flex items-center justify-end gap-0.5">
                  {pos.price_source === "stale" && (
                    <span title="Price last updated — live ticker temporarily unavailable" className="text-[9px] text-amber-400 cursor-help">⚠</span>
                  )}
                  ${(pos.current_value_usd ?? pos.current_price * pos.qty).toFixed(2)}
                </span>

                {/* Unrealized P&L — two stacked lines */}
                <div className="text-right">
                  <div className={cn(
                    "text-[11px] font-semibold tabular-nums leading-tight",
                    pos.unrealized_pnl_usd > 0 ? "text-[#22c55e]"
                    : pos.unrealized_pnl_usd < 0 ? "text-[#ef4444]"
                    : "text-zinc-500"
                  )}>
                    {pos.unrealized_pnl_usd > 0 ? "+" : pos.unrealized_pnl_usd < 0 ? "-" : ""}
                    ${Math.abs(pos.unrealized_pnl_usd).toFixed(2)}
                  </div>
                  <div className={cn(
                    "text-[9px] tabular-nums leading-tight",
                    pos.unrealized_pnl_pct > 0 ? "text-[#22c55e]/70"
                    : pos.unrealized_pnl_pct < 0 ? "text-[#ef4444]/70"
                    : "text-zinc-600"
                  )}>
                    {pos.unrealized_pnl_pct > 0 ? "+" : pos.unrealized_pnl_pct < 0 ? "-" : ""}
                    {Math.abs(pos.unrealized_pnl_pct).toFixed(2)}%
                  </div>
                </div>

                {/* Held */}
                <span className="text-[10px] text-zinc-600 text-right">
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
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 animate-pulse space-y-5">
      <div className="h-4 w-40 bg-zinc-800 rounded" />
      <div className="grid grid-cols-3 gap-6">
        {[0, 1, 2].map((i) => (
          <div key={i} className="space-y-2">
            <div className="h-8 w-32 bg-zinc-800 rounded" />
            <div className="h-3 w-24 bg-zinc-800 rounded" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-4 gap-4 pt-4 border-t border-zinc-800">
        {[0, 1, 2, 3].map((i) => <div key={i} className="h-8 bg-zinc-800 rounded" />)}
      </div>
      <div className="h-28 bg-zinc-800 rounded-xl" />
      <div className="space-y-2 pt-4 border-t border-zinc-800">
        {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="h-9 bg-zinc-800 rounded-xl" />)}
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
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
          Strategy Lab Portfolio
        </h2>
        <span className="text-[10px] text-zinc-700">Live · refreshes every 60 s</span>
      </div>

      {/* Primary metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        <div>
          <p className="text-3xl font-bold text-white tabular-nums">
            ${totalVal.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </p>
          <p className="text-xs text-zinc-500 mt-1">Total Portfolio Value</p>
          {yestVal > 0 && (
            <p className="text-[11px] text-zinc-600 mt-0.5">
              from ${yestVal.toLocaleString("en-US", { minimumFractionDigits: 2 })} yesterday
            </p>
          )}
        </div>
        <div>
          <p className={cn("text-3xl font-bold tabular-nums", todayPos ? "text-lime-400" : "text-red-400")}>
            {todayPos ? "+" : "−"}${Math.abs(todayPnl).toLocaleString("en-US", { minimumFractionDigits: 2 })}
          </p>
          <p className="text-xs text-zinc-500 mt-1">Today's P&L</p>
          <p className="text-[11px] text-zinc-600 mt-0.5">across {p?.leaderboard?.length ?? 6} bots</p>
        </div>
        <div>
          <p className={cn("text-3xl font-bold tabular-nums", ret30Pos ? "text-lime-400" : "text-red-400")}>
            {formatPct(ret30)}
          </p>
          <p className="text-xs text-zinc-500 mt-1">30d Return</p>
          {(p?.return_30d_value_cents ?? 0) !== 0 && (
            <p className="text-[11px] text-zinc-600 mt-0.5">
              {dollars(Math.abs(p!.return_30d_value_cents))} {ret30Pos ? "gain" : "loss"}
            </p>
          )}
        </div>
      </div>

      {/* Secondary metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 pt-3 border-t border-zinc-800">
        {[
          { label: "All-time Return", val: formatPct(retAll), color: retAll >= 0 ? "text-lime-400" : "text-red-400", onClick: undefined },
          { label: "Open Positions",  val: String(p?.total_open_positions ?? 0), color: "text-white", onClick: undefined },
          {
            label: "Watchlists", val: `${p?.total_watchlist_count ?? 0} names`, color: "text-lime-400",
            onClick: () => {
              setTimeout(() => tabSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
            },
          },
        ].map(({ label, val, color, onClick }) => (
          <div key={label} onClick={onClick} className={onClick ? "cursor-pointer group" : ""}>
            <p className="text-[11px] text-zinc-600">{label}</p>
            <p className={cn("text-sm font-semibold mt-0.5", color, onClick && "group-hover:underline underline-offset-2")}>{val}</p>
          </div>
        ))}
      </div>

      {/* Allocation donut */}
      {(portsData?.portfolios ?? []).length > 0 && (
        <div className="pt-3 border-t border-zinc-800">
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wide mb-3">Capital Allocation</p>
          <AllocationDonut
            totalCents={p?.total_value_cents ?? (portsData?.portfolios ?? []).reduce((s, port) => s + port.current_value_cents, 0)}
            slices={[
              ...(portsData?.portfolios ?? []).map((port) => ({ key: port.asset_class, value_cents: port.current_value_cents })),
            ]}
          />
        </div>
      )}

      {/* Open Positions — replaces equity curve until we have multi-day history */}
      <OpenPositionsPanel />

      {/* Leaderboard */}
      <div className="pt-3 border-t border-zinc-800">
        <p className="text-xs font-semibold text-zinc-400 mb-3">Bot Leaderboard — ranked by 30d return</p>
        <div className="space-y-1.5">
          {(p?.leaderboard ?? []).map((entry) => {
            const ret30 = entry.return_30d_pct ?? null;
            const ePos = (ret30 ?? 0) >= 0;
            const tPnl = entry.today_pnl_cents / 100;
            const tPos = tPnl >= 0;
            const isCrypto = entry.profile.includes("crypto");
            const isOptions = entry.profile.includes("options");
            return (
              <button
                key={entry.profile}
                onClick={() => onNavigateBot(entry.profile)}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-xl bg-zinc-800/50 hover:bg-zinc-800 border border-zinc-800/80 hover:border-zinc-700 transition-colors text-left"
              >
                <span className="text-[10px] font-bold text-zinc-600 w-4 flex-shrink-0">
                  #{entry.rank}
                </span>
                <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", isOptions ? "bg-purple-400" : isCrypto ? "bg-orange-400" : entry.profile.includes("quant") ? "bg-violet-400" : "bg-blue-400")} />
                <span className="flex-1 text-xs font-semibold text-white truncate">{entry.name}</span>
                <span className={cn("text-xs font-bold w-16 text-right", ret30 != null ? (ePos ? "text-lime-400" : "text-red-400") : "text-zinc-600")}>
                  {ret30 != null ? `${ret30 >= 0 ? "+" : ""}${ret30.toFixed(3)}%` : "—"}
                </span>
                <span className={cn("text-xs w-20 text-right", tPos ? "text-lime-400" : "text-red-400")}>
                  {tPos ? "+" : "−"}${Math.abs(tPnl).toFixed(2)} today
                </span>
                <span className="text-[10px] text-zinc-600 w-16 text-right flex-shrink-0">
                  {entry.watchlist_count > 0 ? `${entry.watchlist_count} names` : "—"}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Watchlist */}
      <div ref={tabSectionRef} className="pt-3 border-t border-zinc-800">
        <p className="text-xs font-semibold text-zinc-400 mb-3">
          Watchlist — {watchlistItems.length} name{watchlistItems.length !== 1 ? "s" : ""}
        </p>
        {watchlistItems.length === 0 ? (
          <p className="text-zinc-600 text-xs py-3 text-center">Watchlist rebuilds at 8:30am ET. Check back after market open.</p>
        ) : (
          <div className="space-y-1">
            {watchlistItems.map((item) => (
              <div
                key={item.symbol}
                onClick={() => setChartSymbol(item.symbol)}
                className="flex items-center gap-2 px-3 py-2 rounded-xl bg-zinc-800/50 border border-zinc-800/80 cursor-pointer hover:bg-zinc-700/50 hover:border-zinc-600 transition-colors"
              >
                <span className="text-xs font-bold text-white w-14 flex-shrink-0">{item.symbol}</span>
                <span className="text-[10px] text-zinc-500 flex-1">{item.bots_watching.map((b) => b.replace(/_/g, " ")).join(", ")}</span>
                <span className="text-[10px] text-zinc-500 w-16 text-right capitalize">{item.status}</span>
                <span className="text-[10px] text-zinc-500 w-14 text-right">score {item.score.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
    <SymbolChartDrawer symbol={chartSymbol} onClose={() => setChartSymbol(null)} />
    </>
  );
}

// ─── Portfolio panel ──────────────────────────────────────────────────────────

function PortfolioTab({ portfolio }: { portfolio: StrategyPortfolio }) {
  const navigate = useNavigate();
  const currentUsd = portfolio.current_value_cents / 100;
  const pnlUsd = portfolio.pnl_cents / 100;
  const isPositive = portfolio.pnl_pct >= 0;

  return (
    <button
      onClick={() => navigate(`/strategy/portfolio/${portfolio.asset_class}`)}
      className="flex-1 min-w-0 rounded-2xl border-2 border-zinc-800 bg-zinc-950 p-4 text-left transition-all duration-150 hover:border-zinc-600 hover:bg-zinc-900/60 group"
      style={{ "--accent": portfolio.color_hex } as React.CSSProperties}
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xl">{portfolio.emoji}</span>
        <span className="font-bold text-white text-sm group-hover:text-white">{portfolio.name}</span>
        <span className="ml-auto text-zinc-600 group-hover:text-zinc-400 text-xs">→</span>
      </div>
      <div className="text-lg font-bold text-white leading-tight">
        ${currentUsd.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
      </div>
      <div className={cn("text-xs font-medium mt-0.5", isPositive ? "text-lime-400" : "text-red-400")}>
        {isPositive ? "+" : ""}{pnlUsd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        {" "}({isPositive ? "+" : ""}{portfolio.pnl_pct.toFixed(2)}%)
      </div>
      <div className="text-[11px] text-zinc-600 mt-1">
        {portfolio.bots.length} bot{portfolio.bots.length !== 1 ? "s" : ""} · $100k each
      </div>
    </button>
  );
}

// ─── Skeleton card ────────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 animate-pulse">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="h-5 w-32 bg-zinc-800 rounded mb-2" />
          <div className="h-3 w-48 bg-zinc-800 rounded" />
        </div>
        <div className="h-6 w-6 bg-zinc-800 rounded-full" />
      </div>
      <div className="flex gap-2 mb-4">
        <div className="h-5 w-14 bg-zinc-800 rounded-full" />
        <div className="h-5 w-16 bg-zinc-800 rounded-full" />
        <div className="h-5 w-16 bg-zinc-800 rounded-full" />
      </div>
      <div className="grid grid-cols-2 gap-3 mb-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i}>
            <div className="h-3 w-20 bg-zinc-800 rounded mb-1" />
            <div className="h-5 w-14 bg-zinc-800 rounded" />
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <div className="h-8 flex-1 bg-zinc-800 rounded-lg" />
        <div className="h-8 flex-1 bg-zinc-800 rounded-lg" />
      </div>
    </div>
  );
}

// ─── Bot card ─────────────────────────────────────────────────────────────────

interface BotCardProps {
  item: BotListItem;
  onNavigate: (name: string) => void;
  isViewer?: boolean;
}

function BotCard({ item, onNavigate, isViewer }: BotCardProps) {
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
  const isOnWaitlist = allocation?.go_live_requested ?? false;

  const pnlPositive = (stats?.today_pnl ?? 0) >= 0;
  const returnPositive = (stats?.return_30d_pct ?? 0) >= 0;

  // Left border color by asset class
  const leftBorderClass = profile.name.includes("options")
    ? "border-l-4 border-l-purple-500/60"
    : assetClass === "quant"
      ? "border-l-4 border-l-violet-500/60"
      : assetClass === "crypto"
        ? "border-l-4 border-l-orange-500/60"
        : "border-l-4 border-l-blue-500/60";

  return (
    <div
      className={cn(
        "bg-zinc-900 border border-zinc-800 rounded-2xl p-5 cursor-pointer hover:border-zinc-600 transition-colors group",
        leftBorderClass
      )}
      onClick={() => onNavigate(profile.name)}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-white font-semibold text-base leading-snug">
            {meta?.displayName ?? displayName(profile.name)}
          </h3>
          <p className="text-zinc-500 text-xs mt-0.5 leading-relaxed">
            {meta?.description ?? profile.description}
          </p>
        </div>
        <span
          className={cn(
            "text-xs font-semibold px-2 py-0.5 rounded-full",
            isComingSoon
              ? "bg-purple-500/15 text-purple-400 border border-purple-500/30"
              : isEnabled
                ? "bg-lime-500/15 text-lime-400 border border-lime-500/30"
                : "bg-zinc-800 text-zinc-500 border border-zinc-700"
          )}
        >
          {isComingSoon ? "COMING SOON" : isEnabled ? "ACTIVE" : "DISABLED"}
        </span>
      </div>

      {/* Badges */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        <span
          className={cn(
            "text-xs font-semibold px-2 py-0.5 rounded-full",
            assetClass === "stock"
              ? "bg-blue-500/15 text-blue-400 border border-blue-500/30"
              : assetClass === "quant"
                ? "bg-violet-500/15 text-violet-400 border border-violet-500/30"
                : "bg-orange-500/15 text-orange-400 border border-orange-500/30"
          )}
        >
          {assetClass.toUpperCase()}
        </span>
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400 border border-zinc-700">
          {formatCadence(profile.cadence)}
        </span>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <p className="text-zinc-600 text-xs mb-0.5">Today P&L (paper)</p>
          <p
            className={cn(
              "text-sm font-semibold",
              pnlPositive ? "text-lime-400" : "text-red-400"
            )}
          >
            {formatPnl(stats?.today_pnl ?? 0)}
          </p>
        </div>
        <div>
          <p className="text-zinc-600 text-xs mb-0.5">30d Return</p>
          <p
            className={cn(
              "text-sm font-semibold",
              returnPositive ? "text-lime-400" : "text-red-400"
            )}
          >
            {formatPct(stats?.return_30d_pct ?? 0)}
          </p>
        </div>
        <div>
          <p className="text-zinc-600 text-xs mb-0.5">Open Positions</p>
          <p className="text-sm font-semibold text-white">
            {stats?.open_positions ?? 0}
          </p>
        </div>
        <div>
          <p className="text-zinc-600 text-xs mb-0.5">Capital Allocated</p>
          <p className="text-sm font-semibold text-white">
            {allocation ? `${allocation.capital_pct}%` : "—"}
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
                "flex-1 text-xs font-semibold py-2 rounded-lg border transition-colors",
                isEnabled
                  ? "bg-zinc-800 border-zinc-700 text-zinc-300 hover:border-red-700 hover:text-red-400"
                  : "bg-lime-500/10 border-lime-500/30 text-lime-400 hover:bg-lime-500/20"
              )}
            >
              {allocateMut.isPending ? "…" : isEnabled ? "Disable" : "Enable"}
            </button>
            {isEnabled && (
              <button
                onClick={() => runNowMut.mutate()}
                disabled={runNowMut.isPending}
                className="text-xs font-semibold py-2 px-3 rounded-lg border border-blue-500/30 bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 transition-colors disabled:opacity-50"
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
            "flex-1 text-xs font-semibold py-2 rounded-lg border transition-colors",
            isOnWaitlist
              ? "bg-amber-500/10 border-amber-500/30 text-amber-400 hover:bg-amber-500/20"
              : "bg-zinc-800 border-zinc-700 text-zinc-400 hover:border-amber-600 hover:text-amber-400"
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

function ComparisonTable({ bots }: { bots: BotListItem[] }) {
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
        className="text-left pb-2 font-medium cursor-pointer select-none hover:text-zinc-300 transition-colors"
        onClick={() => handleSort(colKey)}
      >
        <span className="flex items-center gap-1">
          {label}
          <span className="text-zinc-600">
            {active ? (sortDir === "asc" ? "↑" : "↓") : "↕"}
          </span>
        </span>
      </th>
    );
  }

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
      <h2 className="text-sm font-semibold text-zinc-300 mb-4">Side-by-Side Comparison</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-zinc-600 border-b border-zinc-800">
              <SortHeader label="Bot" colKey="name" />
              <SortHeader label="Status" colKey="status" />
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
                <tr key={item.profile.name} className="border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/20 transition-colors">
                  <td className="py-2.5">
                    <div className="flex items-center gap-2">
                      <span className={cn("w-2 h-2 rounded-full flex-shrink-0", item.profile.name.includes("options") ? "bg-purple-400" : assetClass === "quant" ? "bg-violet-400" : assetClass === "crypto" ? "bg-orange-400" : "bg-blue-400")} />
                      <span className="font-semibold text-white text-xs">{displayName(item.profile.name)}</span>
                    </div>
                  </td>
                  <td className="py-2.5">
                    <span className={cn(
                      "text-xs font-bold px-1.5 py-0.5 rounded-full border",
                      isEnabled
                        ? "bg-lime-500/15 text-lime-400 border-lime-500/30"
                        : "bg-zinc-800 text-zinc-500 border-zinc-700"
                    )}>
                      {isEnabled ? "ACTIVE" : "OFF"}
                    </span>
                  </td>
                  <td className={cn("py-2.5 font-semibold text-xs", ret30 >= 0 ? "text-lime-400" : "text-red-400")}>
                    {formatPct(ret30)}
                  </td>
                  <td className="py-2.5 text-xs text-red-400">
                    {maxDd != null ? `-${maxDd}%` : "—"}
                  </td>
                  <td className="py-2.5 text-xs text-zinc-300">
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
        <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wide">
          Activity
        </span>
        <button
          onClick={onClose}
          className="text-zinc-600 hover:text-white text-xs transition-colors"
        >
          ‹ Hide
        </button>
      </div>
      {isLoading ? (
        <div className="space-y-2 animate-pulse">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="h-10 bg-zinc-800 rounded-lg" />
          ))}
        </div>
      ) : feed.length === 0 ? (
        <p className="text-zinc-600 text-xs text-center py-6">No activity yet. The execution engine runs daily at 10 AM ET on weekdays.</p>
      ) : (
        <div className="space-y-1 overflow-y-auto flex-1">
          {feed.slice(0, 20).map((item: AutopilotAction) => (
            <div
              key={item.id}
              className="bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2 text-xs"
            >
              <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                <span className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-400 font-medium text-xs">
                  {item.category?.replace(/_/g, " ")}
                </span>
                {item.asset && (
                  <span className="font-semibold text-white">{item.asset}</span>
                )}
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-zinc-500 truncate">
                  {item.action_type?.replace(/_/g, " ")}
                </span>
                <span className="text-zinc-700 whitespace-nowrap flex-shrink-0">
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
        <h2 className="text-sm font-semibold text-zinc-300">
          Today's questions for you
          {visible.length > 0 && (
            <span className="ml-2 text-xs font-bold px-1.5 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-400">
              {visible.length}
            </span>
          )}
        </h2>
      </div>

      {visible.length === 0 ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-6 text-center">
          <p className="text-zinc-500 text-sm">No questions today ✓</p>
          <p className="text-zinc-600 text-xs mt-1">All borderline signals have been reviewed.</p>
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
                className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3"
              >
                <p className="text-sm text-zinc-300 mb-2">
                  <span className="font-semibold text-white">{display}</span> considered{" "}
                  {r.side === "buy" ? "buying" : "selling"}{" "}
                  <span className="font-semibold text-white">{r.symbol}</span> at {timeStr} —{" "}
                  confidence{" "}
                  <span className="text-amber-400 font-semibold">{confPct}%</span>. Review?
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => dismiss(r.id)}
                    className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-300 hover:text-white transition-colors"
                  >
                    Looks good
                  </button>
                  <button
                    onClick={() => {
                      dismiss(r.id);
                      onAskCoPilot(coPilotQ);
                    }}
                    className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-teal-500/30 bg-teal-500/10 text-teal-300 hover:bg-teal-500/20 transition-colors"
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
  if (score == null) return <span className="text-zinc-600 text-xs">—</span>;
  const filled = Math.round(score);
  return (
    <span className={score >= 4 ? "text-lime-400" : score >= 3 ? "text-yellow-400" : "text-zinc-500"}>
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
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 animate-pulse">
        <div className="h-4 w-40 bg-zinc-800 rounded mb-4" />
        <div className="grid grid-cols-3 gap-3">
          {[0, 1, 2].map(i => <div key={i} className="h-16 bg-zinc-800 rounded-xl" />)}
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
      <Link to="/strategy/analyst" className="block bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-3 hover:border-zinc-600 transition-colors">
        <div className="flex items-center justify-between mb-1">
          <span className="font-semibold text-white text-sm">{item.symbol}</span>
          {flag
            ? <span className="text-xs text-red-400 font-semibold">⚑ Flagged</span>
            : <ConvictionStars score={item.conviction_score} />}
        </div>
        <p className="text-[11px] text-zinc-500 leading-tight line-clamp-2">{item.thesis_preview}</p>
        <p className="text-[10px] text-zinc-600 mt-1">{item.bot_name.replace(/_/g, " ")} · {item.suggested_hold}</p>
      </Link>
    );
  }

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-zinc-300">AI Analyst Highlights</h3>
        <Link to="/strategy/analyst" className="text-xs text-lime-400 hover:text-lime-300 underline underline-offset-2">
          Full report →
        </Link>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {picks.length > 0 && (
          <div>
            <p className="text-[11px] text-zinc-500 uppercase tracking-wide font-semibold mb-2">Top Picks</p>
            <div className="space-y-2">
              {picks.slice(0, 3).map(p => <SummaryCard key={p.id} item={p} />)}
            </div>
          </div>
        )}
        {concerns.length > 0 && (
          <div>
            <p className="text-[11px] text-zinc-500 uppercase tracking-wide font-semibold mb-2">Concerns</p>
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
    <nav className="fixed bottom-0 inset-x-0 bg-slate-900 border-t border-slate-700 md:hidden z-40">
      <div className="grid grid-cols-4 h-16">
        <button
          onClick={() => navigate("/strategy")}
          className="flex flex-col items-center justify-center gap-1 text-zinc-400 hover:text-white transition-colors"
        >
          <span className="text-lg">⊞</span>
          <span className="text-[10px] font-medium">Bots</span>
        </button>
        <button
          onClick={onOpenActivity}
          className="flex flex-col items-center justify-center gap-1 text-zinc-400 hover:text-white transition-colors"
        >
          <span className="text-lg">⚡</span>
          <span className="text-[10px] font-medium">Activity</span>
        </button>
        <button
          onClick={onOpenCoPilot}
          className="flex flex-col items-center justify-center gap-1 text-zinc-400 hover:text-white transition-colors"
        >
          <span className="text-lg">⌘</span>
          <span className="text-[10px] font-medium">Co-Pilot</span>
        </button>
        <button
          onClick={() => navigate("/settings")}
          className="flex flex-col items-center justify-center gap-1 text-zinc-400 hover:text-white transition-colors"
        >
          <span className="text-lg">⚙</span>
          <span className="text-[10px] font-medium">Settings</span>
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

  return (
    <>
      {/* Outer layout: content area + optional right rail */}
      <div className={cn("flex gap-6 max-w-7xl mx-auto px-4 py-6 pb-20 md:pb-6")}>
        {/* Main content */}
        <div className="flex-1 min-w-0 space-y-6">
          {/* Title row */}
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-2xl font-bold text-white">Strategy Lab</h1>
              <p className="text-zinc-500 text-sm mt-1">
                Four independent portfolios — Stocks, Crypto, Options, and Quant — each running dedicated bots on real market data.
              </p>
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              {/* Strategy Library link */}
              <Link
                to="/strategy/library"
                className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-teal-500/15 border border-teal-500/30 text-teal-400 hover:bg-teal-500/25 transition-colors whitespace-nowrap"
              >
                Strategy Library →
              </Link>
              {/* Portfolio View link */}
              <Link
                to="/net-portfolio"
                className="text-xs text-teal-400 hover:text-teal-300 underline underline-offset-2 transition-colors whitespace-nowrap"
              >
                Portfolio View →
              </Link>
              {/* Activity rail toggle (desktop) */}
              <button
                onClick={() => setRailOpen((v) => !v)}
                className="hidden md:inline-flex text-xs text-zinc-400 hover:text-white border border-zinc-700 rounded-lg px-3 py-1.5 transition-colors whitespace-nowrap"
              >
                {railOpen ? "‹ Activity" : "Activity ›"}
              </button>
              {bots.some((b) => !b.allocation?.enabled) && (
                <button
                  onClick={() => activateAllMut.mutate()}
                  disabled={activateAllMut.isPending}
                  className="flex-shrink-0 px-5 py-2.5 rounded-xl bg-lime-500 text-black text-sm font-bold hover:bg-lime-400 transition-colors disabled:opacity-50 shadow-lg shadow-lime-500/20"
                >
                  {activateAllMut.isPending ? "Activating…" : "Activate All 9 Bots"}
                </button>
              )}
              {!isViewer && (allPaused ? (
                <button
                  onClick={() => resumeAllMut.mutate()}
                  disabled={isPauseOrResumePending}
                  className="flex-shrink-0 px-5 py-2.5 rounded-xl bg-lime-500 text-black text-sm font-bold hover:bg-lime-400 transition-colors disabled:opacity-50 shadow-lg shadow-lime-500/20"
                >
                  {resumeAllMut.isPending ? "Resuming…" : "Resume All Bots"}
                </button>
              ) : (
                <button
                  onClick={() => pauseAllMut.mutate()}
                  disabled={isPauseOrResumePending}
                  className="flex-shrink-0 px-5 py-2.5 rounded-xl bg-red-600 text-white text-sm font-bold hover:bg-red-500 transition-colors disabled:opacity-50 shadow-lg shadow-red-600/20"
                >
                  {pauseAllMut.isPending ? "Pausing…" : "Pause All Bots"}
                </button>
              ))}
            </div>
          </div>

          {/* Paper-only banner */}
          <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 flex items-center gap-3">
            <span className="text-amber-400 text-sm font-semibold">📄 Paper trading only.</span>
            <span className="text-amber-300 text-xs">
              Currently in beta — all trades are simulated. No real money is at risk.
            </span>
          </div>

          {/* Regime status bar */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3">
            <p className="text-xs font-semibold text-zinc-600 uppercase tracking-wide mb-2">Market Regime</p>
            <RegimeBar regime={regime} isLoading={regimeLoading} />
          </div>

          {/* Three portfolio tab cards / Bot cards — above the portfolio hero */}
          {portfoliosLoading || isLoading ? (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-28 rounded-2xl bg-zinc-900 border border-zinc-800 animate-pulse" />
              ))}
            </div>
          ) : portfolios.length > 0 ? (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {portfolios.map((port) => (
                <PortfolioTab key={port.id} portfolio={port} />
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
                />
              ))}
            </div>
          )}

          {/* Aggregate portfolio hero */}
          <PortfolioHero onNavigateBot={(name) => navigate(`/strategy/${name}`)} />

          {/* Comparison table */}
          {!isLoading && bots.length > 0 && <ComparisonTable bots={bots} />}

          {/* AI Analyst highlights */}
          <AnalystHighlights />

          {/* Today's Questions */}
          <TodaysQuestions
            onAskCoPilot={(q) => openCoPilot(q)}
          />

          {/* Footer */}
          <div className="flex items-center justify-between mt-8">
            <p className="text-xs text-zinc-600">
              Paper trading. Not investment advice. Not a registered investment adviser.
            </p>
            <button
              onClick={() => migrateMut.mutate()}
              disabled={migrateMut.isPending}
              title="Import open positions and watchlist from the old Strategy Lab into Stock Swing & Crypto Swing"
              className="text-xs text-zinc-500 hover:text-zinc-300 underline underline-offset-2 transition-colors disabled:opacity-40"
            >
              {migrateMut.isPending ? "Importing…" : "Import legacy positions →"}
            </button>
          </div>
        </div>

        {/* Right rail (desktop only) */}
        {railOpen && (
          <aside className="hidden md:flex flex-col w-72 flex-shrink-0 bg-zinc-950 border border-zinc-800 rounded-2xl p-4 self-start sticky top-20 max-h-[calc(100vh-6rem)] overflow-hidden">
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

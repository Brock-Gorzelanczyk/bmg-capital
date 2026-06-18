import { useState, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp, TrendingDown, Activity, RefreshCw, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import client from "@/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

interface TradeRow {
  id: number;
  bot: string;
  symbol: string;
  side: string;
  qty: number;
  fill_price: number;
  pnl_cents: number | null;
  pnl_usd: number | null;
  ts: string | null;
  // Options-specific fields (present when asset_class === 'options')
  asset_class?: string;
  contract_symbol?: string;
  option_type?: "call" | "put";
  strike_price?: number;
  expiration_date?: string;  // ISO date string e.g. "2024-07-19"
  contract_count?: number;
  premium_per_contract?: number;
}

interface SparkPoint {
  date: string;
  pnl_cents: number;
}

interface ActivityResponse {
  trades: TradeRow[];
  sparkline: SparkPoint[];
  summary: {
    total_trades: number;
    total_pnl_cents: number;
    winning_trades: number;
    losing_trades: number;
  };
  total_count: number;
  has_more: boolean;
}

// ── Display helpers ───────────────────────────────────────────────────────────

const BOT_LABELS: Record<string, string> = {
  stock_swing:                  "Stock Swing",
  stock_day:                    "Stock Day",
  stock_lt:                     "Stock Long-Term",
  crypto_swing:                 "Crypto Swing",
  crypto_day:                   "Crypto Day",
  crypto_lt:                    "Crypto Long-Term",
  crypto_onchain:               "Crypto Onchain",
  options_income:               "Options Income",
  options_directional:          "Options Directional",
  crypto_quant_aggressive:      "Quant Aggressive",
  crypto_quant_scalper:         "Quant Scalper",
  crypto_quant_mean_reversion:  "Quant Mean Rev",
};

const BOT_SLEEVE: Record<string, string> = {
  stock_swing: "stocks", stock_day: "stocks", stock_lt: "stocks",
  options_income: "options", options_directional: "options",
  crypto_swing: "crypto", crypto_day: "crypto", crypto_lt: "crypto", crypto_onchain: "crypto",
  crypto_quant_aggressive: "quant", crypto_quant_scalper: "quant", crypto_quant_mean_reversion: "quant",
};

const SLEEVE_DOT: Record<string, string> = {
  stocks:  "bg-blue-400",
  crypto:  "bg-teal-400",
  options: "bg-purple-400",
  quant:   "bg-violet-400",
  unknown: "bg-zinc-500",
};

function fmtUsd(cents: number) {
  const usd = Math.abs(cents) / 100;
  if (usd >= 1000) return `$${(usd / 1000).toFixed(1)}k`;
  return `$${usd.toFixed(2)}`;
}

function fmtPnl(cents: number | null) {
  if (cents == null) return { text: "—", cls: "text-zinc-500" };
  const pos = cents >= 0;
  return { text: `${pos ? "+" : "-"}${fmtUsd(cents)}`, cls: pos ? "text-emerald-400" : "text-red-400" };
}

function ago(ts: string) {
  const diff = Date.now() - new Date(ts).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function sideClass(side: string) {
  if (["buy", "long", "cover"].includes(side)) return "text-emerald-400";
  if (["sell", "short"].includes(side)) return "text-red-400";
  return "text-zinc-400";
}

// ── Options helpers ───────────────────────────────────────────────────────────

function isOptionsRow(t: TradeRow): boolean {
  return t.asset_class === "options" || !!t.contract_symbol;
}

/** Format "2024-07-19" → "Jul 19" */
function fmtExpiry(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00Z");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/** Format strike price as "$580" or "$580.50" */
function fmtStrike(strike: number | undefined): string {
  if (strike == null) return "—";
  return strike % 1 === 0 ? `$${strike.toFixed(0)}` : `$${strike.toFixed(2)}`;
}

// ── Sparkline ─────────────────────────────────────────────────────────────────

function PnlSparkline({ points }: { points: SparkPoint[] }) {
  if (points.length < 2) {
    return (
      <div className="flex items-center justify-center h-24 text-xs text-zinc-600 italic">
        Not enough data for chart yet
      </div>
    );
  }

  const vals = points.map((p) => p.pnl_cents);
  // Cumulative running sum
  const cumulative: number[] = [];
  let running = 0;
  for (const v of vals) {
    running += v;
    cumulative.push(running);
  }

  const min = Math.min(...cumulative);
  const max = Math.max(...cumulative);
  const range = max - min || 1;
  const W = 1000;
  const H = 100;
  const pad = 4;

  const pts = cumulative.map((v, i) => {
    const x = pad + (i / (cumulative.length - 1)) * (W - pad * 2);
    const y = H - pad - ((v - min) / range) * (H - pad * 2);
    return `${x},${y}`;
  });

  const pathD = `M${pts.join(" L")}`;
  const isUp = (cumulative[cumulative.length - 1] ?? 0) >= (cumulative[0] ?? 0);
  const color = isUp ? "#34d399" : "#f87171";
  const fillId = "sparkFill";

  const areaD = `M${pts[0]} L${pts.join(" L")} L${pts[pts.length - 1].split(",")[0]},${H} L${pts[0].split(",")[0]},${H} Z`;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="w-full h-24"
      aria-hidden
    >
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.18" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaD} fill={`url(#${fillId})`} />
      <path d={pathD} fill="none" stroke={color} strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// ── Stat pill ─────────────────────────────────────────────────────────────────

function Stat({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3">
      <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider mb-1">{label}</p>
      <p className={cn("text-xl font-bold font-mono tabular-nums", positive === undefined ? "text-white" : positive ? "text-emerald-400" : "text-red-400")}>
        {value}
      </p>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const PAGE_SIZE = 100;

export default function ActivityPage() {
  const [botFilter, setBotFilter]         = useState("all");
  const [sideFilter, setSideFilter]       = useState("all");
  const [assetFilter, setAssetFilter]     = useState("all");
  const [dateFrom, setDateFrom]           = useState("");
  const [dateTo, setDateTo]               = useState("");
  const [search, setSearch]               = useState("");

  // Accumulated trades from all loaded pages
  const [allTrades, setAllTrades]         = useState<TradeRow[]>([]);
  const [offset, setOffset]               = useState(0);
  const [totalCount, setTotalCount]       = useState<number | null>(null);
  const [hasMore, setHasMore]             = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  function buildUrl(off: number) {
    const p = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(off) });
    if (botFilter !== "all")  p.set("bot", botFilter);
    if (sideFilter !== "all") p.set("side", sideFilter);
    if (assetFilter !== "all") p.set("asset_class", assetFilter);
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo)   p.set("date_to", dateTo);
    return `/bots/activity?${p}`;
  }

  // Build a stable filter key so we know when filters change (and need to reset)
  const filterKey = `${botFilter}|${sideFilter}|${assetFilter}|${dateFrom}|${dateTo}`;

  const { data, isLoading, isError, refetch, isFetching } = useQuery<ActivityResponse>({
    queryKey: ["cross-bot-activity", filterKey],
    queryFn: async () => {
      const res = await client.get(buildUrl(0)).then((r) => r.data);
      // Reset accumulator when filters change
      setAllTrades(res.trades ?? []);
      setOffset(0);
      setTotalCount(res.total_count ?? null);
      setHasMore(res.has_more ?? false);
      return res;
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const loadMore = useCallback(async () => {
    if (isLoadingMore || !hasMore) return;
    setIsLoadingMore(true);
    try {
      const nextOffset = allTrades.length;
      const res: ActivityResponse = await client.get(buildUrl(nextOffset)).then((r) => r.data);
      setAllTrades((prev) => [...prev, ...(res.trades ?? [])]);
      setOffset(nextOffset);
      setTotalCount(res.total_count ?? null);
      setHasMore(res.has_more ?? false);
    } finally {
      setIsLoadingMore(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoadingMore, hasMore, allTrades.length, botFilter, sideFilter, assetFilter, dateFrom, dateTo]);

  const trades = allTrades;
  const sparkline = data?.sparkline ?? [];
  const summary = data?.summary ?? { total_trades: 0, total_pnl_cents: 0, winning_trades: 0, losing_trades: 0 };

  // Unique bots present in loaded data
  const allBots = useMemo(() => [...new Set(trades.map((t) => t.bot))].sort(), [trades]);

  const filtered = useMemo(() => {
    return trades.filter((t) => {
      if (botFilter !== "all" && t.bot !== botFilter) return false;
      if (sideFilter === "buy" && !["buy", "long", "cover"].includes(t.side)) return false;
      if (sideFilter === "sell" && !["sell", "short"].includes(t.side)) return false;
      const q = search.toLowerCase();
      if (q && !t.symbol.toLowerCase().includes(q) && !t.bot.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [trades, botFilter, sideFilter, search]);

  const winRate = summary.total_trades > 0
    ? Math.round(summary.winning_trades / summary.total_trades * 100)
    : null;

  const pnlPos = summary.total_pnl_cents >= 0;

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 pb-24 md:pb-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest mb-0.5">
            // ACTIVITY FEED
          </p>
          <h1 className="text-2xl font-bold text-white">Trade Activity</h1>
          <p className="text-zinc-500 text-sm mt-1">
            {totalCount != null
              ? `All trades across every bot — showing ${trades.length.toLocaleString()} of ${totalCount.toLocaleString()}`
              : "All closed trades across every bot."}
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className={cn(
            "flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-300 transition-colors mt-1",
            isFetching && "opacity-40 cursor-not-allowed",
          )}
        >
          <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {/* Summary stats */}
      {!isLoading && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat
            label="Total P&L"
            value={`${pnlPos ? "+" : "-"}${fmtUsd(summary.total_pnl_cents)}`}
            positive={pnlPos}
          />
          <Stat label="Total Trades" value={String(summary.total_trades)} />
          <Stat label="Win Rate" value={winRate != null ? `${winRate}%` : "—"} positive={winRate != null ? winRate >= 50 : undefined} />
          <Stat label="Losing Trades" value={String(summary.losing_trades)} positive={summary.losing_trades === 0 ? true : undefined} />
        </div>
      )}

      {/* Sparkline */}
      {!isLoading && sparkline.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <Activity size={14} className="text-zinc-500" />
            <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">30-Day Cumulative P&L</p>
          </div>
          <PnlSparkline points={sparkline} />
          <div className="flex justify-between text-[10px] text-zinc-600 font-mono mt-1">
            <span>{sparkline[0]?.date}</span>
            <span>{sparkline[sparkline.length - 1]?.date}</span>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        {/* Bot filter */}
        <select
          value={botFilter}
          onChange={(e) => setBotFilter(e.target.value)}
          className="text-xs bg-zinc-900 border border-zinc-700 text-zinc-300 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-zinc-500"
        >
          <option value="all">All bots</option>
          {allBots.map((b) => (
            <option key={b} value={b}>{BOT_LABELS[b] ?? b}</option>
          ))}
        </select>

        {/* Asset class filter */}
        <select
          value={assetFilter}
          onChange={(e) => setAssetFilter(e.target.value)}
          className="text-xs bg-zinc-900 border border-zinc-700 text-zinc-300 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-zinc-500"
        >
          <option value="all">All assets</option>
          <option value="stock">Stocks</option>
          <option value="crypto">Crypto</option>
          <option value="options">Options</option>
          <option value="quant">Quant</option>
        </select>

        {/* Side filter */}
        <div className="flex rounded-lg border border-zinc-700 overflow-hidden">
          {(["all", "buy", "sell"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSideFilter(s)}
              className={cn(
                "text-xs px-3 py-1.5 transition-colors",
                sideFilter === s
                  ? "bg-zinc-700 text-white"
                  : "bg-zinc-900 text-zinc-500 hover:text-zinc-300",
              )}
            >
              {s === "all" ? "All sides" : s === "buy" ? "Buy" : "Sell"}
            </button>
          ))}
        </div>

        {/* Date range */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-zinc-600">From</span>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="text-xs bg-zinc-900 border border-zinc-700 text-zinc-300 rounded-lg px-2 py-1.5 focus:outline-none focus:border-zinc-500"
          />
          <span className="text-xs text-zinc-600">To</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="text-xs bg-zinc-900 border border-zinc-700 text-zinc-300 rounded-lg px-2 py-1.5 focus:outline-none focus:border-zinc-500"
          />
          {(dateFrom || dateTo) && (
            <button
              onClick={() => { setDateFrom(""); setDateTo(""); }}
              className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors"
            >
              ✕
            </button>
          )}
        </div>

        {/* Symbol search */}
        <input
          type="text"
          placeholder="Search symbol or bot…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="text-xs bg-zinc-900 border border-zinc-700 text-zinc-300 rounded-lg px-3 py-1.5 w-44 focus:outline-none focus:border-zinc-500 placeholder:text-zinc-600"
        />

        <span className="text-xs text-zinc-600 ml-auto">
          {filtered.length} of {trades.length} loaded
          {totalCount != null && trades.length < totalCount && (
            <span className="text-zinc-700"> ({totalCount.toLocaleString()} total)</span>
          )}
        </span>
      </div>

      {/* Trade table */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
        {isLoading && (
          <div className="space-y-px">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-12 bg-zinc-800/50 animate-pulse" />
            ))}
          </div>
        )}

        {isError && (
          <p className="text-sm text-red-400 text-center py-10">Failed to load activity. Backend may be starting.</p>
        )}

        {!isLoading && !isError && filtered.length === 0 && (
          <div className="text-center py-16">
            <Activity size={32} className="mx-auto mb-3 text-zinc-700" />
            <p className="text-zinc-500 text-sm">No trades yet.</p>
            <p className="text-zinc-600 text-xs mt-1">Trades appear here once bots start executing.</p>
          </div>
        )}

        {!isLoading && !isError && filtered.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-500">
                  <th className="text-left px-4 py-2.5 font-semibold">Bot</th>
                  <th className="text-left px-3 py-2.5 font-semibold">Symbol</th>
                  <th className="text-left px-3 py-2.5 font-semibold">Side</th>
                  <th className="text-right px-3 py-2.5 font-semibold">Qty / Contracts</th>
                  <th className="text-right px-3 py-2.5 font-semibold">Fill / Premium</th>
                  <th className="text-right px-3 py-2.5 font-semibold">P&amp;L</th>
                  <th className="text-right px-4 py-2.5 font-semibold">When</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t) => {
                  const pnl = fmtPnl(t.pnl_cents);
                  const sleeve = BOT_SLEEVE[t.bot] ?? "unknown";
                  const isOptions = isOptionsRow(t);

                  return (
                    <tr
                      key={t.id}
                      className="border-b border-zinc-800/60 hover:bg-zinc-800/30 transition-colors last:border-0"
                    >
                      {/* Bot */}
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", SLEEVE_DOT[sleeve])} />
                          <span className="text-zinc-300">{BOT_LABELS[t.bot] ?? t.bot}</span>
                        </div>
                      </td>

                      {/* Symbol — options shows underlying + strike/expiry badges */}
                      <td className="px-3 py-2.5">
                        {isOptions ? (
                          <div className="flex flex-col gap-0.5">
                            <span className="text-white font-semibold">
                              {t.contract_symbol ?? t.symbol}
                            </span>
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {/* CALL / PUT badge */}
                              {t.option_type ? (
                                <span className={cn(
                                  "text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide",
                                  t.option_type === "call"
                                    ? "bg-emerald-900/60 text-emerald-300"
                                    : "bg-red-900/60 text-red-300",
                                )}>
                                  {t.option_type}
                                </span>
                              ) : null}
                              {/* Strike */}
                              {t.strike_price != null && (
                                <span className="text-zinc-400">{fmtStrike(t.strike_price)}</span>
                              )}
                              {/* Expiry */}
                              {t.expiration_date && (
                                <span className="text-zinc-500">{fmtExpiry(t.expiration_date)}</span>
                              )}
                            </div>
                          </div>
                        ) : (
                          <span className="text-white font-semibold">{t.symbol}</span>
                        )}
                      </td>

                      {/* Side */}
                      <td className={cn("px-3 py-2.5 font-semibold uppercase", sideClass(t.side))}>
                        {t.side}
                      </td>

                      {/* Qty / Contracts */}
                      <td className="px-3 py-2.5 text-right text-zinc-400">
                        {isOptions
                          ? <span>×{t.contract_count ?? t.qty} contracts</span>
                          : t.qty}
                      </td>

                      {/* Fill / Premium per contract */}
                      <td className="px-3 py-2.5 text-right text-zinc-400">
                        {isOptions
                          ? t.premium_per_contract != null
                            ? <span>${t.premium_per_contract.toFixed(2)}<span className="text-zinc-600">/ct</span></span>
                            : t.fill_price != null
                              ? <span>${t.fill_price.toFixed(2)}<span className="text-zinc-600">/ct</span></span>
                              : "—"
                          : t.fill_price != null
                            ? `$${t.fill_price.toFixed(2)}`
                            : "—"}
                      </td>

                      {/* P&L */}
                      <td className={cn("px-3 py-2.5 text-right font-semibold", pnl.cls)}>
                        {pnl.text}
                      </td>

                      {/* When */}
                      <td className="px-4 py-2.5 text-right text-zinc-600">
                        {t.ts ? ago(t.ts) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Load more */}
      {hasMore && !isError && (
        <div className="flex justify-center pb-2">
          <button
            onClick={loadMore}
            disabled={isLoadingMore}
            className={cn(
              "flex items-center gap-2 text-xs px-4 py-2 rounded-lg border border-zinc-700 text-zinc-400 hover:text-white hover:border-zinc-500 transition-colors",
              isLoadingMore && "opacity-40 cursor-not-allowed",
            )}
          >
            {isLoadingMore
              ? <RefreshCw size={12} className="animate-spin" />
              : <ChevronDown size={12} />}
            {isLoadingMore
              ? "Loading…"
              : `Load ${Math.min(PAGE_SIZE, (totalCount ?? 0) - trades.length).toLocaleString()} more`}
            {totalCount != null && (
              <span className="text-zinc-600">
                ({((totalCount ?? 0) - trades.length).toLocaleString()} remaining)
              </span>
            )}
          </button>
        </div>
      )}
    </div>
  );
}

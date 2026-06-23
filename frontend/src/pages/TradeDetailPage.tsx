import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, ExternalLink, TrendingUp, TrendingDown,
  Target, Shield, AlertTriangle, Zap,
} from "lucide-react";
import { getTradeDetail } from "@/api/bots";
import { getLatestPrices, fetchBars } from "@/api/bars";
import TradePriceChart from "@/components/chart/TradePriceChart";
import { cn } from "@/lib/utils";
import type { TradeDetail } from "@/api/bots";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function priceDecimals(n: number): number {
  const abs = Math.abs(n);
  if (abs >= 1000) return 2;
  if (abs >= 1) return 4;
  if (abs >= 0.01) return 5;
  if (abs >= 0.0001) return 6;
  return 8;
}

function fmt$(n: number | null | undefined, minDec = 2): string {
  if (n == null) return "—";
  const abs = Math.abs(n);
  const maxDec = priceDecimals(abs);
  const effectiveMin = Math.min(Math.max(minDec, 2), maxDec);
  return `$${abs.toLocaleString("en-US", { minimumFractionDigits: effectiveMin, maximumFractionDigits: maxDec })}`;
}

function groupDecimals(...prices: (number | null | undefined)[]): number {
  return Math.max(2, ...prices.filter((p): p is number => p != null).map(priceDecimals));
}

function fmtPct(price: number, entry: number): string {
  if (!entry) return "";
  const pct = ((price - entry) / entry) * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  });
}

function pnlColor(n: number | null | undefined) {
  if (n == null) return "text-zinc-400";
  return n >= 0 ? "text-emerald-400" : "text-red-400";
}

function formatNotional(qty: number | null | undefined, price: number | null | undefined): string {
  if (!qty || !price) return "";
  return `($${(qty * price).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })})`;
}

function calcDTE(expDate: string): number {
  const d = new Date(expDate + "T00:00:00Z");
  return Math.round((d.getTime() - Date.now()) / 86_400_000);
}

function fmtExpiry(expDate: string): string {
  const d = new Date(expDate + "T00:00:00Z");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

// ─── Shared components ────────────────────────────────────────────────────────

function MetaRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-zinc-800 last:border-0">
      <span className="text-xs text-zinc-500">{label}</span>
      <span className="text-sm text-white text-right">{value}</span>
    </div>
  );
}

// ─── Equity chart ─────────────────────────────────────────────────────────────

function ChartLegend({ entry, stop, takeProfit, exitPrice, livePrice, status }: {
  entry: number; stop: number | null; takeProfit: number | null;
  exitPrice: number | null; livePrice: number | null; status: "open" | "closed";
}) {
  const gd = groupDecimals(entry, stop, takeProfit, exitPrice, livePrice);
  const rows: { dot: string; label: string; price: number }[] = [
    { dot: "bg-blue-500", label: "Entry", price: entry },
  ];
  if (stop) rows.push({ dot: "bg-red-500", label: "Stop", price: stop });
  if (takeProfit) rows.push({ dot: "bg-green-500", label: "Target", price: takeProfit });
  if (status === "closed" && exitPrice) rows.push({ dot: "bg-amber-400", label: "Exit", price: exitPrice });
  // Always show current price when available — even on closed trades, so user
  // can see where the underlying is trading now relative to the closed position.
  if (livePrice != null) rows.push({ dot: "bg-cyan-400", label: "Current", price: livePrice });
  return (
    <div className="absolute top-3 right-3 bg-zinc-900/90 backdrop-blur-sm border border-zinc-700/60 rounded-xl px-3 py-2 text-[11px] space-y-1 z-10 pointer-events-none">
      {rows.map((r) => (
        <div key={r.label + r.price} className="flex items-center gap-2">
          <span className={cn("w-2 h-2 rounded-full flex-shrink-0", r.dot)} />
          <span className="text-zinc-400 w-12 flex-shrink-0">{r.label}</span>
          <span className="text-white font-mono tabular-nums">{fmt$(r.price, gd)}</span>
          {r.price !== entry && (
            <span className={cn("font-medium", r.price >= entry ? "text-emerald-400" : "text-red-400")}>
              {fmtPct(r.price, entry)}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function TradeChartSection({ symbol, entryPrice, entryTime, side, qty, stopLoss, takeProfit,
  exitPrice, exitTime, livePrice, status, label }: {
  symbol: string; entryPrice: number; entryTime: string | null;
  side: string; qty: number; stopLoss: number | null; takeProfit: number | null;
  exitPrice: number | null; exitTime: string | null; livePrice: number | null;
  status: "open" | "closed"; label?: string;
}) {
  const barsSymbol = symbol.replace("/", "-");
  const { data: barsData, isLoading } = useQuery({
    queryKey: ["trade-price-bars", barsSymbol],
    queryFn: () => fetchBars(barsSymbol, "1Day"),
    staleTime: 300_000,
  });
  const bars = barsData?.bars ?? [];
  const gd = groupDecimals(entryPrice, stopLoss, takeProfit, exitPrice, livePrice);
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center gap-2 flex-wrap">
        <p className="text-sm font-semibold text-white">{label ?? `${symbol} — Daily`}</p>
        <div className="flex items-center gap-2 ml-auto text-[11px] flex-wrap">
          <span className="flex items-center gap-1.5 text-blue-400">
            <span className="w-3 h-0.5 bg-blue-500 rounded inline-block" /> Entry {fmt$(entryPrice, gd)}
          </span>
          {livePrice != null && (
            <span className="flex items-center gap-1.5 text-cyan-400">
              <span className="w-3 h-0.5 bg-cyan-400 rounded inline-block opacity-70 [border-top:1px_dashed]" />
              NOW {fmt$(livePrice, gd)}{" "}
              <span className={livePrice >= entryPrice ? "text-emerald-400" : "text-red-400"}>
                ({fmtPct(livePrice, entryPrice)})
              </span>
            </span>
          )}
        </div>
      </div>
      <div className="relative h-72 sm:h-80">
        {isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center text-zinc-600 text-sm">Loading chart…</div>
        ) : bars.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center text-zinc-600 text-sm">No chart data</div>
        ) : (
          <>
            <TradePriceChart bars={bars} entryPrice={entryPrice} entryTime={entryTime}
              side={side} qty={qty} symbol={symbol} stopLoss={stopLoss} takeProfit={takeProfit}
              exitPrice={exitPrice} exitTime={exitTime} livePrice={livePrice} />
            <ChartLegend entry={entryPrice} stop={stopLoss} takeProfit={takeProfit}
              exitPrice={exitPrice} livePrice={livePrice} status={status} />
          </>
        )}
      </div>
    </div>
  );
}

// ─── Equity P&L hero ──────────────────────────────────────────────────────────

function PnlHero({ symbol, qty, entryPrice, status, realizedPnl, livePrice, groupDec,
  isOptions, contractCount, entryPremiumUsd, currentPremiumUsd }: {
  symbol: string; qty: number; entryPrice: number; status: "open" | "closed";
  realizedPnl: number | null; livePrice: number | null; groupDec?: number;
  isOptions?: boolean; contractCount?: number | null;
  entryPremiumUsd?: number | null; currentPremiumUsd?: number | null;
}) {
  const unrealizedPnl = status !== "open" ? null
    : isOptions
      ? (currentPremiumUsd != null && entryPremiumUsd != null
          ? (currentPremiumUsd - entryPremiumUsd) * (contractCount ?? 1) * 100 : null)
      : livePrice != null ? (livePrice - entryPrice) * qty : null;
  const displayPnl = status === "closed" ? realizedPnl : unrealizedPnl;
  const pnlLabel = status === "closed" ? "Realized P&L" : "Unrealized P&L";
  const positive = displayPnl != null && displayPnl >= 0;
  const costBasis = isOptions
    ? (entryPremiumUsd != null ? entryPremiumUsd * (contractCount ?? 1) * 100 : null)
    : entryPrice * qty;
  const pnlPct = (displayPnl != null && costBasis && costBasis > 0) ? (displayPnl / costBasis) * 100 : null;
  return (
    <div className={cn("rounded-2xl border p-6 flex flex-col sm:flex-row items-start sm:items-center gap-4",
      positive ? "bg-emerald-500/5 border-emerald-500/20"
        : displayPnl == null ? "bg-zinc-900 border-zinc-800" : "bg-red-500/5 border-red-500/20")}>
      <div className="flex-1">
        <p className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">{pnlLabel}</p>
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className={cn("text-4xl font-bold tabular-nums", pnlColor(displayPnl))}>
            {displayPnl != null ? `${displayPnl >= 0 ? "+" : ""}${fmt$(displayPnl).replace("$", "")}` : status === "open" ? "…" : "—"}
          </span>
          {pnlPct != null && (
            <span className={cn("text-lg font-semibold tabular-nums", pnlColor(displayPnl))}>
              ({pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%)
            </span>
          )}
        </div>
      </div>
      <div className="flex flex-col gap-1.5 text-right min-w-[80px]">
        <div>
          <p className="text-[10px] text-zinc-500 uppercase">Entry</p>
          <p className="text-sm font-semibold text-white">{fmt$(entryPrice, groupDec)}</p>
        </div>
        {status === "open" && livePrice != null && (
          <div>
            <p className="text-[10px] text-zinc-500 uppercase">Live</p>
            <p className="text-sm font-semibold text-white">{fmt$(livePrice, groupDec)}</p>
          </div>
        )}
        <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded-full self-end",
          status === "open" ? "bg-lime-500/15 text-lime-400" : "bg-zinc-700 text-zinc-400")}>
          {status.toUpperCase()}
        </span>
      </div>
    </div>
  );
}

// ─── OPTIONS LAYOUT COMPONENTS ────────────────────────────────────────────────

function OptionsContractHeader({ trade }: { trade: TradeDetail }) {
  const underlying = trade.underlying_symbol ?? trade.symbol;
  const isCall = trade.option_type === "call";
  const contracts = trade.contract_count ?? 1;
  const dte = trade.expiration_date ? calcDTE(trade.expiration_date) : null;
  const expired = dte != null && dte <= 0;

  const strikeStr = trade.strike_price != null
    ? `${trade.strike_price % 1 === 0 ? trade.strike_price.toFixed(0) : trade.strike_price.toFixed(2)}`
    : "?";
  const typeChar = isCall ? "C" : "P";
  const expiryStr = trade.expiration_date ? fmtExpiry(trade.expiration_date) : "";

  return (
    <div className="flex items-start gap-3">
      <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 text-sm font-bold",
        isCall ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400")}>
        {typeChar}
      </div>
      <div className="flex-1 min-w-0">
        <h1 className="text-xl font-bold text-white font-mono">
          {underlying} {strikeStr}{typeChar} {expiryStr}
        </h1>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wide",
            isCall ? "bg-emerald-900/60 text-emerald-300 border border-emerald-700/40"
                   : "bg-red-900/60 text-red-300 border border-red-700/40")}>
            {trade.option_type?.toUpperCase()}
          </span>
          <span className="text-xs text-zinc-400">
            {contracts} contract{contracts !== 1 ? "s" : ""} · ×100 multiplier
          </span>
          {dte != null && (
            <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded-full",
              expired ? "bg-zinc-800 text-zinc-500"
                : dte < 7 ? "bg-red-500/15 text-red-400"
                : dte < 21 ? "bg-amber-500/15 text-amber-400"
                : "bg-zinc-800 text-zinc-400")}>
              {expired ? "EXPIRED" : `${dte} DTE`}
            </span>
          )}
          <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded-full",
            trade.status === "open" ? "bg-lime-500/15 text-lime-400" : "bg-zinc-700 text-zinc-400")}>
            {trade.status.toUpperCase()}
          </span>
        </div>
      </div>
    </div>
  );
}

function OptionsMetricsGrid({ trade, spotPrice }: { trade: TradeDetail; spotPrice: number | null }) {
  const underlying = trade.underlying_symbol ?? trade.symbol;
  const dte = trade.expiration_date ? calcDTE(trade.expiration_date) : null;
  const contracts = trade.contract_count ?? 1;

  const metrics: { label: string; value: React.ReactNode }[] = [
    {
      label: "Strike",
      value: trade.strike_price != null
        ? <span className="font-mono">${trade.strike_price % 1 === 0 ? trade.strike_price.toFixed(0) : trade.strike_price.toFixed(2)}</span>
        : "—",
    },
    {
      label: "Expiry",
      value: trade.expiration_date
        ? (
          <span className={cn("font-mono", dte != null && dte < 7 ? "text-red-400" : "text-white")}>
            {trade.expiration_date}{dte != null ? ` (${dte > 0 ? `${dte} DTE` : "expired"})` : ""}
          </span>
        )
        : "—",
    },
    {
      label: "Underlying",
      value: (
        <a
          href={`/chart?symbol=${underlying}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-400 hover:text-blue-300 flex items-center gap-1"
        >
          {underlying} <ExternalLink size={11} />
        </a>
      ),
    },
    {
      label: "Spot Price",
      value: spotPrice != null
        ? <span className="font-mono">${spotPrice.toFixed(2)}</span>
        : <span className="text-zinc-600 text-xs">live…</span>,
    },
    { label: "Contracts", value: contracts },
    { label: "Multiplier", value: "100× (1 contract = 100 shares)" },
  ];

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4">
      <p className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest mb-3">Contract Details</p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {metrics.map((m) => (
          <div key={m.label} className="bg-zinc-800/50 rounded-xl p-3">
            <p className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">{m.label}</p>
            <div className="text-sm font-semibold text-white">{m.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function OptionsPremiumCard({ trade }: { trade: TradeDetail }) {
  const contracts = trade.contract_count ?? 1;
  const entryTotal = trade.entry_premium_usd != null ? trade.entry_premium_usd * contracts * 100 : null;
  const mid = trade.bid_usd != null && trade.ask_usd != null
    ? (trade.bid_usd + trade.ask_usd) / 2
    : trade.current_premium_usd ?? null;
  const spread = trade.bid_usd != null && trade.ask_usd != null
    ? trade.ask_usd - trade.bid_usd : null;
  const spreadPct = spread != null && mid != null && mid > 0
    ? (spread / mid) * 100 : null;
  const hasBidAsk = trade.bid_usd != null && trade.ask_usd != null;

  const pnlPerContract = mid != null && trade.entry_premium_usd != null
    ? mid - trade.entry_premium_usd : null;
  const totalPnl = pnlPerContract != null ? pnlPerContract * contracts * 100 : null;

  return (
    <div className="bg-zinc-900 border border-purple-500/20 rounded-2xl p-4">
      <p className="text-[10px] font-bold text-purple-400 uppercase tracking-widest mb-3">Premium</p>
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-zinc-800/50 rounded-xl p-3">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Entry Premium</p>
          <p className="text-sm font-semibold text-white font-mono">
            {trade.entry_premium_usd != null ? `$${trade.entry_premium_usd.toFixed(2)}/ct` : "—"}
          </p>
          {entryTotal != null && (
            <p className="text-xs text-zinc-500 mt-0.5">${entryTotal.toFixed(2)} total cost</p>
          )}
        </div>
        <div className="bg-zinc-800/50 rounded-xl p-3">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Current Mid</p>
          <p className={cn("text-sm font-semibold font-mono", mid != null ? "text-white" : "text-zinc-600")}>
            {mid != null ? `$${mid.toFixed(2)}/ct` : "live…"}
          </p>
          {totalPnl != null && (
            <p className={cn("text-xs mt-0.5 font-medium", pnlColor(totalPnl))}>
              {totalPnl >= 0 ? "+" : ""}${Math.abs(totalPnl).toFixed(2)} total
            </p>
          )}
        </div>
        {hasBidAsk && (
          <>
            <div className="bg-zinc-800/50 rounded-xl p-3">
              <p className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Bid / Ask</p>
              <p className="text-sm font-semibold text-white font-mono">
                ${trade.bid_usd!.toFixed(2)} / ${trade.ask_usd!.toFixed(2)}
              </p>
              {spread != null && (
                <p className="text-xs text-zinc-500 mt-0.5">
                  spread ${spread.toFixed(2)}{spreadPct != null ? ` (${spreadPct.toFixed(1)}%)` : ""}
                </p>
              )}
            </div>
          </>
        )}
        <div className="bg-zinc-800/50 rounded-xl p-3">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Max Loss</p>
          <p className="text-sm font-semibold text-red-400 font-mono">
            {entryTotal != null ? `-$${entryTotal.toFixed(2)}` : "—"}
          </p>
          <p className="text-xs text-zinc-500 mt-0.5">premium paid (long only)</p>
        </div>
      </div>
    </div>
  );
}

function OptionsGreeksCard({ trade }: { trade: TradeDetail }) {
  const hasGreeks = trade.delta != null || trade.theta != null || trade.vega != null;
  if (!hasGreeks && !trade.implied_volatility) return null;

  const greeks: { label: string; value: React.ReactNode; sub: string }[] = [];

  if (trade.delta != null) greeks.push({
    label: "Delta",
    value: <span className={trade.delta >= 0 ? "text-emerald-400" : "text-red-400"}>{trade.delta.toFixed(2)}</span>,
    sub: trade.option_type === "call" ? "0→1 (calls)" : "-1→0 (puts)",
  });
  if (trade.gamma != null) greeks.push({
    label: "Gamma",
    value: trade.gamma.toFixed(4),
    sub: "Δ per $1 move",
  });
  if (trade.theta != null) greeks.push({
    label: "Theta",
    value: <span className="text-red-400">${trade.theta.toFixed(2)}/day</span>,
    sub: "time decay",
  });
  if (trade.vega != null) greeks.push({
    label: "Vega",
    value: `$${trade.vega.toFixed(2)}/1% IV`,
    sub: "volatility sensitivity",
  });
  if (trade.implied_volatility != null) greeks.push({
    label: "IV",
    value: `${(trade.implied_volatility * 100).toFixed(1)}%`,
    sub: "implied volatility",
  });

  return (
    <div className="bg-zinc-900 border border-blue-500/20 rounded-2xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <p className="text-[10px] font-bold text-blue-400 uppercase tracking-widest">Greeks</p>
        <span className="text-[9px] text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded">Black-Scholes est.</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {greeks.map((g) => (
          <div key={g.label} className="bg-zinc-800/50 rounded-xl p-3">
            <p className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">{g.label}</p>
            <p className="text-sm font-semibold text-white font-mono">{g.value}</p>
            <p className="text-[10px] text-zinc-600 mt-0.5">{g.sub}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function OptionsBreakevenCard({ trade, spotPrice }: { trade: TradeDetail; spotPrice: number | null }) {
  if (!trade.strike_price || !trade.entry_premium_usd) return null;
  const isCall = trade.option_type === "call";
  const isPut = trade.option_type === "put";
  if (!isCall && !isPut) return null;

  const breakeven = isCall
    ? trade.strike_price + trade.entry_premium_usd
    : trade.strike_price - trade.entry_premium_usd;

  const distFromSpot = spotPrice != null ? spotPrice - breakeven : null;
  const distPct = spotPrice != null && breakeven > 0 ? ((spotPrice - breakeven) / breakeven) * 100 : null;
  const inTheMoney = distFromSpot != null
    ? (isCall ? distFromSpot > 0 : distFromSpot < 0) : null;

  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-2xl p-4">
      <p className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest mb-3">Breakeven</p>
      <div className="flex items-center gap-4 flex-wrap">
        <div>
          <p className="text-[10px] text-zinc-500 mb-1">
            {isCall ? "Strike + Premium" : "Strike − Premium"}
          </p>
          <p className="text-2xl font-bold text-white font-mono">${breakeven.toFixed(2)}</p>
          <p className="text-xs text-zinc-500 mt-0.5">
            {isCall
              ? `$${trade.strike_price.toFixed(2)} + $${trade.entry_premium_usd.toFixed(2)}`
              : `$${trade.strike_price.toFixed(2)} − $${trade.entry_premium_usd.toFixed(2)}`}
          </p>
        </div>
        {spotPrice != null && distPct != null && (
          <div className={cn("rounded-xl px-3 py-2 border",
            inTheMoney
              ? "bg-emerald-500/10 border-emerald-500/20"
              : "bg-red-500/10 border-red-500/20")}>
            <p className="text-[10px] text-zinc-500 mb-0.5">vs Spot ${spotPrice.toFixed(2)}</p>
            <p className={cn("text-sm font-bold font-mono", inTheMoney ? "text-emerald-400" : "text-red-400")}>
              {distPct >= 0 ? "+" : ""}{distPct.toFixed(2)}%
            </p>
            <p className="text-[10px] text-zinc-500">
              {inTheMoney ? "✓ profitable at expiry" : `needs ${Math.abs(distPct).toFixed(1)}% ${isCall ? "↑" : "↓"}`}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function OptionsUnrealizedPnl({ trade }: { trade: TradeDetail }) {
  const contracts = trade.contract_count ?? 1;
  const mid = trade.bid_usd != null && trade.ask_usd != null
    ? (trade.bid_usd + trade.ask_usd) / 2
    : trade.current_premium_usd ?? null;
  const pnl = mid != null && trade.entry_premium_usd != null
    ? (mid - trade.entry_premium_usd) * contracts * 100 : null;
  const entryTotal = trade.entry_premium_usd != null ? trade.entry_premium_usd * contracts * 100 : null;
  const pnlPct = pnl != null && entryTotal && entryTotal > 0 ? (pnl / entryTotal) * 100 : null;
  const positive = pnl != null && pnl >= 0;

  return (
    <div className={cn("rounded-2xl border p-5 flex items-start gap-4",
      pnl == null ? "bg-zinc-900 border-zinc-800"
        : positive ? "bg-emerald-500/5 border-emerald-500/20"
        : "bg-red-500/5 border-red-500/20")}>
      <div className="flex-1">
        <p className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">
          {trade.status === "closed" ? "Realized P&L" : "Unrealized P&L"}
        </p>
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className={cn("text-4xl font-bold tabular-nums font-mono", pnlColor(pnl))}>
            {trade.status === "closed"
              ? (trade.realized_pnl_usd != null ? `${trade.realized_pnl_usd >= 0 ? "+" : ""}$${Math.abs(trade.realized_pnl_usd).toFixed(2)}` : "—")
              : pnl != null ? `${pnl >= 0 ? "+" : ""}$${Math.abs(pnl).toFixed(2)}` : "…"}
          </span>
          {pnlPct != null && (
            <span className={cn("text-lg font-semibold tabular-nums", pnlColor(pnl))}>
              ({pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(1)}%)
            </span>
          )}
        </div>
        {entryTotal != null && (
          <p className="text-xs text-zinc-500 mt-1">cost basis ${entryTotal.toFixed(2)}</p>
        )}
      </div>
      <div className="text-right space-y-1">
        <div>
          <p className="text-[10px] text-zinc-500">Entry Premium</p>
          <p className="text-sm font-semibold text-white font-mono">
            {trade.entry_premium_usd != null ? `$${trade.entry_premium_usd.toFixed(2)}/ct` : "—"}
          </p>
        </div>
        {mid != null && (
          <div>
            <p className="text-[10px] text-zinc-500">Current Mid</p>
            <p className="text-sm font-semibold text-white font-mono">${mid.toFixed(2)}/ct</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Full options layout ──────────────────────────────────────────────────────

function OptionsTradeLayout({ trade, spotPrice, backTo }: {
  trade: TradeDetail; spotPrice: number | null; backTo: string;
}) {
  const underlying = trade.underlying_symbol ?? trade.symbol;
  const chartSymbol = underlying.replace("/", "-");
  const entryPriceForChart = trade.entry_premium_usd ?? trade.entry_price_usd;

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-5 pb-20">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-zinc-500">
        <Link to={backTo} className="flex items-center gap-1 hover:text-zinc-300 transition-colors">
          <ArrowLeft size={12} /> Back
        </Link>
        <span>/</span>
        {trade.bot_display_name && (
          <><Link to={backTo} className="hover:text-zinc-300">{trade.bot_display_name}</Link><span>/</span></>
        )}
        <span className="text-zinc-400 font-medium">{trade.underlying_symbol ?? trade.symbol} #{trade.trade_id}</span>
      </div>

      <OptionsContractHeader trade={trade} />
      {trade.discord_message_url && (
        <a href={trade.discord_message_url} target="_blank" rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 border border-indigo-500/20 bg-indigo-500/10 px-3 py-1.5 rounded-lg w-fit transition-colors">
          <ExternalLink size={12} /> Discord Signal
        </a>
      )}

      <OptionsUnrealizedPnl trade={trade} />
      <OptionsMetricsGrid trade={trade} spotPrice={spotPrice} />
      <OptionsPremiumCard trade={trade} />
      <OptionsBreakevenCard trade={trade} spotPrice={spotPrice} />
      <OptionsGreeksCard trade={trade} />

      {/* Underlying stock chart — contract premium history unavailable via standard API */}
      <TradeChartSection
        symbol={chartSymbol}
        entryPrice={spotPrice ?? entryPriceForChart}
        entryTime={trade.entry_time}
        side={trade.side}
        qty={trade.contract_count ?? trade.qty}
        stopLoss={null}
        takeProfit={null}
        exitPrice={trade.exit_price_usd}
        exitTime={trade.close_time}
        livePrice={spotPrice}
        status={trade.status}
        label={`Underlying: ${underlying} — Daily (no premium history available)`}
      />

      {/* Strategy signal */}
      {(trade.strategy || trade.reason || trade.confidence != null) && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-1">
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wide py-3 border-b border-zinc-800">Strategy Signal</p>
          {trade.strategy && <MetaRow label="Strategy" value={trade.strategy.replace(/_/g, " ")} />}
          {trade.confidence != null && (
            <MetaRow label="Confidence" value={
              <div className="flex items-center gap-2">
                <div className="w-24 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                  <div className="h-full bg-blue-500 rounded-full" style={{ width: `${Math.min(100, Math.round(trade.confidence * 100))}%` }} />
                </div>
                <span>{Math.round(trade.confidence * 100)}%</span>
              </div>
            } />
          )}
          {trade.reason && (
            <div className="py-3 border-t border-zinc-800">
              <p className="text-xs text-zinc-500 mb-1">Signal Reason</p>
              <p className="text-sm text-zinc-300 leading-relaxed">
                {(() => {
                  try { return JSON.stringify(JSON.parse(trade.reason!), null, 2); }
                  catch { return trade.reason; }
                })()}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function TradeDetailPage() {
  const { tradeId } = useParams<{ tradeId: string }>();
  const navigate = useNavigate();
  const id = parseInt(tradeId ?? "0", 10);

  const { data: trade, isLoading, isError, error } = useQuery({
    queryKey: ["bot-trade-detail", id],
    queryFn: () => getTradeDetail(id),
    enabled: id > 0,
    staleTime: 30_000,
    retry: 1,
  });

  const isRealOptions = !!(trade?.option_type) && !trade?.is_legacy_share;

  // Live spot price for the underlying (or the trade symbol for equity/crypto).
  // Fetch for BOTH open AND closed trades so users can always see where the
  // underlying is trading right now relative to the position. Closed trades
  // poll less aggressively (30s) since urgency is lower.
  const priceSymbol = trade
    ? isRealOptions
      ? (trade.underlying_symbol ?? trade.symbol).replace("/", "-")
      : trade.symbol.replace("/", "-")
    : "";
  const { data: prices } = useQuery({
    queryKey: ["latest-prices", priceSymbol],
    queryFn: () => getLatestPrices([priceSymbol]),
    refetchInterval: trade?.status === "open" ? 5_000 : 30_000,
    staleTime: 0,
    enabled: !!priceSymbol,
  });
  // Backend may key by normalized symbol (e.g. "BTC/USD" instead of "BTC-USD"),
  // so try both shapes before giving up.
  const livePrice: number | null =
    prices?.[priceSymbol] ??
    prices?.[trade?.symbol ?? ""] ??
    prices?.[priceSymbol.replace("-", "/")] ??
    null;

  // Prefer backend-returned spot_price (fetched with Greeks), fall back to live WebSocket price
  const spotPrice = isRealOptions ? (trade?.spot_price ?? livePrice) : livePrice;

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8 space-y-4 animate-pulse">
        <div className="h-5 w-40 bg-zinc-800 rounded" />
        <div className="h-32 bg-zinc-900 rounded-2xl" />
        <div className="h-80 bg-zinc-900 rounded-2xl" />
        <div className="h-48 bg-zinc-900 rounded-2xl" />
      </div>
    );
  }

  if (isError || !trade) {
    const status = (error as any)?.response?.status ?? (error as any)?.status;
    if (status === 410) {
      return (
        <div className="max-w-3xl mx-auto px-4 py-8">
          <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300 mb-6">
            <ArrowLeft size={12} /> Back
          </button>
          <div className="bg-zinc-900 border border-amber-500/30 rounded-2xl p-6 space-y-3">
            <div className="flex items-center gap-2">
              <AlertTriangle size={16} className="text-amber-400 flex-shrink-0" />
              <p className="text-amber-400 font-semibold text-sm">Trade Quarantined — Legacy Misrouted Order</p>
            </div>
            <p className="text-zinc-400 text-sm leading-relaxed">
              This was a pre-options-fix share order that the broker executed as a stock fill
              instead of an options contract. It has been quarantined and excluded from active P&amp;L.
            </p>
            <a
              href="/chart?symbol=AMD"
              className="inline-flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300"
            >
              View AMD stock chart <ExternalLink size={11} />
            </a>
            <p className="text-zinc-600 text-xs">The audit trail is preserved in the database.</p>
          </div>
        </div>
      );
    }
    return (
      <div className="max-w-3xl mx-auto px-4 py-8 text-center">
        <p className="text-zinc-500 text-sm mb-4">Trade not found.</p>
        <button onClick={() => navigate(-1)} className="text-xs text-blue-400 hover:text-blue-300">← Go back</button>
      </div>
    );
  }

  const backTo = trade.bot_profile ? `/strategy/${trade.bot_profile}` : "/strategy";

  // ── Real options trade: full options layout ──────────────────────────────────
  if (isRealOptions) {
    return <OptionsTradeLayout trade={trade} spotPrice={spotPrice} backTo={backTo} />;
  }

  // ── Legacy share or equity/crypto trade: original layout ─────────────────────
  const isCrypto = trade.symbol.includes("/");
  const isLegacyShare = !!trade.is_legacy_share;
  const chartSymbol = trade.symbol.replace("/", "-");
  const unitLabel = isCrypto ? trade.symbol.split("/")[0] : isLegacyShare ? "shares (legacy)" : "shares";
  const tradeDec = groupDecimals(trade.entry_price_usd, trade.stop_loss_usd, trade.take_profit_usd, trade.exit_price_usd, livePrice);

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-5 pb-20">
      {isLegacyShare && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 flex items-start gap-2">
          <AlertTriangle size={14} className="text-amber-400 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-amber-400 text-xs font-semibold">Legacy Position — Pre-Options Fix</p>
            <p className="text-zinc-500 text-xs mt-0.5 leading-relaxed">
              This trade was created before the options fix (commit 17aa7f3). It is a share position, not an options contract. P&L and quantity are shown in share terms.
            </p>
          </div>
        </div>
      )}

      <div className="flex items-center gap-2 text-xs text-zinc-500">
        <button onClick={() => navigate(-1)} className="flex items-center gap-1 hover:text-zinc-300 transition-colors">
          <ArrowLeft size={12} /> Back
        </button>
        <span>/</span>
        {trade.bot_display_name && (
          <><Link to={backTo} className="hover:text-zinc-300 transition-colors">{trade.bot_display_name}</Link><span>/</span></>
        )}
        <span className="text-zinc-400 font-medium">{trade.symbol} #{trade.trade_id}</span>
      </div>

      <div className="flex items-start gap-3">
        <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0",
          trade.side === "buy" ? "bg-lime-500/15" : "bg-orange-500/15")}>
          {trade.side === "buy"
            ? <TrendingUp size={18} className="text-lime-400" />
            : <TrendingDown size={18} className="text-orange-400" />}
        </div>
        <div>
          <h1 className="text-xl font-bold text-white">{trade.symbol}</h1>
          <p className="text-sm text-zinc-500">
            {trade.side?.toUpperCase()} · {trade.qty?.toFixed(isCrypto ? 6 : 4)} {unitLabel}{" "}
            <span className="text-zinc-600">{formatNotional(trade.qty, trade.entry_price_usd)}</span>
            {trade.bot_display_name && <span className="ml-2 text-zinc-600">via {trade.bot_display_name}</span>}
          </p>
        </div>
        {trade.discord_message_url && (
          <a href={trade.discord_message_url} target="_blank" rel="noopener noreferrer"
            className="ml-auto flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 border border-indigo-500/20 bg-indigo-500/10 px-3 py-1.5 rounded-lg transition-colors">
            <ExternalLink size={12} /> Discord Signal
          </a>
        )}
      </div>

      <PnlHero symbol={trade.symbol} qty={trade.qty} entryPrice={trade.entry_price_usd}
        status={trade.status} realizedPnl={trade.realized_pnl_usd} livePrice={livePrice}
        groupDec={tradeDec} />

      <TradeChartSection symbol={chartSymbol} entryPrice={trade.entry_price_usd}
        entryTime={trade.entry_time} side={trade.side} qty={trade.qty}
        stopLoss={trade.stop_loss_usd} takeProfit={trade.take_profit_usd}
        exitPrice={trade.exit_price_usd} exitTime={trade.close_time}
        livePrice={livePrice} status={trade.status} />

      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-1">
        <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wide py-3 border-b border-zinc-800">Trade Details</p>
        <MetaRow label="Entry Price" value={fmt$(trade.entry_price_usd, tradeDec)} />
        <MetaRow label="Entry Time" value={fmtDate(trade.entry_time)} />
        <MetaRow label="Quantity" value={
          <span>{trade.qty?.toFixed(isCrypto ? 6 : 4)} {unitLabel}{" "}
            <span className="text-zinc-500">{formatNotional(trade.qty, trade.entry_price_usd)}</span>
          </span>
        } />
        <MetaRow label="Status" value={
          <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded-full",
            trade.status === "open" ? "bg-lime-500/15 text-lime-400" : "bg-zinc-700 text-zinc-400")}>
            {trade.status.toUpperCase()}
          </span>
        } />
        {trade.stop_loss_usd != null && (
          <MetaRow label="Stop Loss" value={<span className="text-red-400 flex items-center gap-1"><Shield size={11} /> {fmt$(trade.stop_loss_usd, tradeDec)}</span>} />
        )}
        {trade.take_profit_usd != null && (
          <MetaRow label="Take Profit" value={<span className="text-emerald-400 flex items-center gap-1"><Target size={11} /> {fmt$(trade.take_profit_usd, tradeDec)}</span>} />
        )}
        {trade.exit_price_usd != null && (
          <MetaRow label="Exit Price" value={
            <span>{fmt$(trade.exit_price_usd, tradeDec)}{" "}
              {trade.qty && <span className="text-zinc-500">(${(trade.qty * trade.exit_price_usd).toFixed(2)})</span>}
            </span>
          } />
        )}
        {trade.close_time && <MetaRow label="Close Time" value={fmtDate(trade.close_time)} />}
        {trade.alpaca_order_id && (
          <MetaRow label="Order ID" value={<span className="text-zinc-400 font-mono text-[11px]">{trade.alpaca_order_id}</span>} />
        )}
      </div>

      {(trade.strategy || trade.reason || trade.confidence != null) && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-1">
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wide py-3 border-b border-zinc-800">Strategy Signal</p>
          {trade.strategy && <MetaRow label="Strategy" value={trade.strategy.replace(/_/g, " ")} />}
          {trade.confidence != null && (
            <MetaRow label="Confidence" value={
              <div className="flex items-center gap-2">
                <div className="w-24 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                  <div className="h-full bg-blue-500 rounded-full" style={{ width: `${Math.min(100, Math.round(trade.confidence * 100))}%` }} />
                </div>
                <span>{Math.round(trade.confidence * 100)}%</span>
              </div>
            } />
          )}
          {trade.reason && (
            <div className="py-3 border-t border-zinc-800">
              <p className="text-xs text-zinc-500 mb-1">Signal Reason</p>
              <p className="text-sm text-zinc-300 leading-relaxed">{trade.reason}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, TrendingUp, TrendingDown, Target, Shield } from "lucide-react";
import { getTradeDetail } from "@/api/bots";
import { getLatestPrices, fetchBars } from "@/api/bars";
import TradePriceChart from "@/components/chart/TradePriceChart";
import { cn } from "@/lib/utils";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function priceDecimals(n: number): number {
  const abs = Math.abs(n);
  if (abs >= 1000) return 2;
  if (abs >= 1) return 4;
  if (abs >= 0.01) return 5;
  if (abs >= 0.0001) return 6;
  return 8;
}

/** Format a price. Pass minDec to force a minimum number of decimal places
 *  (used to align entry/stop/target in the same group). */
function fmt$(n: number | null | undefined, minDec = 2): string {
  if (n == null) return "—";
  const abs = Math.abs(n);
  const maxDec = priceDecimals(abs);
  const effectiveMin = Math.min(Math.max(minDec, 2), maxDec);
  return `$${abs.toLocaleString("en-US", { minimumFractionDigits: effectiveMin, maximumFractionDigits: maxDec })}`;
}

/** Shared decimal precision for a group of related prices (entry/stop/target). */
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

// ─── Legend ───────────────────────────────────────────────────────────────────

function ChartLegend({ entry, stop, takeProfit, exitPrice, livePrice, status }: {
  entry: number;
  stop: number | null;
  takeProfit: number | null;
  exitPrice: number | null;
  livePrice: number | null;
  status: "open" | "closed";
}) {
  const nowPrice = status === "open" ? livePrice : exitPrice;
  const nowAbove = nowPrice != null && nowPrice >= entry;
  // All prices in this trade share the same precision floor
  const gd = groupDecimals(entry, stop, takeProfit, exitPrice, nowPrice);

  const rows: { dot: string; label: string; price: number; pctClass?: string }[] = [
    { dot: "bg-blue-500", label: "Entry", price: entry },
  ];
  if (stop) rows.push({ dot: "bg-red-500", label: "Stop", price: stop });
  if (takeProfit) rows.push({ dot: "bg-green-500", label: "Target", price: takeProfit });
  if (status === "closed" && exitPrice) {
    rows.push({ dot: "bg-amber-400", label: "Exit", price: exitPrice });
  }
  if (nowPrice != null) {
    rows.push({ dot: "bg-cyan-400", label: status === "open" ? "Now" : "", price: nowPrice });
  }

  return (
    <div className="absolute top-3 right-3 bg-zinc-900/90 backdrop-blur-sm border border-zinc-700/60 rounded-xl px-3 py-2 text-[11px] space-y-1 z-10 pointer-events-none">
      {rows.map((r) => (
        <div key={r.label + r.price} className="flex items-center gap-2">
          <span className={cn("w-2 h-2 rounded-full flex-shrink-0", r.dot)} />
          <span className="text-zinc-400 w-12 flex-shrink-0">{r.label}</span>
          <span className="text-white font-mono tabular-nums">{fmt$(r.price, gd)}</span>
          {r.price !== entry && (
            <span className={cn(
              "font-medium",
              r.price >= entry ? "text-emerald-400" : "text-red-400"
            )}>
              {fmtPct(r.price, entry)}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Chart section ────────────────────────────────────────────────────────────

function TradeChartSection({ symbol, entryPrice, entryTime, side, qty, stopLoss, takeProfit, exitPrice, exitTime, livePrice, status }: {
  symbol: string;
  entryPrice: number;
  entryTime: string | null;
  side: string;
  qty: number;
  stopLoss: number | null;
  takeProfit: number | null;
  exitPrice: number | null;
  exitTime: string | null;
  livePrice: number | null;
  status: "open" | "closed";
}) {
  // BTC/USD → BTC-USD so the slash doesn't break the URL path
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
      {/* Header */}
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center gap-2 flex-wrap">
        <p className="text-sm font-semibold text-white">{symbol} — Daily</p>
        <div className="flex items-center gap-2 ml-auto text-[11px] flex-wrap">
          <span className="flex items-center gap-1.5 text-blue-400">
            <span className="w-3 h-0.5 bg-blue-500 rounded inline-block" />
            Entry {fmt$(entryPrice, gd)}
          </span>
          {stopLoss && (
            <span className="flex items-center gap-1.5 text-red-400">
              <span className="w-3 h-0.5 bg-red-500 rounded inline-block border-t border-dashed border-red-500" />
              Stop {fmt$(stopLoss, gd)}
            </span>
          )}
          {takeProfit && (
            <span className="flex items-center gap-1.5 text-green-400">
              <span className="w-3 h-0.5 bg-green-500 rounded inline-block" />
              Target {fmt$(takeProfit, gd)}
            </span>
          )}
          {status === "open" && livePrice != null && (
            <span className="flex items-center gap-1.5 text-cyan-400">
              <span className="w-3 h-0.5 bg-cyan-400 rounded inline-block" style={{ borderTop: "2px dashed #06b6d4", background: "none", height: 0 }} />
              Now {fmt$(livePrice, gd)}{" "}
              <span className={livePrice >= entryPrice ? "text-emerald-400" : "text-red-400"}>
                ({fmtPct(livePrice, entryPrice)})
              </span>
            </span>
          )}
        </div>
      </div>

      {/* Chart */}
      <div className="relative h-72 sm:h-80">
        {isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-zinc-600 text-sm">Loading chart…</div>
          </div>
        ) : bars.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-zinc-600 text-sm">No chart data available</div>
          </div>
        ) : (
          <>
            <TradePriceChart
              bars={bars}
              entryPrice={entryPrice}
              entryTime={entryTime}
              side={side}
              qty={qty}
              symbol={symbol}
              stopLoss={stopLoss}
              takeProfit={takeProfit}
              exitPrice={exitPrice}
              exitTime={exitTime}
              livePrice={livePrice}
            />
            <ChartLegend
              entry={entryPrice}
              stop={stopLoss}
              takeProfit={takeProfit}
              exitPrice={exitPrice}
              livePrice={livePrice}
              status={status}
            />
          </>
        )}
      </div>
    </div>
  );
}

// ─── P&L Hero ─────────────────────────────────────────────────────────────────

function PnlHero({ symbol, qty, entryPrice, status, realizedPnl, livePrice, groupDec,
  isOptions, contractCount, entryPremiumUsd, currentPremiumUsd }: {
  symbol: string;
  qty: number;
  entryPrice: number;
  status: "open" | "closed";
  realizedPnl: number | null;
  livePrice: number | null;
  groupDec?: number;
  isOptions?: boolean;
  contractCount?: number | null;
  entryPremiumUsd?: number | null;
  currentPremiumUsd?: number | null;
}) {
  // Options P&L: (current_premium - entry_premium) × contracts × 100
  // Stock P&L:   (live_price - entry_price) × qty
  const unrealizedPnl = status !== "open" ? null
    : isOptions
      ? (currentPremiumUsd != null && entryPremiumUsd != null
          ? (currentPremiumUsd - entryPremiumUsd) * (contractCount ?? 1) * 100
          : null)
      : livePrice != null
        ? (livePrice - entryPrice) * qty
        : null;

  const displayPnl = status === "closed" ? realizedPnl : unrealizedPnl;
  const pnlLabel = status === "closed" ? "Realized P&L" : "Unrealized P&L";
  const positive = displayPnl != null && displayPnl >= 0;

  // P&L % — for options use premium as cost basis
  const costBasis = isOptions
    ? (entryPremiumUsd != null ? entryPremiumUsd * (contractCount ?? 1) * 100 : null)
    : entryPrice * qty;
  const pnlPct = (status === "open" && unrealizedPnl != null && costBasis && costBasis > 0)
    ? (unrealizedPnl / costBasis) * 100
    : (status === "closed" && realizedPnl != null && costBasis && costBasis > 0)
    ? (realizedPnl / costBasis) * 100
    : null;

  return (
    <div className={cn(
      "rounded-2xl border p-6 flex flex-col sm:flex-row items-start sm:items-center gap-4",
      positive ? "bg-emerald-500/5 border-emerald-500/20"
        : displayPnl == null ? "bg-zinc-900 border-zinc-800"
        : "bg-red-500/5 border-red-500/20"
    )}>
      <div className="flex-1">
        <p className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">{pnlLabel}</p>
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className={cn("text-4xl font-bold tabular-nums", pnlColor(displayPnl))}>
            {displayPnl != null
              ? `${displayPnl >= 0 ? "+" : ""}${fmt$(displayPnl).replace("$", "")}`
              : status === "open" ? "…" : "—"}
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
        {status === "open" && (
          <div>
            <p className="text-[10px] text-zinc-500 uppercase">Live</p>
            <p className={cn("text-sm font-semibold", livePrice != null ? "text-white" : "text-zinc-600")}>
              {livePrice != null ? fmt$(livePrice, groupDec) : "…"}
            </p>
          </div>
        )}
        <span className={cn(
          "text-[10px] font-bold px-2 py-0.5 rounded-full self-end",
          status === "open" ? "bg-lime-500/15 text-lime-400" : "bg-zinc-700 text-zinc-400"
        )}>
          {status.toUpperCase()}
        </span>
      </div>
    </div>
  );
}

// ─── Metadata row ─────────────────────────────────────────────────────────────

function MetaRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-zinc-800 last:border-0">
      <span className="text-xs text-zinc-500">{label}</span>
      <span className="text-sm text-white text-right">{value}</span>
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

  // Live price: for options use the underlying ticker; for others use the trade symbol
  const priceSymbol = trade
    ? (trade.option_type
        ? (trade.underlying_symbol ?? trade.symbol).replace("/", "-")
        : trade.symbol.replace("/", "-"))
    : "";
  const { data: prices } = useQuery({
    queryKey: ["latest-prices", priceSymbol],
    queryFn: () => getLatestPrices([priceSymbol]),
    refetchInterval: 5_000,
    staleTime: 0,
    enabled: !!priceSymbol && trade?.status === "open",
  });
  // Backend normalizes LINK-USD → LINK/USD in its response keys, so check both.
  const livePrice = (trade?.status === "open"
    ? (prices?.[priceSymbol] ?? prices?.[trade?.symbol ?? ""] ?? null)
    : null);

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
    // Check if this is a 410 Gone (quarantined trade)
    const status = (error as any)?.response?.status ?? (error as any)?.status;
    if (status === 410) {
      return (
        <div className="max-w-3xl mx-auto px-4 py-8">
          <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300 mb-6">
            <ArrowLeft size={12} /> Back
          </button>
          <div className="bg-zinc-900 border border-amber-500/30 rounded-2xl p-6 text-center space-y-2">
            <p className="text-amber-400 font-semibold text-sm">Trade Quarantined</p>
            <p className="text-zinc-500 text-xs leading-relaxed">
              This trade was created before the options fix (pre-17aa7f3) and has been
              quarantined. It was a share position mislabeled as an options contract
              and has been excluded from P&amp;L and all activity feeds.
            </p>
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

  const isCrypto = trade.symbol.includes("/");
  // Use the option_type field from DB — not bot profile name — to detect real options positions
  const isOptions = !!trade.option_type;
  const isLegacyShare = !!trade.is_legacy_share;
  // Chart symbol: for options, use underlying ticker; for others, use the trade symbol
  const chartSymbol = isOptions
    ? (trade.underlying_symbol ?? trade.symbol).replace("/", "-")
    : trade.symbol.replace("/", "-");
  const unitLabel = isCrypto
    ? trade.symbol.split("/")[0]
    : (isOptions && !isLegacyShare)
      ? "contracts"
      : "shares";
  const backTo = trade.bot_profile ? `/strategy/${trade.bot_profile}` : "/strategy";
  // Shared decimal floor for all price levels in this trade
  const tradeDec = groupDecimals(
    trade.entry_price_usd, trade.stop_loss_usd,
    trade.take_profit_usd, trade.exit_price_usd, livePrice,
  );

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-5 pb-20">
      {/* Legacy share banner */}
      {isLegacyShare && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 flex items-start gap-2">
          <span className="text-amber-400 mt-0.5 flex-shrink-0">⚠</span>
          <div>
            <p className="text-amber-400 text-xs font-semibold">Legacy Position — Pre-Options Fix</p>
            <p className="text-zinc-500 text-xs mt-0.5 leading-relaxed">
              This trade was created before the options fix (commit 17aa7f3). It is a <strong className="text-zinc-400">share position</strong>, not an options contract. P&L and quantity are shown in share terms.
            </p>
          </div>
        </div>
      )}

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-zinc-500">
        <button onClick={() => navigate(-1)} className="flex items-center gap-1 hover:text-zinc-300 transition-colors">
          <ArrowLeft size={12} />
          Back
        </button>
        <span>/</span>
        {trade.bot_display_name && (
          <>
            <Link to={backTo} className="hover:text-zinc-300 transition-colors">{trade.bot_display_name}</Link>
            <span>/</span>
          </>
        )}
        <span className="text-zinc-400 font-medium">{trade.symbol} #{trade.trade_id}</span>
      </div>

      {/* Header */}
      <div className="flex items-start gap-3">
        <div className={cn(
          "w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0",
          trade.side === "buy" ? "bg-lime-500/15" : "bg-orange-500/15"
        )}>
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
          <a
            href={trade.discord_message_url}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 border border-indigo-500/20 bg-indigo-500/10 px-3 py-1.5 rounded-lg transition-colors"
          >
            <ExternalLink size={12} />
            Discord Signal
          </a>
        )}
      </div>

      {/* P&L Hero */}
      <PnlHero
        symbol={trade.symbol}
        qty={trade.qty}
        entryPrice={trade.entry_price_usd}
        status={trade.status}
        realizedPnl={trade.realized_pnl_usd}
        livePrice={livePrice}
        groupDec={tradeDec}
        isOptions={isOptions && !isLegacyShare}
        contractCount={trade.contract_count}
        entryPremiumUsd={trade.entry_premium_usd}
        currentPremiumUsd={trade.current_premium_usd}
      />

      {/* Chart with price lines, markers, and legend */}
      <TradeChartSection
        symbol={chartSymbol}
        entryPrice={trade.entry_price_usd}
        entryTime={trade.entry_time}
        side={trade.side}
        qty={trade.qty}
        stopLoss={trade.stop_loss_usd}
        takeProfit={trade.take_profit_usd}
        exitPrice={trade.exit_price_usd}
        exitTime={trade.close_time}
        livePrice={livePrice}
        status={trade.status}
      />

      {/* Trade metadata */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-1">
        <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wide py-3 border-b border-zinc-800">Trade Details</p>
        <MetaRow label="Entry Price" value={fmt$(trade.entry_price_usd, tradeDec)} />
        <MetaRow label="Entry Time" value={fmtDate(trade.entry_time)} />
        <MetaRow label="Quantity" value={
          <span>
            {trade.qty?.toFixed(isCrypto ? 6 : 4)} {unitLabel}{" "}
            <span className="text-zinc-500">{formatNotional(trade.qty, trade.entry_price_usd)}</span>
          </span>
        } />
        <MetaRow label="Status" value={
          <span className={cn(
            "text-[10px] font-bold px-2 py-0.5 rounded-full",
            trade.status === "open" ? "bg-lime-500/15 text-lime-400" : "bg-zinc-700 text-zinc-400"
          )}>
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
            <span>
              {fmt$(trade.exit_price_usd, tradeDec)}{" "}
              {trade.qty && (
                <span className="text-zinc-500">
                  (exited for ${(trade.qty * trade.exit_price_usd).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })})
                </span>
              )}
            </span>
          } />
        )}
        {trade.close_time && (
          <MetaRow label="Close Time" value={fmtDate(trade.close_time)} />
        )}
        {trade.alpaca_order_id && (
          <MetaRow
            label="Order ID"
            value={<span className="text-zinc-400 font-mono text-[11px]">{trade.alpaca_order_id}</span>}
          />
        )}
      </div>

      {/* Options contract metadata */}
      {isOptions && !isLegacyShare && (
        <div className="bg-zinc-900 border border-purple-500/20 rounded-2xl px-5 py-1">
          <p className="text-xs font-semibold text-purple-400 uppercase tracking-wide py-3 border-b border-zinc-800">Options Contract</p>
          <MetaRow label="Underlying" value={trade.underlying_symbol ?? trade.symbol} />
          {trade.option_type && (
            <MetaRow label="Right" value={
              <span className={cn(
                "text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wide",
                trade.option_type === "call"
                  ? "bg-emerald-900/60 text-emerald-300"
                  : "bg-red-900/60 text-red-300",
              )}>
                {trade.option_type}
              </span>
            } />
          )}
          {trade.strike_price != null && (
            <MetaRow label="Strike" value={`$${trade.strike_price.toFixed(trade.strike_price % 1 === 0 ? 0 : 2)}`} />
          )}
          {trade.expiration_date && (
            <MetaRow label="Expiry" value={
              (() => {
                const d = new Date(trade.expiration_date + "T00:00:00Z");
                const dte = Math.round((d.getTime() - Date.now()) / 86_400_000);
                return `${trade.expiration_date} (${dte > 0 ? `${dte} DTE` : "expired"})`;
              })()
            } />
          )}
          {trade.contract_count != null && (
            <MetaRow label="Contracts" value={`${trade.contract_count} contract${trade.contract_count !== 1 ? "s" : ""}`} />
          )}
          {trade.entry_premium_usd != null && (
            <MetaRow label="Entry Premium" value={`$${trade.entry_premium_usd.toFixed(2)}/ct (cost basis $${((trade.entry_premium_usd) * (trade.contract_count ?? 1) * 100).toFixed(2)})`} />
          )}
          {trade.current_premium_usd != null ? (
            <MetaRow label="Current Premium" value={`$${trade.current_premium_usd.toFixed(2)}/ct`} />
          ) : (
            <MetaRow label="Current Premium" value={<span className="text-zinc-600 text-xs">Live quote unavailable</span>} />
          )}
          <div className="py-2.5 border-t border-zinc-800 mt-1">
            <p className="text-[10px] text-zinc-600">
              P&L formula: (current_premium − entry_premium) × contracts × 100
            </p>
          </div>
        </div>
      )}

      {/* Strategy context */}
      {(trade.strategy || trade.reason || trade.confidence != null) && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-1">
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wide py-3 border-b border-zinc-800">Strategy Signal</p>
          {trade.strategy && <MetaRow label="Strategy" value={trade.strategy.replace(/_/g, " ")} />}
          {trade.confidence != null && (
            <MetaRow label="Confidence" value={
              <div className="flex items-center gap-2">
                <div className="w-24 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full"
                    style={{ width: `${Math.min(100, Math.round(trade.confidence * 100))}%` }}
                  />
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

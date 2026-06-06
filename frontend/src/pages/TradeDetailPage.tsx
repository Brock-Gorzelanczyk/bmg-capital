import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, TrendingUp, TrendingDown, Clock, Target, Shield } from "lucide-react";
import { getTradeDetail } from "@/api/bots";
import { getLatestPrices, fetchBars } from "@/api/bars";
import CandlestickChart from "@/components/chart/CandlestickChart";
import { cn } from "@/lib/utils";
import type { Drawing } from "@/types/chart";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt$(n: number | null | undefined): string {
  if (n == null) return "—";
  return `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
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

// ─── Live P&L hero ────────────────────────────────────────────────────────────

function LivePnlHero({ symbol, qty, entryPrice, status, realizedPnl }: {
  symbol: string;
  qty: number;
  entryPrice: number;
  status: "open" | "closed";
  realizedPnl: number | null;
}) {
  const { data: prices } = useQuery({
    queryKey: ["latest-prices", symbol],
    queryFn: () => getLatestPrices([symbol]),
    refetchInterval: 5_000,
    staleTime: 0,
    enabled: status === "open",
  });

  const livePrice = prices?.[symbol] ?? null;

  const unrealizedPnl = (status === "open" && livePrice != null)
    ? (livePrice - entryPrice) * qty
    : null;

  const displayPnl = status === "closed" ? realizedPnl : unrealizedPnl;
  const pnlLabel = status === "closed" ? "Realized P&L" : "Unrealized P&L";
  const positive = displayPnl != null && displayPnl >= 0;

  const pnlPct = (status === "open" && livePrice != null && entryPrice > 0)
    ? ((livePrice - entryPrice) / entryPrice) * 100
    : (status === "closed" && realizedPnl != null && entryPrice > 0 && qty > 0)
    ? ((realizedPnl / (entryPrice * qty)) * 100)
    : null;

  return (
    <div className={cn(
      "rounded-2xl border p-6 flex flex-col sm:flex-row items-start sm:items-center gap-4",
      positive ? "bg-emerald-500/5 border-emerald-500/20" : displayPnl == null ? "bg-zinc-900 border-zinc-800" : "bg-red-500/5 border-red-500/20"
    )}>
      <div className="flex-1">
        <p className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">{pnlLabel}</p>
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className={cn("text-4xl font-bold tabular-nums", pnlColor(displayPnl))}>
            {displayPnl != null ? `${displayPnl >= 0 ? "+" : ""}${fmt$(displayPnl).replace("$", "")}` : "—"}
          </span>
          {pnlPct != null && (
            <span className={cn("text-lg font-semibold tabular-nums", pnlColor(displayPnl))}>
              ({pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%)
            </span>
          )}
        </div>
      </div>
      <div className="flex flex-col gap-1 text-right">
        <div>
          <p className="text-xs text-zinc-500">Entry</p>
          <p className="text-sm font-semibold text-white">{fmt$(entryPrice)}</p>
        </div>
        {status === "open" && (
          <div>
            <p className="text-xs text-zinc-500">Live</p>
            <p className={cn("text-sm font-semibold", livePrice != null ? "text-white" : "text-zinc-600")}>
              {livePrice != null ? fmt$(livePrice) : "…"}
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

// ─── Mini chart ───────────────────────────────────────────────────────────────

const INDICATOR_MAP: Record<string, { overlays: string[] }> = {
  canslim_leaders:        { overlays: ["EMA_21,SMA_50,SMA_200"] },
  stage2_breakout:        { overlays: ["EMA_21,SMA_50,SMA_200"] },
  momentum_surge:         { overlays: ["SMA_20,SMA_50"] },
  high_rs_momentum:       { overlays: ["SMA_50,SMA_200"] },
  power_trend:            { overlays: ["EMA_8,EMA_21,EMA_55"] },
  turtle_breakout:        { overlays: ["SMA_50,SMA_200"] },
  golden_cross:           { overlays: ["SMA_50,SMA_200"] },
};

function TradeMiniChart({ symbol, entryPrice, stopLoss, takeProfit, strategy }: {
  symbol: string;
  entryPrice: number;
  stopLoss: number | null;
  takeProfit: number | null;
  strategy: string | null;
}) {
  const indicators = (strategy && INDICATOR_MAP[strategy])
    ? INDICATOR_MAP[strategy].overlays[0]
    : "SMA_50,SMA_200";

  const { data: barsData, isLoading } = useQuery({
    queryKey: ["trade-mini-bars", symbol, indicators],
    queryFn: () => fetchBars(symbol, "1Day", indicators),
    staleTime: 300_000,
  });

  const bars = barsData?.bars ?? [];
  const rawIndicators = barsData?.indicators ?? {};

  const overlayIndicators = useMemo(() => {
    const out: Record<string, (number | null)[]> = {};
    Object.entries(rawIndicators).forEach(([k, v]) => {
      if (k.startsWith("SMA_") || k.startsWith("EMA_") || k.startsWith("BB_")) {
        out[k] = v;
      }
    });
    return out;
  }, [rawIndicators]);

  const drawings = useMemo<Drawing[]>(() => {
    const out: Drawing[] = [];
    out.push({ id: "entry", type: "hline", price: entryPrice, color: "#3b82f6" });
    if (stopLoss) out.push({ id: "stop", type: "hline", price: stopLoss, color: "#ef4444" });
    if (takeProfit) out.push({ id: "target", type: "hline", price: takeProfit, color: "#10b981" });
    return out;
  }, [entryPrice, stopLoss, takeProfit]);

  if (isLoading) {
    return <div className="h-64 bg-zinc-900 border border-zinc-800 rounded-2xl animate-pulse" />;
  }

  if (bars.length === 0) {
    return (
      <div className="h-64 bg-zinc-900 border border-zinc-800 rounded-2xl flex items-center justify-center">
        <p className="text-zinc-600 text-sm">No chart data available</p>
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center gap-3">
        <p className="text-sm font-semibold text-white">{symbol} — Daily</p>
        <div className="flex items-center gap-3 text-xs ml-auto">
          <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-blue-500 inline-block" /> Entry {fmt$(entryPrice)}</span>
          {stopLoss && <span className="flex items-center gap-1.5 text-red-400"><span className="w-3 h-0.5 bg-red-500 inline-block" /> Stop {fmt$(stopLoss)}</span>}
          {takeProfit && <span className="flex items-center gap-1.5 text-emerald-400"><span className="w-3 h-0.5 bg-emerald-500 inline-block" /> Target {fmt$(takeProfit)}</span>}
        </div>
      </div>
      <div className="h-64">
        <CandlestickChart
          bars={bars}
          indicators={overlayIndicators}
          drawings={drawings}
          height={256}
        />
      </div>
    </div>
  );
}

// ─── Metadata row ─────────────────────────────────────────────────────────────

function MetaRow({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-zinc-800 last:border-0">
      <span className="text-xs text-zinc-500">{label}</span>
      <span className={cn("text-sm text-white", mono && "font-mono text-xs")}>{value}</span>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function TradeDetailPage() {
  const { tradeId } = useParams<{ tradeId: string }>();
  const navigate = useNavigate();
  const id = parseInt(tradeId ?? "0", 10);

  const { data: trade, isLoading, isError } = useQuery({
    queryKey: ["bot-trade-detail", id],
    queryFn: () => getTradeDetail(id),
    enabled: id > 0,
    staleTime: 30_000,
    retry: 1,
  });

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8 space-y-4 animate-pulse">
        <div className="h-5 w-40 bg-zinc-800 rounded" />
        <div className="h-32 bg-zinc-900 rounded-2xl" />
        <div className="h-64 bg-zinc-900 rounded-2xl" />
        <div className="h-48 bg-zinc-900 rounded-2xl" />
      </div>
    );
  }

  if (isError || !trade) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8 text-center">
        <p className="text-zinc-500 text-sm mb-4">Trade not found.</p>
        <button onClick={() => navigate(-1)} className="text-xs text-blue-400 hover:text-blue-300">← Go back</button>
      </div>
    );
  }

  const isCrypto = trade.symbol.includes("/");
  const unitLabel = isCrypto ? trade.symbol.split("/")[0] : "shares";
  const backTo = trade.bot_profile ? `/strategy/${trade.bot_profile}` : "/strategy";

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-5 pb-20">
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
            {trade.side?.toUpperCase()} · {trade.qty?.toFixed(isCrypto ? 6 : 4)} {unitLabel}
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

      {/* Live P&L hero */}
      <LivePnlHero
        symbol={trade.symbol}
        qty={trade.qty}
        entryPrice={trade.entry_price_usd}
        status={trade.status}
        realizedPnl={trade.realized_pnl_usd}
      />

      {/* Chart */}
      <TradeMiniChart
        symbol={trade.symbol}
        entryPrice={trade.entry_price_usd}
        stopLoss={trade.stop_loss_usd}
        takeProfit={trade.take_profit_usd}
        strategy={trade.bot_profile}
      />

      {/* Trade metadata */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-1">
        <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wide py-3 border-b border-zinc-800">Trade Details</p>
        <MetaRow label="Entry Price" value={fmt$(trade.entry_price_usd)} />
        <MetaRow label="Entry Time" value={fmtDate(trade.entry_time)} />
        <MetaRow label="Quantity" value={`${trade.qty?.toFixed(isCrypto ? 6 : 4)} ${unitLabel}`} />
        <MetaRow label="Status" value={
          <span className={cn(
            "text-[10px] font-bold px-2 py-0.5 rounded-full",
            trade.status === "open" ? "bg-lime-500/15 text-lime-400" : "bg-zinc-700 text-zinc-400"
          )}>
            {trade.status.toUpperCase()}
          </span>
        } />
        {trade.stop_loss_usd != null && (
          <MetaRow label="Stop Loss" value={<span className="text-red-400 flex items-center gap-1"><Shield size={11} /> {fmt$(trade.stop_loss_usd)}</span>} />
        )}
        {trade.take_profit_usd != null && (
          <MetaRow label="Take Profit" value={<span className="text-emerald-400 flex items-center gap-1"><Target size={11} /> {fmt$(trade.take_profit_usd)}</span>} />
        )}
        {trade.exit_price_usd != null && (
          <MetaRow label="Exit Price" value={fmt$(trade.exit_price_usd)} />
        )}
        {trade.close_time && (
          <MetaRow label="Close Time" value={fmtDate(trade.close_time)} />
        )}
        {trade.alpaca_order_id && (
          <MetaRow label="Order ID" value={<span className="text-zinc-400 font-mono text-[11px]">{trade.alpaca_order_id}</span>} mono />
        )}
      </div>

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

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

// ─── Skinned components (2026-06-30) ─────────────────────────────────────────
// Visual restyle only. Every prop below flows from the same data source /
// P&L math / level calculations as the original components — nothing here
// computes or fetches; it's presentation. Ref: Trade Detail.dc.html.

const TD_COLORS = {
  entry:   "#5b8def",  // blue
  stop:    "#f87171",  // red
  target:  "#3ddc84",  // green
  exit:    "#f0a63c",  // orange
  current: "#22d3ee",  // cyan
  posGreen: "#3ddc84",
  negRed:   "#f87171",
  bgCard: "linear-gradient(180deg, rgba(14,32,20,0.7), rgba(8,16,10,0.55))",
  cardBorder: "rgba(74,222,128,0.28)",
  panelBorder: "rgba(74,222,128,0.14)",
  panelBg: "rgba(6,11,8,0.6)",
  textPrimary: "#f4f8f4",
  textMuted:   "#7e8e7e",
  textDim:     "#9fb0a0",
  textFaint:   "#50604f",
} as const;

/** Big instrument icon tile — orange ↘ for SELL, green ↗ for BUY. */
function SkinnedInstrumentIcon({ side }: { side: string }) {
  const isSell = side === "sell";
  const iconColor = isSell ? "#f0a63c" : "#3ddc84";
  const bg = isSell
    ? "linear-gradient(180deg,#2a1e0e,#1a1206)"
    : "linear-gradient(180deg,#0e2a1c,#062012)";
  const borderColor = isSell ? "rgba(240,166,60,0.28)" : "rgba(61,220,132,0.28)";
  const shadow = isSell ? "0 0 22px rgba(240,166,60,0.12)" : "0 0 22px rgba(61,220,132,0.12)";
  const glyph = isSell ? "↘" : "↗";
  return (
    <div
      style={{
        width: 66, height: 66, borderRadius: 16, background: bg,
        border: `1px solid ${borderColor}`,
        display: "flex", alignItems: "center", justifyContent: "center",
        boxShadow: shadow, flexShrink: 0,
      }}
    >
      <span style={{ fontSize: 30, color: iconColor }}>{glyph}</span>
    </div>
  );
}

/** Header row: icon tile + ticker + side/qty/notional/via bot subline. */
function SkinnedTradeHeader({
  symbol, side, qty, entryPrice, botDisplayName, unitLabel, isCrypto,
}: {
  symbol: string; side: string; qty: number; entryPrice: number;
  botDisplayName: string | null; unitLabel: string; isCrypto: boolean;
}) {
  const sideColor = side === "sell" ? "#f0a63c" : "#3ddc84";
  const qtyLabel = `${qty?.toFixed(isCrypto ? 6 : 4)} ${unitLabel}`;
  const notional = qty && entryPrice
    ? `($${(qty * entryPrice).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })})`
    : "";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
      <SkinnedInstrumentIcon side={side} />
      <div>
        <div
          style={{
            fontSize: 40, fontWeight: 700, letterSpacing: "-0.02em",
            color: TD_COLORS.textPrimary, lineHeight: 1,
            fontFamily: "'Space Grotesk', sans-serif",
          }}
        >
          {symbol}
        </div>
        <div
          style={{
            fontSize: 17, color: TD_COLORS.textMuted, marginTop: 9,
            fontFamily: "'Space Grotesk', sans-serif",
          }}
        >
          <span style={{ color: sideColor, fontWeight: 600 }}>{side?.toUpperCase()}</span>
          {" "}·{" "}
          {qtyLabel}{" "}
          <span style={{ color: TD_COLORS.textDim }}>{notional}</span>
          {botDisplayName && (
            <>
              {" "}
              <span style={{ color: TD_COLORS.textFaint }}>via</span> {botDisplayName}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** Compact meta strip — replaces the big P&L card (v2). P&L moves onto the
 *  chart header itself. This strip just shows ENTRY + status pill. */
function SkinnedMetaStrip({
  entryPrice, isClosed, livePrice, groupDec,
}: {
  entryPrice: number; isClosed: boolean;
  livePrice: number | null; groupDec: number;
}) {
  const statusText = isClosed ? "CLOSED" : "OPEN";
  const statusBg = isClosed ? "rgba(126,142,126,0.14)" : "rgba(61,220,132,0.14)";
  const statusColor = isClosed ? TD_COLORS.textDim : TD_COLORS.posGreen;
  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 14, marginTop: 20,
        flexWrap: "wrap",
      }}
    >
      <span
        style={{
          fontFamily: "'JetBrains Mono', monospace", fontSize: 13,
          letterSpacing: "0.16em", color: TD_COLORS.textMuted,
        }}
      >
        ENTRY{" "}
        <span style={{ color: TD_COLORS.textPrimary, fontVariantNumeric: "tabular-nums" }}>
          {fmt$(entryPrice, groupDec)}
        </span>
      </span>
      {!isClosed && livePrice != null && (
        <>
          <span style={{ width: 1, height: 16, background: "rgba(74,222,128,0.16)" }} />
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace", fontSize: 13,
              letterSpacing: "0.16em", color: TD_COLORS.textMuted,
            }}
          >
            LIVE{" "}
            <span style={{ color: TD_COLORS.textPrimary, fontVariantNumeric: "tabular-nums" }}>
              {fmt$(livePrice, groupDec)}
            </span>
          </span>
        </>
      )}
      <span style={{ width: 1, height: 16, background: "rgba(74,222,128,0.16)" }} />
      <span
        style={{
          display: "inline-block",
          fontFamily: "'JetBrains Mono', monospace", fontSize: 12,
          letterSpacing: "0.14em", color: statusColor,
          background: statusBg, borderRadius: 20, padding: "5px 15px",
        }}
      >
        {statusText}
      </span>
    </div>
  );
}

/** Chart-header P&L pill — v2 moves P&L from a big card onto the chart title row. */
function SkinnedPnlPill({
  displayPnl, pnlPct, isClosed,
}: {
  displayPnl: number | null; pnlPct: number | null; isClosed: boolean;
}) {
  if (displayPnl == null) return null;
  const positive = displayPnl >= 0;
  const dotColor = positive ? TD_COLORS.posGreen : TD_COLORS.negRed;
  const bg = positive ? "rgba(61,220,132,0.1)" : "rgba(248,113,113,0.1)";
  const border = positive ? "rgba(61,220,132,0.34)" : "rgba(248,113,113,0.34)";
  const label = isClosed ? "P&L" : "UNREAL";
  const pnlStr = `${positive ? "+$" : "-$"}${Math.abs(displayPnl).toFixed(2)}`;
  const pctStr = pnlPct != null ? ` · ${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%` : "";
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        fontFamily: "'JetBrains Mono', monospace", fontSize: 13, fontWeight: 600,
        color: dotColor, background: bg, border: `1px solid ${border}`,
        borderRadius: 20, padding: "4px 12px",
        fontVariantNumeric: "tabular-nums",
      }}
    >
      <span
        style={{
          width: 6, height: 6, borderRadius: "50%",
          background: dotColor, boxShadow: `0 0 6px ${dotColor}`,
        }}
      />
      {label} {pnlStr}{pctStr}
    </span>
  );
}

/** Compact top-LEFT legend (v2 — Trading Desk style, small font, tighter). */
function SkinnedChartLegend({
  entry, stop, target, exit, current,
}: {
  entry: number; stop: number | null; target: number | null;
  exit: number | null; current: number | null;
}) {
  const gd = groupDecimals(entry, stop, target, exit, current);
  const rows: { color: string; label: string; price: number }[] = [
    { color: TD_COLORS.entry, label: "Entry", price: entry },
  ];
  if (stop != null) rows.push({ color: TD_COLORS.stop, label: "Stop", price: stop });
  if (target != null) rows.push({ color: TD_COLORS.target, label: "Target", price: target });
  if (exit != null) rows.push({ color: TD_COLORS.exit, label: "Exit", price: exit });
  if (current != null) rows.push({ color: TD_COLORS.current, label: "Current", price: current });
  return (
    <div
      style={{
        position: "absolute", top: 12, left: 12,
        border: `1px solid ${TD_COLORS.panelBorder}`, borderRadius: 8,
        background: "rgba(6,11,8,0.82)",
        padding: "9px 11px", backdropFilter: "blur(3px)",
        zIndex: 10, pointerEvents: "none",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {rows.map((r) => {
          const deltaPct = r.label === "Entry" || !entry
            ? null
            : ((r.price - entry) / entry) * 100;
          const deltaColor = deltaPct == null ? null
            : deltaPct >= 0 ? TD_COLORS.posGreen : TD_COLORS.negRed;
          return (
            <div
              key={r.label}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
              }}
            >
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: r.color, flexShrink: 0 }} />
              <span style={{ color: TD_COLORS.textMuted, width: 54 }}>{r.label}</span>
              <span style={{ color: TD_COLORS.textPrimary, fontVariantNumeric: "tabular-nums" }}>
                {fmt$(r.price, gd)}
              </span>
              {deltaPct != null && (
                <span style={{ color: deltaColor ?? undefined, fontVariantNumeric: "tabular-nums" }}>
                  {deltaPct >= 0 ? "+" : ""}{deltaPct.toFixed(2)}%
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Skinned chart panel — rounded dark container wrapping TradePriceChart. */
function SkinnedChartSection({
  symbol, entryPrice, entryTime, side, qty, stopLoss, takeProfit,
  exitPrice, exitTime, livePrice, status, timeframeLabel,
  displayPnl, pnlPct,
}: {
  symbol: string; entryPrice: number; entryTime: string | null;
  side: string; qty: number; stopLoss: number | null; takeProfit: number | null;
  exitPrice: number | null; exitTime: string | null; livePrice: number | null;
  status: "open" | "closed"; timeframeLabel?: string;
  displayPnl: number | null; pnlPct: number | null;
}) {
  const barsSymbol = symbol.replace("/", "-");
  const { data: barsData, isLoading } = useQuery({
    queryKey: ["trade-price-bars", barsSymbol],
    queryFn: () => fetchBars(barsSymbol, "1Day"),
    staleTime: 300_000,
  });
  const bars = barsData?.bars ?? [];
  const gd = groupDecimals(entryPrice, stopLoss, takeProfit, exitPrice, livePrice);
  const tfLabel = timeframeLabel ?? "Daily";
  const nowDeltaPct = livePrice != null && entryPrice
    ? ((livePrice - entryPrice) / entryPrice) * 100 : null;
  return (
    <div
      style={{
        position: "relative", border: `1px solid ${TD_COLORS.panelBorder}`,
        borderRadius: 22, background: TD_COLORS.panelBg,
        padding: "22px 24px 16px", marginTop: 20,
      }}
    >
      <div
        style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginBottom: 10, gap: 16, flexWrap: "wrap",
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span
            style={{
              fontSize: 22, fontWeight: 700, color: TD_COLORS.textPrimary,
              fontFamily: "'Space Grotesk', sans-serif",
            }}
          >
            {symbol}{" "}
            <span style={{ color: TD_COLORS.textFaint, fontWeight: 500 }}>— {tfLabel}</span>
          </span>
          <SkinnedPnlPill displayPnl={displayPnl} pnlPct={pnlPct} isClosed={status === "closed"} />
        </span>
        <div
          style={{
            display: "flex", alignItems: "center", gap: 22,
            fontFamily: "'JetBrains Mono', monospace", fontSize: 14,
            flexWrap: "wrap",
          }}
        >
          <span style={{ display: "flex", alignItems: "center", gap: 8, color: "#8fa8d8" }}>
            <span style={{ width: 16, height: 3, background: TD_COLORS.entry, borderRadius: 2 }} />
            Entry {fmt$(entryPrice, gd)}
          </span>
          {livePrice != null && (
            <span style={{ display: "flex", alignItems: "center", gap: 8, color: "#5ec5d8" }}>
              <span style={{ width: 16, height: 3, background: TD_COLORS.current, borderRadius: 2 }} />
              NOW {fmt$(livePrice, gd)}
              {nowDeltaPct != null && (
                <span style={{ color: nowDeltaPct >= 0 ? TD_COLORS.posGreen : TD_COLORS.negRed, marginLeft: 4 }}>
                  ({nowDeltaPct >= 0 ? "+" : ""}{nowDeltaPct.toFixed(2)}%)
                </span>
              )}
            </span>
          )}
        </div>
      </div>
      <div style={{ position: "relative", width: "100%", height: 600 }}>
        {isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center text-zinc-600 text-sm">
            Loading chart…
          </div>
        ) : bars.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center text-zinc-600 text-sm">
            No chart data
          </div>
        ) : (
          <>
            <TradePriceChart
              bars={bars} entryPrice={entryPrice} entryTime={entryTime}
              side={side} qty={qty} symbol={symbol}
              stopLoss={stopLoss} takeProfit={takeProfit}
              exitPrice={exitPrice} exitTime={exitTime} livePrice={livePrice}
            />
            <SkinnedChartLegend
              entry={entryPrice}
              stop={stopLoss}
              target={takeProfit}
              exit={status === "closed" ? exitPrice : null}
              current={livePrice}
            />
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

  // ── P&L math for skinned card (same formulas as PnlHero, no calc changes) ──
  const _costBasis = trade.qty * trade.entry_price_usd;
  const _unrealizedPnl = trade.status !== "open" ? null
    : livePrice != null ? (livePrice - trade.entry_price_usd) * trade.qty : null;
  const _displayPnl = trade.status === "closed" ? trade.realized_pnl_usd : _unrealizedPnl;
  const _pnlPct = (_displayPnl != null && _costBasis > 0) ? (_displayPnl / _costBasis) * 100 : null;

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "radial-gradient(120% 80% at 50% -10%, #071009 0%, #040705 55%)",
        fontFamily: "'Space Grotesk', sans-serif",
        color: TD_COLORS.textPrimary,
        padding: "34px 40px 60px",
      }}
    >
      <div style={{ maxWidth: 1120, margin: "0 auto" }}>
        {isLegacyShare && (
          <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 flex items-start gap-2 mb-4">
            <AlertTriangle size={14} className="text-amber-400 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-amber-400 text-xs font-semibold">Legacy Position — Pre-Options Fix</p>
              <p className="text-zinc-500 text-xs mt-0.5 leading-relaxed">
                This trade was created before the options fix (commit 17aa7f3). It is a share position, not an options contract. P&L and quantity are shown in share terms.
              </p>
            </div>
          </div>
        )}

        {/* Breadcrumb — kept compact so it doesn't compete with the header */}
        <div
          style={{
            display: "flex", alignItems: "center", gap: 8,
            fontSize: 12, color: TD_COLORS.textFaint, marginBottom: 18,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          <button
            onClick={() => navigate(-1)}
            style={{ display: "flex", alignItems: "center", gap: 4, color: "inherit", background: "none", border: "none", cursor: "pointer" }}
          >
            <ArrowLeft size={12} /> Back
          </button>
          <span>/</span>
          {trade.bot_display_name && (
            <>
              <Link to={backTo} style={{ color: TD_COLORS.textMuted, textDecoration: "none" }}>
                {trade.bot_display_name}
              </Link>
              <span>/</span>
            </>
          )}
          <span style={{ color: TD_COLORS.textDim }}>
            {trade.symbol} #{trade.trade_id}
          </span>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 14 }}>
            {/* Trading Desk deep-link — open the cinematic view focused on
                this bot + symbol so the toasts + chart are filtered to
                just what the user came here to watch. */}
            <Link
              to={`/fund/desk?symbol=${encodeURIComponent(trade.symbol)}${trade.bot_profile ? `&bot=${encodeURIComponent(trade.bot_profile)}` : ""}&tf=5m`}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                color: TD_COLORS.current, textDecoration: "none",
                borderRadius: 20, padding: "5px 12px",
                background: "rgba(34,211,238,0.08)",
                border: "1px solid rgba(34,211,238,0.28)",
                fontSize: 11, letterSpacing: "0.06em",
              }}
              title="Open Trading Desk focused on this bot + symbol"
            >
              <Zap size={11} /> WATCH ON DESK
            </Link>
            {trade.discord_message_url && (
              <a
                href={trade.discord_message_url}
                target="_blank" rel="noopener noreferrer"
                style={{
                  display: "flex", alignItems: "center", gap: 6,
                  color: "#8fa8d8", textDecoration: "none",
                }}
              >
                <ExternalLink size={11} /> Discord Signal
              </a>
            )}
          </div>
        </div>

        <SkinnedTradeHeader
          symbol={trade.symbol}
          side={trade.side}
          qty={trade.qty}
          entryPrice={trade.entry_price_usd}
          botDisplayName={trade.bot_display_name ?? null}
          unitLabel={unitLabel}
          isCrypto={isCrypto}
        />

        <SkinnedMetaStrip
          entryPrice={trade.entry_price_usd}
          isClosed={trade.status === "closed"}
          livePrice={livePrice}
          groupDec={tradeDec}
        />

        <SkinnedChartSection
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
          displayPnl={_displayPnl}
          pnlPct={_pnlPct}
        />

        <div
          className="rounded-2xl px-5 py-1 mt-5"
          style={{
            background: "rgba(6,11,8,0.6)",
            border: `1px solid ${TD_COLORS.panelBorder}`,
          }}
        >
          <p
            className="text-xs font-semibold uppercase tracking-wide py-3 border-b"
            style={{ color: TD_COLORS.textDim, borderColor: TD_COLORS.panelBorder, fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.14em" }}
          >
            TRADE DETAILS
          </p>
          <MetaRow label="Entry Price" value={fmt$(trade.entry_price_usd, tradeDec)} />
          <MetaRow label="Entry Time" value={fmtDate(trade.entry_time)} />
          <MetaRow label="Quantity" value={
            <span>{trade.qty?.toFixed(isCrypto ? 6 : 4)} {unitLabel}{" "}
              <span style={{ color: TD_COLORS.textFaint }}>{formatNotional(trade.qty, trade.entry_price_usd)}</span>
            </span>
          } />
          <MetaRow label="Status" value={
            <span
              className="text-[10px] font-bold px-2 py-0.5 rounded-full"
              style={{
                background: trade.status === "open" ? "rgba(61,220,132,0.14)" : "rgba(126,142,126,0.14)",
                color: trade.status === "open" ? TD_COLORS.posGreen : TD_COLORS.textDim,
              }}
            >
              {trade.status.toUpperCase()}
            </span>
          } />
          {trade.stop_loss_usd != null && (
            <MetaRow label="Stop Loss" value={
              <span style={{ color: TD_COLORS.stop }} className="flex items-center gap-1">
                <Shield size={11} /> {fmt$(trade.stop_loss_usd, tradeDec)}
              </span>
            } />
          )}
          {trade.take_profit_usd != null && (
            <MetaRow label="Take Profit" value={
              <span style={{ color: TD_COLORS.target }} className="flex items-center gap-1">
                <Target size={11} /> {fmt$(trade.take_profit_usd, tradeDec)}
              </span>
            } />
          )}
          {trade.exit_price_usd != null && (
            <MetaRow label="Exit Price" value={
              <span>{fmt$(trade.exit_price_usd, tradeDec)}{" "}
                {trade.qty && <span style={{ color: TD_COLORS.textFaint }}>(${(trade.qty * trade.exit_price_usd).toFixed(2)})</span>}
              </span>
            } />
          )}
          {trade.close_time && <MetaRow label="Close Time" value={fmtDate(trade.close_time)} />}
          {trade.alpaca_order_id && (
            <MetaRow label="Order ID" value={
              <span className="font-mono text-[11px]" style={{ color: TD_COLORS.textDim }}>
                {trade.alpaca_order_id}
              </span>
            } />
          )}
        </div>

        {(trade.strategy || trade.reason || trade.confidence != null) && (
          <div
            className="rounded-2xl px-5 py-1 mt-5"
            style={{
              background: "rgba(6,11,8,0.6)",
              border: `1px solid ${TD_COLORS.panelBorder}`,
            }}
          >
            <p
              className="text-xs font-semibold uppercase tracking-wide py-3 border-b"
              style={{ color: TD_COLORS.textDim, borderColor: TD_COLORS.panelBorder, fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.14em" }}
            >
              STRATEGY SIGNAL
            </p>
            {trade.strategy && <MetaRow label="Strategy" value={trade.strategy.replace(/_/g, " ")} />}
            {trade.confidence != null && (
              <MetaRow label="Confidence" value={
                <div className="flex items-center gap-2">
                  <div className="w-24 h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(126,142,126,0.2)" }}>
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.min(100, Math.round(trade.confidence * 100))}%`,
                        background: TD_COLORS.entry,
                      }}
                    />
                  </div>
                  <span>{Math.round(trade.confidence * 100)}%</span>
                </div>
              } />
            )}
            {trade.reason && (
              <div className="py-3 border-t" style={{ borderColor: TD_COLORS.panelBorder }}>
                <p className="text-xs mb-1" style={{ color: TD_COLORS.textFaint }}>Signal Reason</p>
                <p className="text-sm leading-relaxed" style={{ color: TD_COLORS.textDim }}>{trade.reason}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

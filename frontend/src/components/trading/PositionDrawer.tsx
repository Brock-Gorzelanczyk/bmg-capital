import { useEffect, useRef } from "react";
import { X, TrendingUp, TrendingDown, ExternalLink } from "lucide-react";
import type { PaperPosition } from "@/api/paper";
import { COMPANY_INFO } from "@/data/companyInfo";
import { useMarketStore } from "@/store";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";

interface PositionDrawerProps {
  position: PaperPosition | null;
  onClose: () => void;
  onTrade: (symbol: string, side: "buy" | "sell") => void;
}

export default function PositionDrawer({ position, onClose, onTrade }: PositionDrawerProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const quotes = useMarketStore((s) => s.quotes);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  // Close on backdrop click
  function handleOverlayClick(e: React.MouseEvent) {
    if (e.target === overlayRef.current) onClose();
  }

  if (!position) return null;

  const info = COMPANY_INFO[position.symbol];
  const liveQuote = quotes[position.symbol];

  // Prefer live price; fall back to backend value
  const currentPrice = liveQuote?.price ?? position.current_price;
  const marketValue = position.qty * currentPrice;
  const unrealizedPnl = marketValue - position.cost_basis;
  const unrealizedPnlPct = position.cost_basis > 0 ? (unrealizedPnl / position.cost_basis) * 100 : 0;

  const prevClose = position.prev_close > 0 ? position.prev_close : currentPrice;
  const dayPnl = (currentPrice - prevClose) * position.qty;
  const dayPnlPct = prevClose > 0 ? ((currentPrice - prevClose) / prevClose) * 100 : 0;

  const isProfit = unrealizedPnl >= 0;
  const isDayUp = dayPnl >= 0;

  // Bar chart: market value vs cost basis
  const total = Math.max(marketValue, position.cost_basis);
  const mvPct = total > 0 ? (marketValue / total) * 100 : 0;
  const cbPct = total > 0 ? (position.cost_basis / total) * 100 : 0;

  return (
    <div
      ref={overlayRef}
      onClick={handleOverlayClick}
      className="fixed inset-0 z-50 flex items-stretch justify-end"
      style={{ backgroundColor: "rgba(2,6,23,0.6)" }}
    >
      {/* Drawer panel */}
      <div className="w-full max-w-sm bg-[var(--bg-elevated)] border-l border-[var(--border-subtle)] flex flex-col overflow-y-auto animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-4 border-b border-[var(--border-subtle)]">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono font-bold text-xl text-[var(--text-primary)]">{position.symbol}</span>
              {info && (
                <span className="text-xs text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)] px-2 py-0.5 rounded-full">
                  {info.sector}
                </span>
              )}
            </div>
            {info && (
              <p className="text-[var(--text-tertiary)] text-sm mt-0.5">{info.name}</p>
            )}
          </div>
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors p-1">
            <X size={18} />
          </button>
        </div>

        {/* Current Price */}
        <div className="px-5 pt-4 pb-3 border-b border-[var(--border-subtle)]">
          <div className={cn("text-3xl font-mono font-bold", isDayUp ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
            {currentPrice > 0 ? formatCurrency(currentPrice) : "—"}
          </div>
          <div className={cn("flex items-center gap-1.5 mt-1 text-sm font-mono", isDayUp ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
            {isDayUp ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
            <span>{isDayUp ? "+" : ""}{formatCurrency(dayPnl)} ({formatPercent(dayPnlPct)}) today</span>
          </div>
        </div>

        {/* Position stats */}
        <div className="px-5 py-4 space-y-3 border-b border-[var(--border-subtle)]">
          {[
            { label: "Shares", value: position.qty.toLocaleString(undefined, { maximumFractionDigits: 4 }) },
            { label: "Avg Cost", value: formatCurrency(position.avg_cost) },
            { label: "Market Value", value: formatCurrency(marketValue) },
            { label: "Cost Basis", value: formatCurrency(position.cost_basis) },
          ].map(({ label, value }) => (
            <div key={label} className="flex items-center justify-between">
              <span className="text-sm text-[var(--text-tertiary)]">{label}</span>
              <span className="text-sm font-mono text-[var(--text-primary)]">{value}</span>
            </div>
          ))}
        </div>

        {/* Unrealized P&L — large */}
        <div className="px-5 py-4 border-b border-[var(--border-subtle)]">
          <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-widest mb-2">Unrealized P&L</p>
          <div className={cn("text-2xl font-mono font-bold", isProfit ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
            {isProfit ? "+" : ""}{formatCurrency(unrealizedPnl)}
          </div>
          <div className={cn("text-sm font-mono mt-0.5", isProfit ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
            {formatPercent(unrealizedPnlPct)}
          </div>
        </div>

        {/* Cost basis vs market value bar */}
        <div className="px-5 py-4 border-b border-[var(--border-subtle)]">
          <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-widest mb-3">Value vs. Cost Basis</p>
          <div className="space-y-2">
            {/* Market value bar */}
            <div>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-[var(--text-tertiary)]">Market Value</span>
                <span className="font-mono text-[var(--text-secondary)]">{formatCurrency(marketValue)}</span>
              </div>
              <div className="h-2 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
                <div
                  className={cn("h-full rounded-full transition-all duration-500", isProfit ? "bg-[#22C55E]" : "bg-[#EF4444]")}
                  style={{ width: `${mvPct}%` }}
                />
              </div>
            </div>
            {/* Cost basis bar */}
            <div>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-[var(--text-tertiary)]">Cost Basis</span>
                <span className="font-mono text-[var(--text-secondary)]">{formatCurrency(position.cost_basis)}</span>
              </div>
              <div className="h-2 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full bg-[#334155] transition-all duration-500"
                  style={{ width: `${cbPct}%` }}
                />
              </div>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="px-5 py-4 space-y-2 mt-auto">
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => { onTrade(position.symbol, "buy"); }}
              className="py-3 rounded-xl text-sm font-semibold bg-[#22C55E] text-black hover:bg-emerald-400 transition-colors"
            >
              Buy More
            </button>
            <button
              onClick={() => { onTrade(position.symbol, "sell"); }}
              className="py-3 rounded-xl text-sm font-semibold bg-[#EF4444] text-[var(--text-primary)] hover:bg-red-400 transition-colors"
            >
              Sell
            </button>
          </div>
          <button
            onClick={() => { onTrade(position.symbol, "sell"); onClose(); }}
            className="w-full py-2.5 rounded-xl text-sm font-semibold bg-[var(--bg-elevated-2)] text-[var(--accent-negative)] border border-red-900/40 hover:bg-red-950/30 transition-colors"
          >
            Close Position ({position.qty.toLocaleString(undefined, { maximumFractionDigits: 4 })} {position.symbol.includes("/") ? position.symbol.split("/")[0] : "shares"})
          </button>
        </div>
      </div>
    </div>
  );
}

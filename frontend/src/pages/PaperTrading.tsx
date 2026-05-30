import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getAccount,
  getOrders,
  getTransactions,
  cancelOrder,
  resetAccount,
  seedDemo,
} from "@/api/paper";
import type { PaperPosition, PaperOrder, PaperTransaction } from "@/api/paper";
import { useMarketStore } from "@/store";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import {
  Plus,
  RotateCcw,
  AlertTriangle,
  X,
  Sprout,
  TrendingUp,
  TrendingDown,
  ChevronRight,
  Clock,
  CheckCircle2,
  XCircle,
  Ban,
  Bot,
} from "lucide-react";
import { toast } from "sonner";
import { COMPANY_INFO } from "@/data/companyInfo";
import OrderTicket from "@/components/trading/OrderTicket";
import PositionDrawer from "@/components/trading/PositionDrawer";
import AskAIDrawer from "@/components/ui/AskAIDrawer";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor(diff / 60_000);
  if (h >= 24) return `${Math.floor(h / 24)}d ago`;
  if (h >= 1) return `${h}h ago`;
  if (m >= 1) return `${m}m ago`;
  return "just now";
}

function fmtDate(dateStr: string) {
  return new Date(dateStr).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

type PageTab = "positions" | "orders" | "activity";
type OrderFilter = "working" | "filled" | "all";

const STATUS_ICONS: Record<PaperOrder["status"], React.ReactNode> = {
  working: <Clock size={12} className="text-[#F59E0B]" />,
  filled: <CheckCircle2 size={12} className="text-[var(--accent-positive)]" />,
  cancelled: <Ban size={12} className="text-[var(--text-tertiary)]" />,
  rejected: <XCircle size={12} className="text-[var(--accent-negative)]" />,
  expired: <Ban size={12} className="text-[var(--text-tertiary)]" />,
};

const STATUS_LABEL: Record<PaperOrder["status"], string> = {
  working: "Working",
  filled: "Filled",
  cancelled: "Cancelled",
  rejected: "Rejected",
  expired: "Expired",
};

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function SkeletonRow({ cols = 5 }: { cols?: number }) {
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 bg-[var(--bg-elevated-2)] animate-pulse rounded" style={{ width: i === 0 ? "80px" : "60px" }} />
        </td>
      ))}
    </tr>
  );
}

function SkeletonCard() {
  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
      <div className="h-3 w-20 bg-[var(--bg-elevated-2)] animate-pulse rounded mb-3" />
      <div className="h-7 w-32 bg-[var(--bg-elevated-2)] animate-pulse rounded" />
    </div>
  );
}

// ─── Order Ticket Modal ────────────────────────────────────────────────────────

interface TicketModalProps {
  symbol: string;
  defaultSide?: "buy" | "sell";
  onClose: () => void;
}

function TicketModal({ symbol, defaultSide, onClose }: TicketModalProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(2,6,23,0.7)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="w-full max-w-sm animate-in zoom-in-95 duration-150">
        <OrderTicket symbol={symbol} defaultSide={defaultSide} onClose={onClose} />
      </div>
    </div>
  );
}

// ─── Positions Tab ─────────────────────────────────────────────────────────────

interface PositionsTabProps {
  positions: PaperPosition[];
  isLoading: boolean;
  isError: boolean;
  onSelectPosition: (pos: PaperPosition) => void;
  onTrade: (symbol: string, side: "buy" | "sell") => void;
}

function PositionsTab({ positions, isLoading, isError, onSelectPosition, onTrade }: PositionsTabProps) {
  const quotes = useMarketStore((s) => s.quotes);

  if (isLoading) {
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <tbody>{Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} cols={6} />)}</tbody>
        </table>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="text-[var(--accent-negative)] text-sm text-center py-8">Failed to load positions. Please refresh.</div>
    );
  }

  if (positions.length === 0) {
    return (
      <div className="py-16 text-center text-[var(--text-tertiary)]">
        <Plus size={32} className="mx-auto mb-3 text-[#1E293B]" />
        <p className="text-sm font-medium text-[var(--text-secondary)]">No open positions.</p>
        <p className="text-xs mt-1">Use the order ticket to place your first trade.</p>
      </div>
    );
  }

  const rows = positions.map((pos) => {
    const livePrice = quotes[pos.symbol]?.price ?? pos.current_price;
    const mv = pos.qty * livePrice;
    const pnl = mv - pos.cost_basis;
    const pnlPct = pos.cost_basis > 0 ? (pnl / pos.cost_basis) * 100 : 0;
    const prevClose = pos.prev_close > 0 ? pos.prev_close : livePrice;
    const dayPnl = (livePrice - prevClose) * pos.qty;
    const dayPnlPct = prevClose > 0 ? ((livePrice - prevClose) / prevClose) * 100 : 0;
    const info = COMPANY_INFO[pos.symbol];
    return { pos, livePrice, mv, pnl, pnlPct, dayPnl, dayPnlPct, info };
  });

  return (
    <div>
      {/* Mobile card list */}
      <div className="md:hidden divide-y divide-[#1E293B]">
        {rows.map(({ pos, livePrice, mv, pnl, pnlPct, dayPnl, dayPnlPct, info }) => (
          <div
            key={pos.id}
            onClick={() => onSelectPosition(pos)}
            className="p-4 cursor-pointer active:bg-[var(--bg-elevated-2)]/40 transition-colors"
          >
            <div className="flex items-start justify-between mb-3">
              <div>
                <span className="font-mono font-bold text-[var(--text-primary)] text-base">{pos.symbol}</span>
                {info && <div className="text-[11px] text-[var(--text-tertiary)] mt-0.5">{info.name}</div>}
              </div>
              <div className="text-right">
                <div className="text-sm font-mono font-semibold text-[var(--text-primary)]">{livePrice > 0 ? formatCurrency(mv) : "—"}</div>
                <div className="text-[11px] text-[var(--text-tertiary)]">
                  {pos.qty.toLocaleString(undefined, { maximumFractionDigits: 4 })} sh @ {formatCurrency(pos.avg_cost)}
                </div>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div className="bg-[var(--bg-base)] rounded-lg px-3 py-2">
                <div className="text-[9px] text-[var(--text-tertiary)] uppercase tracking-wide mb-1">Current</div>
                <div className="text-xs font-mono text-[var(--text-primary)]">{livePrice > 0 ? formatCurrency(livePrice) : "—"}</div>
              </div>
              <div className="bg-[var(--bg-base)] rounded-lg px-3 py-2">
                <div className="text-[9px] text-[var(--text-tertiary)] uppercase tracking-wide mb-1">Total P&L</div>
                <div className={cn("text-xs font-mono font-semibold", pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                  {pnl >= 0 ? "▲" : "▼"} {formatCurrency(Math.abs(pnl))}
                </div>
                <div className={cn("text-[9px]", pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                  {Math.abs(pnlPct).toFixed(2)}%
                </div>
              </div>
              <div className="bg-[var(--bg-base)] rounded-lg px-3 py-2">
                <div className="text-[9px] text-[var(--text-tertiary)] uppercase tracking-wide mb-1">Day P&L</div>
                <div className={cn("text-xs font-mono", dayPnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                  {dayPnl >= 0 ? "▲" : "▼"} {formatCurrency(Math.abs(dayPnl))}
                </div>
                <div className={cn("text-[9px]", dayPnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                  {Math.abs(dayPnlPct).toFixed(2)}%
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider border-b border-[var(--border-subtle)]">
              <th className="text-left px-4 py-2.5">Symbol</th>
              <th className="text-right px-4 py-2.5">Qty</th>
              <th className="text-right px-4 py-2.5">Avg Cost</th>
              <th className="text-right px-4 py-2.5">Current</th>
              <th className="text-right px-4 py-2.5">Market Value</th>
              <th className="text-right px-4 py-2.5">Unrealized P&L</th>
              <th className="text-right px-4 py-2.5">Day P&L</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {rows.map(({ pos, livePrice, mv, pnl, pnlPct, dayPnl, dayPnlPct, info }) => (
              <tr
                key={pos.id}
                className="border-b border-[var(--border-subtle)]/50 hover:bg-[var(--bg-elevated-2)]/40 cursor-pointer transition-colors group"
                onClick={() => onSelectPosition(pos)}
              >
                <td className="px-4 py-3">
                  <div className="font-mono font-bold text-[var(--text-primary)]">{pos.symbol}</div>
                  {info && <div className="text-xs text-[var(--text-tertiary)]">{info.name}</div>}
                </td>
                <td className="px-4 py-3 text-right font-mono text-[var(--text-secondary)]">
                  {pos.qty.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                </td>
                <td className="px-4 py-3 text-right font-mono text-[var(--text-secondary)]">
                  {formatCurrency(pos.avg_cost)}
                </td>
                <td className="px-4 py-3 text-right font-mono text-[var(--text-primary)]">
                  {livePrice > 0 ? formatCurrency(livePrice) : "—"}
                </td>
                <td className="px-4 py-3 text-right font-mono text-[var(--text-primary)]">
                  {formatCurrency(mv)}
                </td>
                <td
                  className={cn("px-4 py-3 text-right font-mono font-semibold", pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}
                  aria-label={`${pnl >= 0 ? "Gain" : "Loss"}: ${formatCurrency(Math.abs(pnl))}`}
                >
                  <div>{pnl >= 0 ? "▲" : "▼"} {formatCurrency(Math.abs(pnl))}</div>
                  <div className="text-xs opacity-75">{pnlPct >= 0 ? "▲" : "▼"} {Math.abs(pnlPct).toFixed(2)}%</div>
                </td>
                <td
                  className={cn("px-4 py-3 text-right font-mono", dayPnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}
                  aria-label={`${dayPnl >= 0 ? "Gain" : "Loss"}: ${formatCurrency(Math.abs(dayPnl))}`}
                >
                  <div>{dayPnl >= 0 ? "▲" : "▼"} {formatCurrency(Math.abs(dayPnl))}</div>
                  <div className="text-xs opacity-75">{dayPnlPct >= 0 ? "▲" : "▼"} {Math.abs(dayPnlPct).toFixed(2)}%</div>
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={(e) => { e.stopPropagation(); onTrade(pos.symbol, "buy"); }}
                    className="text-xs text-[var(--accent-positive)] hover:text-blue-300 font-semibold opacity-0 group-hover:opacity-100 transition-all mr-2"
                  >
                    Trade
                  </button>
                  <ChevronRight size={14} className="text-[var(--border-emphasis)] group-hover:text-[var(--text-tertiary)] transition-colors inline" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Orders Tab ───────────────────────────────────────────────────────────────

interface OrdersTabProps {
  isLoading: boolean;
}

function OrdersTab({ isLoading }: OrdersTabProps) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<OrderFilter>("all");

  const { data: orders = [] } = useQuery({
    queryKey: ["paper-orders"],
    queryFn: () => getOrders(),
    staleTime: 10_000,
  });

  const cancelMut = useMutation({
    mutationFn: (id: number) => cancelOrder(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["paper-orders"] });
      toast.success("Order cancelled");
    },
    onError: () => toast.error("Failed to cancel order"),
  });

  const filtered =
    filter === "all"
      ? orders
      : orders.filter((o) => {
          if (filter === "working") return o.status === "working";
          if (filter === "filled") return o.status === "filled";
          return true;
        });

  return (
    <div>
      {/* Sub-filter */}
      <div className="px-4 py-2.5 border-b border-[var(--border-subtle)] flex gap-1.5">
        {(["all", "working", "filled"] as OrderFilter[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "px-3 py-1 rounded-full text-xs font-semibold capitalize transition-colors",
              filter === f
                ? "bg-[#334155] text-[var(--text-primary)]"
                : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            )}
          >
            {f}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="divide-y divide-[#1E293B]">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="p-4 flex justify-between">
              <div className="space-y-2">
                <div className="h-4 w-16 bg-[var(--bg-elevated-2)] animate-pulse rounded" />
                <div className="h-3 w-24 bg-[var(--bg-elevated-2)] animate-pulse rounded" />
              </div>
              <div className="h-4 w-20 bg-[var(--bg-elevated-2)] animate-pulse rounded" />
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="py-14 text-center text-[var(--text-tertiary)]">
          <p className="text-sm">No orders</p>
        </div>
      ) : (
        <div>
          {/* Mobile card list */}
          <div className="md:hidden divide-y divide-[#1E293B]">
            {filtered.map((o) => (
              <div key={o.id} className="p-4">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-[var(--text-primary)]">{o.symbol}</span>
                    <span className={cn(
                      "text-[10px] font-bold px-1.5 py-0.5 rounded-full",
                      o.side === "buy" ? "bg-emerald-900/40 text-emerald-400" : "bg-rose-900/40 text-red-400"
                    )}>
                      {o.side.toUpperCase()}
                    </span>
                  </div>
                  <span className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
                    {STATUS_ICONS[o.status]}
                    {STATUS_LABEL[o.status]}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs text-[var(--text-tertiary)]">
                  <span className="capitalize">{o.order_type.replace("_", " ")} · {(o.fill_qty ?? o.qty).toLocaleString(undefined, { maximumFractionDigits: 4 })} sh</span>
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-[var(--text-secondary)]">{o.fill_price ? formatCurrency(o.fill_price) : "—"}</span>
                    <span>{o.filled_at ? timeAgo(o.filled_at) : timeAgo(o.created_at)}</span>
                    {o.status === "working" && (
                      <button
                        onClick={() => cancelMut.mutate(o.id)}
                        disabled={cancelMut.isPending}
                        className="text-[var(--text-tertiary)] hover:text-red-400 transition-colors disabled:opacity-50 min-h-[44px] min-w-[44px] flex items-center justify-center"
                      >
                        <X size={14} />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Desktop table */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider border-b border-[var(--border-subtle)]">
                  <th className="text-left px-4 py-2.5">Symbol</th>
                  <th className="text-left px-4 py-2.5">Side</th>
                  <th className="text-left px-4 py-2.5">Type</th>
                  <th className="text-right px-4 py-2.5">Qty</th>
                  <th className="text-right px-4 py-2.5">Fill Price</th>
                  <th className="text-left px-4 py-2.5">Status</th>
                  <th className="text-right px-4 py-2.5">Time</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((o) => (
                  <tr key={o.id} className="border-b border-[var(--border-subtle)]/50 hover:bg-[var(--bg-elevated-2)]/30 transition-colors">
                    <td className="px-4 py-3 font-mono font-bold text-[var(--text-primary)]">{o.symbol}</td>
                    <td className="px-4 py-3">
                      <span className={cn(
                        "text-xs font-bold px-2 py-0.5 rounded-full",
                        o.side === "buy"
                          ? "bg-emerald-900/40 text-emerald-400"
                          : "bg-rose-900/40 text-red-400"
                      )}>
                        {o.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[var(--text-secondary)] capitalize">
                      {o.order_type.replace("_", " ")}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[var(--text-secondary)]">
                      {(o.fill_qty ?? o.qty).toLocaleString(undefined, { maximumFractionDigits: 4 })}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[var(--text-primary)]">
                      {o.fill_price ? formatCurrency(o.fill_price) : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                        {STATUS_ICONS[o.status]}
                        {STATUS_LABEL[o.status]}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-[var(--text-tertiary)] text-xs">
                      {o.filled_at ? timeAgo(o.filled_at) : timeAgo(o.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {o.status === "working" && (
                        <button
                          onClick={() => cancelMut.mutate(o.id)}
                          disabled={cancelMut.isPending}
                          className="flex items-center gap-1 text-xs text-[var(--text-tertiary)] hover:text-red-400 transition-colors disabled:opacity-50"
                        >
                          <X size={12} /> Cancel
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Activity Tab ─────────────────────────────────────────────────────────────

function ActivityTab() {
  const { data: txns = [], isLoading } = useQuery({
    queryKey: ["paper-transactions"],
    queryFn: getTransactions,
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <table className="w-full text-sm">
        <tbody>{Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} cols={6} />)}</tbody>
      </table>
    );
  }

  if (txns.length === 0) {
    return (
      <div className="py-14 text-center text-[var(--text-tertiary)]">
        <p className="text-sm">No transactions yet</p>
        <p className="text-xs mt-1">Realized P&L will appear here after you close positions.</p>
      </div>
    );
  }

  return (
    <div>
      {/* Mobile card list */}
      <div className="md:hidden divide-y divide-[#1E293B]">
        {txns.map((t: PaperTransaction) => {
          const pnlPositive = t.realized_pnl >= 0;
          return (
            <div key={t.id} className="p-4">
              <div className="flex items-start justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-[var(--text-primary)]">{t.symbol}</span>
                  <span className={cn(
                    "text-[10px] font-bold px-1.5 py-0.5 rounded-full",
                    t.side === "buy" ? "bg-emerald-900/40 text-emerald-400" : "bg-rose-900/40 text-red-400"
                  )}>
                    {t.side.toUpperCase()}
                  </span>
                </div>
                <span className={cn("text-sm font-mono font-semibold", pnlPositive ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                  {pnlPositive ? "▲" : "▼"} {formatCurrency(Math.abs(t.realized_pnl))}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs text-[var(--text-tertiary)]">
                <span>{t.qty.toLocaleString(undefined, { maximumFractionDigits: 4 })} sh @ <span className="font-mono text-[var(--text-secondary)]">{formatCurrency(t.fill_price)}</span></span>
                <span>{fmtDate(t.created_at)}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider border-b border-[var(--border-subtle)]">
              <th className="text-left px-4 py-2.5">Symbol</th>
              <th className="text-left px-4 py-2.5">Side</th>
              <th className="text-right px-4 py-2.5">Qty</th>
              <th className="text-right px-4 py-2.5">Fill Price</th>
              <th className="text-right px-4 py-2.5">Realized P&L</th>
              <th className="text-right px-4 py-2.5">Date</th>
            </tr>
          </thead>
          <tbody>
          {txns.map((t: PaperTransaction) => {
            const pnlPositive = t.realized_pnl >= 0;
            return (
              <tr key={t.id} className="border-b border-[var(--border-subtle)]/50 hover:bg-[var(--bg-elevated-2)]/30 transition-colors">
                <td className="px-4 py-3 font-mono font-bold text-[var(--text-primary)]">{t.symbol}</td>
                <td className="px-4 py-3">
                  <span className={cn(
                    "text-xs font-bold px-2 py-0.5 rounded-full",
                    t.side === "buy"
                      ? "bg-emerald-900/40 text-emerald-400"
                      : "bg-rose-900/40 text-red-400"
                  )}>
                    {t.side.toUpperCase()}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-mono text-[var(--text-secondary)]">
                  {t.qty.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                </td>
                <td className="px-4 py-3 text-right font-mono text-[var(--text-primary)]">
                  {formatCurrency(t.fill_price)}
                </td>
                <td className={cn("px-4 py-3 text-right font-mono font-semibold", pnlPositive ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                  {pnlPositive ? "+" : ""}{formatCurrency(t.realized_pnl)}
                </td>
                <td className="px-4 py-3 text-right text-[var(--text-tertiary)] text-xs">
                  {fmtDate(t.created_at)}
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

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function PaperTrading() {
  const qc = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  const [activeTab, setActiveTab] = useState<PageTab>("positions");
  const [showReset, setShowReset] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [ticketModal, setTicketModal] = useState<{ symbol: string; side: "buy" | "sell" } | null>(null);
  const [selectedPosition, setSelectedPosition] = useState<PaperPosition | null>(null);
  const [fabSymbol, setFabSymbol] = useState("AAPL");

  // Auto-open order ticket when navigated from Portfolio with ?symbol=&side=
  useEffect(() => {
    const sym = searchParams.get("symbol");
    const side = searchParams.get("side");
    if (sym) {
      setFabSymbol(sym);
      setTicketModal({ symbol: sym, side: side === "sell" ? "sell" : "buy" });
      setSearchParams({}, { replace: true });
    }
  }, []);

  const { data: account, isLoading, isError: accountError } = useQuery({
    queryKey: ["paper-account"],
    queryFn: getAccount,
    staleTime: 10_000,
    refetchInterval: 30_000,
  });

  const resetMut = useMutation({
    mutationFn: resetAccount,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["paper-account"] });
      qc.invalidateQueries({ queryKey: ["paper-orders"] });
      qc.invalidateQueries({ queryKey: ["paper-transactions"] });
      setShowReset(false);
      toast.success("Account reset to $100,000");
    },
    onError: () => toast.error("Reset failed"),
  });

  const seedMut = useMutation({
    mutationFn: seedDemo,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["paper-account"] });
      qc.invalidateQueries({ queryKey: ["paper-orders"] });
      qc.invalidateQueries({ queryKey: ["paper-transactions"] });
      toast.success("Demo account seeded with sample positions");
    },
    onError: () => toast.error("Seed failed"),
  });

  const positions = account?.positions ?? [];

  function openTrade(symbol: string, side: "buy" | "sell") {
    setFabSymbol(symbol);
    setSelectedPosition(null);
    setTicketModal({ symbol, side });
  }

  // Summary stats from account
  const equity = account?.equity ?? 0;
  const cash = account?.cash ?? 0;
  const dayPnl = account?.day_pnl ?? 0;
  const dayPnlPct = account?.day_pnl_pct ?? 0;
  const totalPnl = account?.total_pnl ?? 0;
  const totalPnlPct = account?.total_pnl_pct ?? 0;

  const isDayUp = dayPnl >= 0;
  const isTotalUp = totalPnl >= 0;

  return (
    <div className="max-w-7xl mx-auto space-y-5 pb-24">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold text-[var(--text-primary)]">Paper Trading</h1>
          <span className="text-xs font-semibold text-[#F59E0B] bg-yellow-900/30 border border-yellow-800/40 px-2 py-0.5 rounded-full">
            Demo Account
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setAiOpen(true)}
            className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
          >
            <Bot size={12} /> Ask AI
          </button>
          <button
            onClick={() => {
              const confirmed = window.confirm(
                "Seed demo will clear your existing positions and orders, then add sample positions. Your transaction history will be preserved. Continue?"
              );
              if (!confirmed) return;
              seedMut.mutate();
            }}
            disabled={seedMut.isPending}
            className="flex items-center gap-1.5 text-xs font-semibold text-[#F59E0B] bg-yellow-900/20 border border-yellow-800/40 px-3 py-1.5 rounded-lg hover:bg-yellow-900/40 transition-colors disabled:opacity-50"
          >
            <Sprout size={13} />
            {seedMut.isPending ? "Seeding…" : "Seed Demo"}
          </button>
          <button
            onClick={() => {
              const confirmed = window.confirm(
                "Reset will clear all your positions and orders, returning your account to $100,000 cash. Transaction history is preserved. This cannot be undone. Continue?"
              );
              if (!confirmed) return;
              setShowReset(true);
            }}
            className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] transition-colors px-3 py-1.5 rounded-lg hover:bg-red-950/20"
          >
            <RotateCcw size={13} />
            Reset
          </button>
        </div>
      </div>

      {/* ── Reset confirm ──────────────────────────────────────────────────── */}
      {showReset && (
        <div className="bg-red-950/30 border border-red-800/50 rounded-xl p-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-red-400 text-sm">
            <AlertTriangle size={16} />
            <span>This will erase all positions, orders, and history. Continue?</span>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={() => resetMut.mutate()}
              disabled={resetMut.isPending}
              className="bg-red-600 hover:bg-red-700 text-[var(--text-primary)] text-xs font-semibold px-3 py-1.5 rounded-lg disabled:opacity-50 transition-colors"
            >
              {resetMut.isPending ? "Resetting…" : "Yes, reset"}
            </button>
            <button
              onClick={() => setShowReset(false)}
              className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-xs px-2 py-1.5"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ── Account summary bar ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-5 gap-3">
        {/* Equity — large */}
        {isLoading ? (
          <>
            {Array.from({ length: 5 }).map((_, i) => <SkeletonCard key={i} />)}
          </>
        ) : (
          <>
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 xl:col-span-1">
              <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">Total Equity</div>
              <div className="text-2xl font-mono font-bold text-[var(--text-primary)]">{formatCurrency(equity)}</div>
            </div>

            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
              <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">
                Day's P&L <span className="normal-case font-normal opacity-60">vs prev close</span>
              </div>
              <div
                className={cn("text-xl font-mono font-bold", isDayUp ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}
                aria-label={`${isDayUp ? "Gain" : "Loss"}: ${formatCurrency(Math.abs(dayPnl))}`}
              >
                {isDayUp ? "▲" : "▼"} {formatCurrency(Math.abs(dayPnl))}
              </div>
              <div className={cn("text-xs font-mono mt-0.5", isDayUp ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                {isDayUp ? "▲" : "▼"} {Math.abs(dayPnlPct).toFixed(2)}%
              </div>
            </div>

            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
              <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">Total P&L</div>
              <div
                className={cn("text-lg font-mono font-semibold", isTotalUp ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}
                aria-label={`${isTotalUp ? "Gain" : "Loss"}: ${formatCurrency(Math.abs(totalPnl))}`}
              >
                {isTotalUp ? "▲" : "▼"} {formatCurrency(Math.abs(totalPnl))}
              </div>
              <div className={cn("text-xs font-mono mt-0.5", isTotalUp ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                {isTotalUp ? "▲" : "▼"} {Math.abs(totalPnlPct).toFixed(2)}%
              </div>
            </div>

            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
              <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">Cash Available</div>
              <div className="text-lg font-mono font-semibold text-[var(--text-primary)]">{formatCurrency(cash)}</div>
            </div>

            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
              <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">Buying Power</div>
              <div className="text-lg font-mono font-semibold text-[var(--text-primary)]">{formatCurrency(cash)}</div>
              <div className="text-xs text-[var(--text-tertiary)] mt-0.5">
                {positions.length} position{positions.length !== 1 ? "s" : ""}
              </div>
            </div>
          </>
        )}
      </div>

      {/* ── Tabs ────────────────────────────────────────────────────────────── */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
        {/* Tab bar */}
        <div className="flex border-b border-[var(--border-subtle)]">
          {(["positions", "orders", "activity"] as PageTab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "px-5 py-3.5 text-sm font-semibold capitalize transition-colors border-b-2 -mb-px",
                activeTab === tab
                  ? "text-[var(--text-primary)] border-[#3B82F6]"
                  : "text-[var(--text-tertiary)] border-transparent hover:text-[var(--text-secondary)]"
              )}
            >
              {tab}
              {tab === "positions" && positions.length > 0 && (
                <span className="ml-2 text-xs bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] rounded-full px-1.5 py-0.5">
                  {positions.length}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === "positions" && (
          <PositionsTab
            positions={positions}
            isLoading={isLoading}
            isError={accountError}
            onSelectPosition={(pos) => {
              setSelectedPosition(pos);
              setFabSymbol(pos.symbol);
            }}
            onTrade={openTrade}
          />
        )}
        {activeTab === "orders" && <OrdersTab isLoading={isLoading} />}
        {activeTab === "activity" && <ActivityTab />}
      </div>

      {/* ── Floating New Order Button ────────────────────────────────────────── */}
      <button
        onClick={() => setTicketModal({ symbol: fabSymbol, side: "buy" })}
        className="fixed bottom-20 md:bottom-6 right-4 md:right-6 z-40 w-14 h-14 rounded-full bg-[var(--accent-positive)] hover:bg-blue-400 text-[var(--text-primary)] shadow-lg shadow-blue-900/40 flex items-center justify-center transition-all hover:scale-105 active:scale-95"
        title="New Order"
      >
        <Plus size={22} />
      </button>

      {/* ── Order Ticket Modal ───────────────────────────────────────────────── */}
      {ticketModal && (
        <TicketModal
          symbol={ticketModal.symbol}
          defaultSide={ticketModal.side}
          onClose={() => setTicketModal(null)}
        />
      )}

      {/* ── Position Drawer ──────────────────────────────────────────────────── */}
      {selectedPosition && (
        <PositionDrawer
          position={selectedPosition}
          onClose={() => setSelectedPosition(null)}
          onTrade={(symbol, side) => {
            setSelectedPosition(null);
            openTrade(symbol, side);
          }}
        />
      )}

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title="Ask BMG about Paper Trading"
        context="Paper Trading simulator"
        suggestedQuestions={[
          "How should I think about position sizing in a paper portfolio?",
          "What's a good risk/reward ratio for swing trades?",
          "How does paper trading differ from live trading psychologically?",
          "What's a stop-loss strategy for volatile stocks?",
          "How can I measure whether my paper trading strategy is working?",
        ]}
      />
    </div>
  );
}

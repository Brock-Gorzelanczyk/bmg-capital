import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import client from "@/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

type TriggerType = "drift" | "cash_inflow" | "calendar" | "manual";

interface RebalanceTrade {
  symbol: string;
  action: string;
  qty: number;
  value: number;
}

interface RebalanceEvent {
  id: number | string;
  date: string;
  trigger: TriggerType;
  summary: string;
  trades?: RebalanceTrade[];
}

interface RebalanceHistoryResponse {
  logs: RebalanceEvent[];
}

interface RebalanceHistoryPanelProps {
  className?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const TRIGGER_STYLES: Record<TriggerType, { dot: string; label: string; pill: string }> = {
  drift: {
    dot: "bg-amber-400",
    label: "drift",
    pill: "bg-amber-500/10 border-amber-500/20 text-amber-400",
  },
  cash_inflow: {
    dot: "bg-green-400",
    label: "cash inflow",
    pill: "bg-green-500/10 border-green-500/20 text-green-400",
  },
  calendar: {
    dot: "bg-blue-400",
    label: "calendar",
    pill: "bg-blue-500/10 border-blue-500/20 text-blue-400",
  },
  manual: {
    dot: "bg-purple-400",
    label: "manual",
    pill: "bg-purple-500/10 border-purple-500/20 text-purple-400",
  },
};

function formatEventDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "...";
}

function formatEventValue(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

// ── Row component ─────────────────────────────────────────────────────────────

function EventRow({ event }: { event: RebalanceEvent }) {
  const [expanded, setExpanded] = useState(false);
  const styles = TRIGGER_STYLES[event.trigger] ?? TRIGGER_STYLES.manual;
  const hasTrades = event.trades && event.trades.length > 0;
  const tradeCount = event.trades?.length ?? 0;

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-3">
        {/* Dot + date */}
        <div className="flex flex-col items-center gap-1 pt-0.5 shrink-0">
          <span className={cn("w-2 h-2 rounded-full", styles.dot)} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-medium text-[var(--text-tertiary)] shrink-0">
              {formatEventDate(event.date)}
            </span>
            <span
              className={cn(
                "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide border",
                styles.pill
              )}
            >
              {styles.label}
            </span>
          </div>
          <p className="text-sm text-[var(--text-secondary)] mt-0.5 leading-snug">
            {expanded ? event.summary : truncate(event.summary, 60)}
          </p>

          {hasTrades && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 mt-1 transition-colors"
            >
              {expanded ? (
                <>
                  Collapse <ChevronUp size={12} />
                </>
              ) : (
                <>
                  Expand — see {tradeCount} trade{tradeCount !== 1 ? "s" : ""} <ChevronDown size={12} />
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Expanded trades table */}
      {expanded && hasTrades && (
        <div className="ml-5 bg-slate-800/40 border border-[var(--border-subtle)] rounded-lg overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[var(--border-subtle)]">
                <th className="text-left px-3 py-2 text-[var(--text-tertiary)] font-medium">Symbol</th>
                <th className="text-left px-3 py-2 text-[var(--text-tertiary)] font-medium">Action</th>
                <th className="text-right px-3 py-2 text-[var(--text-tertiary)] font-medium">Qty</th>
                <th className="text-right px-3 py-2 text-[var(--text-tertiary)] font-medium">~Value</th>
              </tr>
            </thead>
            <tbody>
              {event.trades!.map((trade, idx) => (
                <tr
                  key={idx}
                  className={cn(
                    "border-b border-[var(--border-subtle)] last:border-0",
                    "hover:bg-slate-700/20 transition-colors"
                  )}
                >
                  <td className="px-3 py-2 font-semibold text-[var(--text-primary)]">
                    {trade.symbol}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={cn(
                        "font-medium capitalize",
                        trade.action === "buy" ? "text-green-400" : "text-red-400"
                      )}
                    >
                      {trade.action}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right text-[var(--text-secondary)]">
                    {trade.qty}
                  </td>
                  <td className="px-3 py-2 text-right text-[var(--text-secondary)]">
                    {formatEventValue(trade.value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function RebalanceHistoryPanel({ className }: RebalanceHistoryPanelProps) {
  const { data, isLoading } = useQuery<RebalanceHistoryResponse>({
    queryKey: ["robo-rebalance-history"],
    queryFn: () => client.get<RebalanceHistoryResponse>("/api/robo/rebalance/history").then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });

  const events = (data?.logs ?? []) as RebalanceEvent[];

  return (
    <div
      className={cn(
        "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <span className="text-xs font-semibold tracking-widest text-[var(--text-tertiary)] uppercase">
          Recent Actions
        </span>
        <div className="flex-1 h-px bg-[var(--border-subtle)]" />
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex gap-3 animate-pulse">
              <div className="w-2 h-2 rounded-full bg-slate-600 mt-1 shrink-0" />
              <div className="flex-1 space-y-1.5">
                <div className="h-3 bg-slate-700/60 rounded w-24" />
                <div className="h-3 bg-slate-700/60 rounded w-3/4" />
              </div>
            </div>
          ))}
        </div>
      ) : events.length === 0 ? (
        <p className="text-sm text-[var(--text-tertiary)] text-center py-4">
          No rebalance events yet. We'll notify you when action is needed.
        </p>
      ) : (
        <div className="space-y-4">
          {/* Divider */}
          <div className="h-px bg-[var(--border-subtle)]" />
          {events.map((event) => (
            <EventRow key={event.id} event={event} />
          ))}
          <div className="h-px bg-[var(--border-subtle)]" />
        </div>
      )}

      {/* View full history */}
      <button className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 mt-4 transition-colors">
        View Full History <ChevronRight size={13} />
      </button>
    </div>
  );
}

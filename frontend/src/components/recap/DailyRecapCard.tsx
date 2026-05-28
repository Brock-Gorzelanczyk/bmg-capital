import { useState } from "react";
import { ChevronDown, ChevronUp, Calendar } from "lucide-react";
import { cn } from "@/lib/utils";
import type { DailyRecap } from "@/api/recap";

interface Props {
  recap: DailyRecap;
  defaultExpanded?: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPct(n: number | null, signed = true): string {
  if (n == null) return "—";
  const sign = signed && n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
}

function fmtCurrency(n: number): string {
  const abs = Math.abs(n);
  const sign = n >= 0 ? "+" : "-";
  return `${sign}$${abs.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function pctColor(n: number | null): string {
  if (n == null) return "text-[#94A3B8]";
  return n >= 0 ? "text-[#22C55E]" : "text-[#EF4444]";
}

function pctBadgeCls(n: number | null): string {
  if (n == null) return "bg-[#1E293B] text-[#94A3B8]";
  return n >= 0
    ? "bg-[#22C55E]/10 text-[#22C55E] border border-[#22C55E]/20"
    : "bg-[#EF4444]/10 text-[#EF4444] border border-[#EF4444]/20";
}

function formatRecapDate(dateStr: string | undefined | null): string {
  if (!dateStr) return "—";
  const [year, month, day] = dateStr.split("-").map(Number);
  const d = new Date(year, month - 1, day);
  return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function DailyRecapCard({ recap, defaultExpanded = false }: Props) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const spy    = recap.market_summary?.spy    ?? null;
  const qqq    = recap.market_summary?.qqq    ?? null;
  const iwm    = recap.market_summary?.iwm    ?? null;
  const vix    = recap.market_summary?.vix    ?? null;
  const breadth = recap.market_summary?.breadth ?? null;
  const strat  = recap.strategy_summary ?? { day_pnl: 0, day_pnl_pct: 0, new_entries: 0, exits: 0, open_positions: 0 };
  const top_setups = recap.top_setups ?? [];
  const narrative  = recap.narrative   ?? null;
  const dayPnlPos  = strat.day_pnl >= 0;

  return (
    <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl overflow-hidden">
      {/* ── Collapsed / header row ─────────────────────────────────── */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-[#1E293B]/50 transition-colors duration-150 text-left"
      >
        {/* Date */}
        <div className="flex items-center gap-1.5 shrink-0 text-[#94A3B8]">
          <Calendar size={13} />
          <span className="text-xs font-medium font-mono">{formatRecapDate(recap.recap_date)}</span>
        </div>

        {/* Market tickers */}
        <div className="hidden sm:flex items-center gap-3 text-xs font-mono flex-1">
          <span className="text-[#475569]">|</span>
          {spy != null && (
            <span className={cn("font-semibold", pctColor(spy))}>
              SPY {fmtPct(spy)}
            </span>
          )}
          {qqq != null && (
            <span className={cn("font-semibold", pctColor(qqq))}>
              QQQ {fmtPct(qqq)}
            </span>
          )}
          {iwm != null && (
            <span className={cn("font-semibold hidden md:inline", pctColor(iwm))}>
              IWM {fmtPct(iwm)}
            </span>
          )}
          <span className="text-[#475569]">|</span>
        </div>

        {/* P&L summary */}
        <div className={cn("text-xs font-mono font-semibold shrink-0", dayPnlPos ? "text-[#22C55E]" : "text-[#EF4444]")}>
          {fmtCurrency(strat.day_pnl)}
          <span className="text-[#475569] font-normal ml-1">({fmtPct(strat.day_pnl_pct)})</span>
        </div>

        {/* Expand chevron */}
        <div className="shrink-0 text-[#475569]">
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>
      </button>

      {/* ── Expanded body ──────────────────────────────────────────── */}
      {expanded && (
        <div className="border-t border-[#1E293B] px-4 py-4 space-y-4">

          {/* Market section */}
          <div>
            <div className="text-[10px] font-semibold text-[#475569] uppercase tracking-widest mb-2">Market</div>
            <div className="flex flex-wrap gap-2">
              {([
                { label: "SPY", val: spy },
                { label: "QQQ", val: qqq },
                { label: "IWM", val: iwm },
              ] as { label: string; val: number | null }[]).map(({ label, val }) => (
                <div key={label} className={cn("flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-mono font-semibold", pctBadgeCls(val))}>
                  <span className="text-[#94A3B8] font-medium">{label}</span>
                  <span>{fmtPct(val)}</span>
                </div>
              ))}
              {vix != null && (
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-mono font-semibold bg-[#1E293B] text-[#94A3B8]">
                  <span className="text-[#475569]">VIX</span>
                  <span>{vix.toFixed(1)}</span>
                </div>
              )}
              {breadth && (
                <div className={cn(
                  "flex items-center px-2.5 py-1 rounded-lg text-xs font-medium",
                  breadth === "advancing" ? "bg-[#22C55E]/10 text-[#22C55E]"
                    : breadth === "declining" ? "bg-[#EF4444]/10 text-[#EF4444]"
                    : "bg-[#F59E0B]/10 text-[#F59E0B]"
                )}>
                  {breadth.charAt(0).toUpperCase() + breadth.slice(1)}
                </div>
              )}
            </div>
          </div>

          {/* Strategy section */}
          <div>
            <div className="text-[10px] font-semibold text-[#475569] uppercase tracking-widest mb-2">Strategy</div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#94A3B8]">
              <span>
                <span className="text-[#F8FAFC] font-semibold">{strat.new_entries}</span> new {strat.new_entries === 1 ? "entry" : "entries"}
              </span>
              <span className="text-[#334155]">·</span>
              <span>
                <span className="text-[#F8FAFC] font-semibold">{strat.exits}</span> {strat.exits === 1 ? "exit" : "exits"}
              </span>
              <span className="text-[#334155]">·</span>
              <span>
                <span className="text-[#F8FAFC] font-semibold">{strat.open_positions}</span> open positions
              </span>
              <span className="text-[#334155]">·</span>
              <span className={cn("font-semibold font-mono", dayPnlPos ? "text-[#22C55E]" : "text-[#EF4444]")}>
                {fmtCurrency(strat.day_pnl)} ({fmtPct(strat.day_pnl_pct)}) day
              </span>
            </div>
          </div>

          {/* Narrative */}
          {narrative && (
            <div>
              <div className="text-[10px] font-semibold text-[#475569] uppercase tracking-widest mb-2">Recap</div>
              <p className="text-sm text-[#94A3B8] leading-relaxed">{narrative}</p>
            </div>
          )}

          {/* Top setups */}
          {top_setups.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-[#475569] uppercase tracking-widest mb-2">Top Setups</div>
              <div className="flex flex-wrap gap-1.5">
                {top_setups.map((s, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#1E293B] border border-[#334155] text-xs"
                  >
                    <span className="font-mono font-bold text-[#F8FAFC]">{s.symbol}</span>
                    <span className="text-[#475569]">·</span>
                    <span className="text-[#64748B]">{s.preset}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

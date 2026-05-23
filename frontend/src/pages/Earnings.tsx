import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getEarnings } from "@/api/market";
import { formatCurrency, cn } from "@/lib/utils";
import { Calendar, ChevronRight, TrendingUp, TrendingDown } from "lucide-react";
import SectorPill from "@/components/ui/SectorPill";
import { COMPANY_INFO } from "@/data/companyInfo";

function groupByDate(events: any[]) {
  const map = new Map<string, any[]>();
  for (const e of events) {
    const d = e.date ?? "Unknown";
    if (!map.has(d)) map.set(d, []);
    map.get(d)!.push(e);
  }
  return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]));
}

function formatDate(dateStr: string) {
  try {
    const d = new Date(dateStr + "T12:00:00");
    return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  } catch {
    return dateStr;
  }
}

function isToday(dateStr: string) {
  const today = new Date().toISOString().slice(0, 10);
  return dateStr === today;
}

function isTomorrow(dateStr: string) {
  const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  return dateStr === tomorrow;
}

function EarningsRow({ event }: { event: any }) {
  const navigate = useNavigate();
  const hasEps = event.eps_estimate != null;
  const hasBeat =
    event.eps_actual != null && event.eps_estimate != null
      ? event.eps_actual >= event.eps_estimate
      : null;

  return (
    <div
      className="flex items-center px-4 py-3 min-h-[44px] border-b border-[#1E293B]/50 last:border-0 hover:bg-[#1E293B]/40 cursor-pointer group"
      onClick={() => navigate(`/research?symbol=${event.symbol}`)}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold text-white">{event.symbol}</span>
          <SectorPill symbol={event.symbol} />
          {event.time && (
            <span className="text-[10px] text-[#475569] border border-[#334155] px-1.5 py-px rounded">
              {event.time === "bmo" ? "Pre-market" : event.time === "amc" ? "After-hours" : event.time}
            </span>
          )}
        </div>
        {COMPANY_INFO[event.symbol] && (
          <div className="text-xs text-[#475569] mt-0.5">{COMPANY_INFO[event.symbol].name}</div>
        )}
      </div>

      <div className="flex items-center gap-4 text-sm shrink-0">
        {hasEps ? (
          <>
            <div className="text-right hidden sm:block">
              <div className="text-[10px] text-[#475569] uppercase tracking-wide">Est. EPS</div>
              <div className="text-[#94A3B8] font-mono">{event.eps_estimate?.toFixed(2) ?? "—"}</div>
            </div>
            {event.eps_actual != null && (
              <div className="text-right">
                <div className="text-[10px] text-[#475569] uppercase tracking-wide">Actual</div>
                <div className={cn("font-mono font-semibold", hasBeat ? "text-[#22C55E]" : "text-[#EF4444]")}>
                  {event.eps_actual.toFixed(2)}
                  {hasBeat != null && (
                    <span className="ml-1">{hasBeat ? "↑" : "↓"}</span>
                  )}
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="text-[#475569] text-xs hidden sm:block">No estimates</div>
        )}
        <ChevronRight size={14} className="text-[#475569] group-hover:text-[#94A3B8] transition-colors" />
      </div>
    </div>
  );
}

export default function Earnings() {
  const [daysAhead, setDaysAhead] = useState(14);

  const { data: events = [], isLoading } = useQuery({
    queryKey: ["earnings", daysAhead],
    queryFn: () => getEarnings(daysAhead),
    staleTime: 300_000,
  });

  const grouped = groupByDate(events);

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white">Earnings Calendar</h1>
          <p className="text-[#475569] text-sm mt-0.5">Upcoming earnings reports</p>
        </div>
        <div className="flex items-center gap-1 bg-[#0F172A] border border-[#334155] rounded-lg p-1">
          {[7, 14, 30].map((d) => (
            <button
              key={d}
              onClick={() => setDaysAhead(d)}
              className={cn(
                "px-3 py-1 rounded text-sm transition-colors",
                daysAhead === d ? "bg-white text-black font-semibold" : "text-[#475569] hover:text-[#F8FAFC]"
              )}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="bg-[#0F172A] border border-[#1E293B] rounded-xl overflow-hidden">
              <div className="h-8 bg-[#1E293B] animate-pulse" />
              {[...Array(3)].map((__, j) => (
                <div key={j} className="h-14 border-t border-[#1E293B] bg-[#0F172A] animate-pulse" />
              ))}
            </div>
          ))}
        </div>
      ) : grouped.length === 0 ? (
        <div className="text-center py-16">
          <Calendar size={32} className="text-[#475569] mx-auto mb-3" />
          <p className="text-[#475569]">No earnings events in the next {daysAhead} days</p>
        </div>
      ) : (
        <div className="space-y-4">
          {grouped.map(([date, dayEvents]) => (
            <div key={date} className="bg-[#0F172A] border border-[#1E293B] rounded-xl overflow-hidden">
              <div className="px-4 py-2 bg-[#1E293B]/50 border-b border-[#1E293B] flex items-center gap-2">
                <Calendar size={13} className="text-[#475569]" />
                <span className="text-sm font-semibold text-white">{formatDate(date)}</span>
                {isToday(date) && (
                  <span className="text-[10px] font-bold text-[#22C55E] bg-[#22C55E]/10 border border-emerald-400/20 px-1.5 py-px rounded-full">TODAY</span>
                )}
                {isTomorrow(date) && (
                  <span className="text-[10px] font-bold text-blue-400 bg-blue-400/10 border border-blue-400/20 px-1.5 py-px rounded-full">TOMORROW</span>
                )}
                <span className="ml-auto text-xs text-[#475569]">{dayEvents.length} companies</span>
              </div>
              {dayEvents.map((e: any) => (
                <EarningsRow key={e.symbol} event={e} />
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

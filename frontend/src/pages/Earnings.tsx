import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getEarnings, getImpliedMove, getEarningsHistory } from "@/api/market";
import type { EarningsHistoryEntry } from "@/api/market";
import { cn } from "@/lib/utils";
import { Calendar, ChevronRight, ChevronDown, Bot } from "lucide-react";
import SectorPill from "@/components/ui/SectorPill";
import { COMPANY_INFO } from "@/data/companyInfo";
import AskAIDrawer from "@/components/ui/AskAIDrawer";

// ─── helpers ────────────────────────────────────────────────────────────────

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

/** True if US equity market is currently open (9:30–16:00 ET on weekdays). */
function isMarketOpen(): boolean {
  const now = new Date();
  // Convert to Eastern time
  const etStr = now.toLocaleString("en-US", { timeZone: "America/New_York" });
  const et = new Date(etStr);
  const day = et.getDay(); // 0=Sun 6=Sat
  if (day === 0 || day === 6) return false;
  const h = et.getHours();
  const m = et.getMinutes();
  const mins = h * 60 + m;
  return mins >= 9 * 60 + 30 && mins < 16 * 60;
}

/** True if Eastern time is before 9:30 am today (market hasn't opened). */
function isPreMarket(): boolean {
  const now = new Date();
  const etStr = now.toLocaleString("en-US", { timeZone: "America/New_York" });
  const et = new Date(etStr);
  const day = et.getDay();
  if (day === 0 || day === 6) return false;
  const mins = et.getHours() * 60 + et.getMinutes();
  return mins < 9 * 60 + 30;
}

// ─── Implied Move Badge (used inside rows) ───────────────────────────────────

function ImpliedMoveBadge({ symbol }: { symbol: string }) {
  const { data } = useQuery({
    queryKey: ["implied-move", symbol],
    queryFn: () => getImpliedMove(symbol),
    staleTime: 3_600_000,
  });

  if (!data?.implied_move_pct) return null;

  return (
    <span className="text-[10px] font-mono font-semibold text-amber-400 bg-amber-400/10 border border-amber-400/20 px-1.5 py-px rounded">
      ±{data.implied_move_pct}%
    </span>
  );
}

// ─── Earnings Surprise History Chart ────────────────────────────────────────

function SurpriseBar({ entry }: { entry: EarningsHistoryEntry }) {
  const beat = (entry.surprise_pct ?? 0) >= 0;
  const absVal = Math.abs(entry.surprise_pct ?? 0);
  // Clamp bar width: max 100% at ±50% surprise
  const widthPct = Math.min(100, (absVal / 50) * 100);

  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="w-20 text-right text-[10px] text-[var(--text-tertiary)] shrink-0 truncate">{entry.period}</div>
      <div className="flex-1 flex items-center gap-1.5">
        <div className="flex-1 h-4 bg-[var(--bg-elevated-2)] rounded-sm overflow-hidden relative">
          {entry.surprise_pct != null ? (
            <div
              className={cn("h-full rounded-sm", beat ? "bg-emerald-500/70" : "bg-red-500/70")}
              style={{ width: `${widthPct}%` }}
            />
          ) : (
            <div className="h-full w-full bg-[var(--border-subtle)]" />
          )}
        </div>
        <span className={cn("text-[10px] font-mono w-14 shrink-0", entry.surprise_pct == null ? "text-[var(--text-tertiary)]" : beat ? "text-emerald-400" : "text-red-400")}>
          {entry.surprise_pct != null
            ? `${beat ? "+" : ""}${entry.surprise_pct.toFixed(1)}%`
            : "N/A"}
        </span>
      </div>
    </div>
  );
}

function EarningsSurpriseHistory({ symbol }: { symbol: string }) {
  const navigate = useNavigate();
  const { data: history = [], isLoading } = useQuery({
    queryKey: ["earnings-history", symbol],
    queryFn: () => getEarningsHistory(symbol),
    staleTime: 3_600_000,
  });

  if (isLoading) {
    return (
      <div className="px-4 py-3 border-t border-[var(--border-subtle)]/50 space-y-1.5">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-4 bg-[var(--bg-elevated-2)] animate-pulse rounded" />
        ))}
      </div>
    );
  }

  return (
    <div className="px-4 py-3 border-t border-[var(--border-subtle)]/50 space-y-2 bg-[var(--bg-elevated-2)]/30">
      <div className="text-[10px] uppercase tracking-widest text-[var(--text-tertiary)] font-semibold mb-1">
        EPS Surprise — Last 4 Quarters
      </div>
      {history.length === 0 ? (
        <p className="text-xs text-[var(--text-tertiary)]">No historical data available</p>
      ) : (
        <div className="space-y-1.5">
          {history.map((entry) => (
            <SurpriseBar key={entry.period} entry={entry} />
          ))}
        </div>
      )}
      <button
        onClick={() => navigate(`/research?symbol=${symbol}`)}
        className="mt-2 text-xs text-blue-400 hover:text-blue-300 font-semibold transition-colors"
      >
        View Research →
      </button>
    </div>
  );
}

// ─── EarningsRow ─────────────────────────────────────────────────────────────

function EarningsRow({ event, isPast }: { event: any; isPast: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const hasEps = event.eps_estimate != null;
  const hasBeat =
    event.eps_actual != null && event.eps_estimate != null
      ? event.eps_actual >= event.eps_estimate
      : null;

  return (
    <div className="border-b border-[var(--border-subtle)]/50 last:border-0">
      <div
        className="flex items-center px-4 py-3 min-h-[44px] hover:bg-[var(--bg-elevated-2)]/40 cursor-pointer group"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono font-bold text-[var(--text-primary)]">{event.symbol}</span>
            <SectorPill symbol={event.symbol} />
            {event.time && (
              <span className="text-[10px] text-[var(--text-tertiary)] border border-[var(--border-emphasis)] px-1.5 py-px rounded">
                {event.time === "bmo" ? "Pre-market" : event.time === "amc" ? "After-hours" : event.time}
              </span>
            )}
            {!isPast && <ImpliedMoveBadge symbol={event.symbol} />}
          </div>
          {COMPANY_INFO[event.symbol] && (
            <div className="text-xs text-[var(--text-tertiary)] mt-0.5">{COMPANY_INFO[event.symbol].name}</div>
          )}
        </div>

        <div className="flex items-center gap-4 text-sm shrink-0">
          {hasEps ? (
            <>
              <div className="text-right hidden sm:block">
                <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wide">Est. EPS</div>
                <div className="text-[var(--text-secondary)] font-mono">{event.eps_estimate?.toFixed(2) ?? "—"}</div>
              </div>
              {event.eps_actual != null && (
                <div className="text-right">
                  <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wide">Actual</div>
                  <div className={cn("font-mono font-semibold", hasBeat ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                    {event.eps_actual.toFixed(2)}
                    {hasBeat != null && (
                      <span className="ml-1">{hasBeat ? "↑" : "↓"}</span>
                    )}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="text-[var(--text-tertiary)] text-xs hidden sm:block">No estimates</div>
          )}
          {expanded
            ? <ChevronDown size={14} className="text-[var(--text-tertiary)] transition-colors" />
            : <ChevronRight size={14} className="text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)] transition-colors" />
          }
        </div>
      </div>

      {expanded && <EarningsSurpriseHistory symbol={event.symbol} />}
    </div>
  );
}

// ─── Today's Spotlight Card ──────────────────────────────────────────────────

function SpotlightCard({ event }: { event: any }) {
  const navigate = useNavigate();
  const hasEps = event.eps_estimate != null;
  const hasBeat =
    event.eps_actual != null && event.eps_estimate != null
      ? event.eps_actual >= event.eps_estimate
      : null;

  const marketOpen = isMarketOpen();
  const preMarket = isPreMarket();

  // Show LIVE badge: market is open and it's AMC, OR pre-market and it's BMO
  const showLive =
    (marketOpen && event.time === "amc") ||
    (preMarket && event.time === "bmo");

  return (
    <div
      className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 cursor-pointer hover:border-[var(--border-emphasis)] transition-colors space-y-2"
      onClick={() => navigate(`/research?symbol=${event.symbol}`)}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono font-bold text-lg text-[var(--text-primary)]">{event.symbol}</span>
            {showLive && (
              <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400 bg-emerald-400/10 border border-emerald-400/20 px-1.5 py-px rounded-full">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                LIVE
              </span>
            )}
          </div>
          {COMPANY_INFO[event.symbol] && (
            <div className="text-xs text-[var(--text-tertiary)] mt-0.5 truncate">{COMPANY_INFO[event.symbol].name}</div>
          )}
        </div>
        {event.time && (
          <span className="text-[10px] text-[var(--text-tertiary)] border border-[var(--border-emphasis)] px-1.5 py-px rounded shrink-0">
            {event.time === "bmo" ? "Pre-market" : event.time === "amc" ? "After-hours" : event.time}
          </span>
        )}
      </div>

      {hasEps && (
        <div className="flex items-center gap-3 pt-1">
          <div>
            <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wide">Est. EPS</div>
            <div className="font-mono text-sm text-[var(--text-secondary)]">{event.eps_estimate?.toFixed(2) ?? "—"}</div>
          </div>
          {event.eps_actual != null && (
            <>
              <div className="w-px h-8 bg-[var(--border-subtle)]" />
              <div>
                <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wide">Actual</div>
                <div className={cn("font-mono text-sm font-semibold flex items-center gap-1", hasBeat ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                  {event.eps_actual.toFixed(2)}
                  <span className="text-xs px-1 py-px rounded font-bold" style={{ background: hasBeat ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)" }}>
                    {hasBeat ? "BEAT" : "MISS"}
                  </span>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      <div className="flex items-center gap-2 pt-1">
        <SectorPill symbol={event.symbol} />
        <ImpliedMoveBadge symbol={event.symbol} />
      </div>
    </div>
  );
}

function TodaySpotlight({ events }: { events: any[] }) {
  return (
    <div className="bg-[var(--bg-elevated)] border border-emerald-500/30 rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 bg-emerald-500/10 border-b border-emerald-500/20 flex items-center gap-2">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
        <span className="text-sm font-bold text-emerald-400">Today's Earnings</span>
        <span className="ml-auto text-xs text-[var(--text-tertiary)]">{events.length} {events.length === 1 ? "company" : "companies"}</span>
      </div>
      <div className="p-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
        {events.map((e: any) => (
          <SpotlightCard key={e.symbol} event={e} />
        ))}
      </div>
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function Earnings() {
  const [daysAhead, setDaysAhead] = useState(14);
  const [aiOpen, setAiOpen] = useState(false);

  const { data: events = [], isLoading } = useQuery({
    queryKey: ["earnings", daysAhead],
    queryFn: () => getEarnings(daysAhead),
    staleTime: 300_000,
  });

  const todayEvents = events.filter((e: any) => isToday(e.date));
  const grouped = groupByDate(events);

  const today = new Date().toISOString().slice(0, 10);

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)]">Earnings Calendar</h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Upcoming earnings reports</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setAiOpen(true)}
            className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
          >
            <Bot size={12} /> Ask AI
          </button>
          <div className="flex items-center gap-1 bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-lg p-1">
            {[7, 14, 30].map((d) => (
              <button
                key={d}
                onClick={() => setDaysAhead(d)}
                className={cn(
                  "px-3 py-1 rounded text-sm transition-colors",
                  daysAhead === d ? "bg-white text-black font-semibold" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
                )}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
              <div className="h-8 bg-[var(--bg-elevated-2)] animate-pulse" />
              {[...Array(3)].map((__, j) => (
                <div key={j} className="h-14 border-t border-[var(--border-subtle)] bg-[var(--bg-elevated)] animate-pulse" />
              ))}
            </div>
          ))}
        </div>
      ) : grouped.length === 0 ? (
        <div className="text-center py-16">
          <Calendar size={32} className="text-[var(--text-tertiary)] mx-auto mb-3" />
          <p className="text-[var(--text-tertiary)]">No earnings events in the next {daysAhead} days</p>
        </div>
      ) : (
        <div className="space-y-4">
          {todayEvents.length > 0 && <TodaySpotlight events={todayEvents} />}

          {grouped.map(([date, dayEvents]) => (
            <div key={date} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
              <div className="px-4 py-2 bg-[var(--bg-elevated-2)]/50 border-b border-[var(--border-subtle)] flex items-center gap-2">
                <Calendar size={13} className="text-[var(--text-tertiary)]" />
                <span className="text-sm font-semibold text-[var(--text-primary)]">{formatDate(date)}</span>
                {isToday(date) && (
                  <span className="text-[10px] font-bold text-[var(--accent-positive)] bg-[var(--accent-positive-bg)] border border-emerald-400/20 px-1.5 py-px rounded-full">TODAY</span>
                )}
                {isTomorrow(date) && (
                  <span className="text-[10px] font-bold text-blue-400 bg-blue-400/10 border border-blue-400/20 px-1.5 py-px rounded-full">TOMORROW</span>
                )}
                <span className="ml-auto text-xs text-[var(--text-tertiary)]">{dayEvents.length} companies</span>
              </div>
              {dayEvents.map((e: any) => (
                <EarningsRow key={e.symbol} event={e} isPast={e.date < today} />
              ))}
            </div>
          ))}
        </div>
      )}

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title="Ask BMG about Earnings"
        context="Earnings Calendar"
        suggestedQuestions={[
          "Which earnings reports look most interesting this week?",
          "What are analysts expecting from major upcoming reporters?",
          "Explain implied move from the options market",
          "Which sectors report earnings most this week?",
          "What should I watch for in upcoming earnings calls?",
        ]}
      />
    </div>
  );
}

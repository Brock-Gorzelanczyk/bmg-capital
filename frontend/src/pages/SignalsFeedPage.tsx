import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { getRecentSignals } from "@/api/bots";
import { getSignals as getScoutSignals } from "@/api/scout";
import { getForgeSignals } from "@/api/forge";

// ── Unified shape ──────────────────────────────────────────────────────────────

type Source = "bot" | "scout" | "forge";

interface UnifiedSignal {
  key: string;
  source: Source;
  label: string;        // bot display name / forge bot name
  ticker: string;
  strategy: string;
  side: string;
  confidence: number;
  entry: number | null;
  stop: number | null;
  target: number | null;
  reason: string;
  ts: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtPrice(v: number | null | undefined) {
  if (v == null) return "—";
  if (v >= 1000) return `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  if (v >= 1) return `$${v.toFixed(2)}`;
  return `$${v.toFixed(6)}`;
}

function ago(ts: string) {
  const diff = Date.now() - new Date(ts).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

const SOURCE_META: Record<Source, { label: string; dot: string; badge: string }> = {
  bot:   { label: "Bot",   dot: "bg-teal-400",   badge: "bg-teal-500/10 border-teal-500/20 text-teal-400" },
  scout: { label: "Scout", dot: "bg-violet-400",  badge: "bg-violet-500/10 border-violet-500/20 text-violet-400" },
  forge: { label: "Forge", dot: "bg-orange-400",  badge: "bg-orange-500/10 border-orange-500/20 text-orange-400" },
};

function sideClass(side: string) {
  if (side === "buy" || side === "long" || side === "cover") return "text-emerald-400";
  if (side === "sell" || side === "short") return "text-red-400";
  return "text-zinc-400";
}

// ── Signal row ─────────────────────────────────────────────────────────────────

function SignalRow({ sig }: { sig: UnifiedSignal }) {
  const meta = SOURCE_META[sig.source];
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <div
        className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/40 transition-colors cursor-pointer border-b border-zinc-800/50 last:border-0"
        onClick={() => setExpanded((v) => !v)}
      >
        {/* Source badge */}
        <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded border flex-shrink-0", meta.badge)}>
          {meta.label.toUpperCase()}
        </span>

        {/* Side */}
        <span className={cn("text-xs font-bold w-10 flex-shrink-0 uppercase", sideClass(sig.side))}>
          {sig.side}
        </span>

        {/* Ticker */}
        <span className="text-xs font-mono font-semibold text-white w-20 flex-shrink-0 truncate">
          {sig.ticker}
        </span>

        {/* Strategy / bot */}
        <div className="flex-1 min-w-0">
          <p className="text-xs text-white truncate">{sig.strategy}</p>
          <p className="text-[10px] text-zinc-600 truncate">{sig.label}</p>
        </div>

        {/* Confidence */}
        <span className="text-xs font-semibold text-white w-10 text-right flex-shrink-0">
          {Math.round(sig.confidence * 100)}%
        </span>

        {/* Entry */}
        <span className="text-xs text-zinc-400 w-20 text-right flex-shrink-0 hidden sm:block">
          {fmtPrice(sig.entry)}
        </span>

        {/* Timestamp */}
        <span className="text-xs text-zinc-600 w-14 text-right flex-shrink-0">{ago(sig.ts)}</span>

        {/* Expand chevron */}
        <span className="text-zinc-700 text-xs flex-shrink-0">{expanded ? "▲" : "▼"}</span>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 py-3 bg-zinc-900/60 border-b border-zinc-800 grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div>
            <p className="text-[10px] text-zinc-600 uppercase mb-0.5">Entry</p>
            <p className="text-sm font-semibold text-white">{fmtPrice(sig.entry)}</p>
          </div>
          <div>
            <p className="text-[10px] text-zinc-600 uppercase mb-0.5">Stop</p>
            <p className="text-sm font-semibold text-red-400">{fmtPrice(sig.stop)}</p>
          </div>
          <div>
            <p className="text-[10px] text-zinc-600 uppercase mb-0.5">Target</p>
            <p className="text-sm font-semibold text-emerald-400">{fmtPrice(sig.target)}</p>
          </div>
          <div>
            <p className="text-[10px] text-zinc-600 uppercase mb-0.5">R/R</p>
            <p className="text-sm font-semibold text-white">
              {sig.entry && sig.stop && sig.target
                ? `1 : ${Math.abs((sig.target - sig.entry) / (sig.entry - sig.stop)).toFixed(1)}`
                : "—"}
            </p>
          </div>
          {sig.reason && (
            <div className="col-span-2 sm:col-span-4">
              <p className="text-[10px] text-zinc-600 uppercase mb-0.5">Reason</p>
              <p className="text-xs text-zinc-400 leading-relaxed">{sig.reason}</p>
            </div>
          )}
        </div>
      )}
    </>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

type SourceFilter = "all" | Source;
type SideFilter   = "all" | "long" | "short";

export default function SignalsFeedPage() {
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [sideFilter, setSideFilter]     = useState<SideFilter>("all");
  const [search, setSearch]             = useState("");

  const { data: botData,   isLoading: botLoading   } = useQuery({
    queryKey: ["bot-signals-feed", 100],
    queryFn:  () => getRecentSignals(100),
    staleTime: 30_000,
    retry: 0,
    refetchInterval: 60_000,
  });
  const { data: scoutData, isLoading: scoutLoading } = useQuery({
    queryKey: ["scout-signals"],
    queryFn:  getScoutSignals,
    staleTime: 30_000,
    retry: 0,
    refetchInterval: 60_000,
  });
  const { data: forgeData, isLoading: forgeLoading } = useQuery({
    queryKey: ["forge-signals"],
    queryFn:  getForgeSignals,
    staleTime: 30_000,
    retry: 0,
    refetchInterval: 60_000,
  });

  const isLoading = botLoading || scoutLoading || forgeLoading;

  const unified = useMemo<UnifiedSignal[]>(() => {
    const out: UnifiedSignal[] = [];

    for (const s of botData?.signals ?? []) {
      out.push({
        key:        `bot-${s.id ?? s.ts}`,
        source:     "bot",
        label:      (s as any).bot_display || (s as any).bot_name || (s as any).bot || "",
        ticker:     (s as any).symbol,
        strategy:   (s as any).strategy || "",
        side:       s.side,
        confidence: s.confidence,
        entry:      (s as any).entry_price ?? null,
        stop:       (s as any).stop_price  ?? null,
        target:     (s as any).target_price ?? null,
        reason:     s.reason || "",
        ts:         (s as any).ts || "",
      });
    }
    for (const s of scoutData?.signals ?? []) {
      out.push({
        key:        `scout-${s.id}`,
        source:     "scout",
        label:      "Strategy Scout",
        ticker:     s.ticker,
        strategy:   s.display_name,
        side:       s.side,
        confidence: s.confidence,
        entry:      s.entry_price,
        stop:       s.stop_price,
        target:     s.target_price,
        reason:     s.reason || "",
        ts:         s.created_at,
      });
    }
    for (const s of forgeData?.signals ?? []) {
      out.push({
        key:        `forge-${s.id}`,
        source:     "forge",
        label:      s.bot_name,
        ticker:     s.ticker,
        strategy:   s.display_name,
        side:       s.side,
        confidence: s.confidence,
        entry:      s.entry_price,
        stop:       s.stop_price,
        target:     s.target_price,
        reason:     s.reason || "",
        ts:         s.created_at,
      });
    }

    return out.sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());
  }, [botData, scoutData, forgeData]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return unified.filter((s) => {
      if (sourceFilter !== "all" && s.source !== sourceFilter) return false;
      if (sideFilter === "long"  && !["buy","long","cover"].includes(s.side))  return false;
      if (sideFilter === "short" && !["sell","short"].includes(s.side)) return false;
      if (q && !s.ticker.toLowerCase().includes(q) && !s.strategy.toLowerCase().includes(q) && !s.label.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [unified, sourceFilter, sideFilter, search]);

  const counts: Record<Source, number> = { bot: 0, scout: 0, forge: 0 };
  for (const s of unified) counts[s.source]++;

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 pb-24 md:pb-6 space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest mb-0.5">
            // SIGNAL FEED
          </p>
          <h1 className="text-2xl font-bold text-white">My Signals</h1>
          <p className="text-zinc-500 text-sm mt-1">
            All signals across bots, Scout, and Forge — live, every 60 s.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-zinc-600 flex-wrap">
          {Object.entries(SOURCE_META).map(([src, meta]) => (
            <span key={src} className="flex items-center gap-1.5">
              <span className={cn("w-2 h-2 rounded-full", meta.dot)} />
              {meta.label}: {counts[src as Source]}
            </span>
          ))}
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex flex-col sm:flex-row gap-2">
        {/* Source filter */}
        <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1">
          {(["all", "bot", "scout", "forge"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSourceFilter(s)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors capitalize",
                sourceFilter === s
                  ? "bg-zinc-700 text-white"
                  : "text-zinc-500 hover:text-zinc-300"
              )}
            >
              {s === "all" ? `All (${unified.length})` : `${SOURCE_META[s].label} (${counts[s]})`}
            </button>
          ))}
        </div>

        {/* Side filter */}
        <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1">
          {(["all", "long", "short"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSideFilter(s)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors capitalize",
                sideFilter === s
                  ? "bg-zinc-700 text-white"
                  : "text-zinc-500 hover:text-zinc-300"
              )}
            >
              {s === "all" ? "Both" : s === "long" ? "Long" : "Short"}
            </button>
          ))}
        </div>

        {/* Ticker search */}
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search ticker or strategy…"
          className="flex-1 bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-zinc-600 transition-colors"
        />
      </div>

      {/* Feed table */}
      {isLoading ? (
        <div className="space-y-1">
          {[0,1,2,3,4].map((i) => (
            <div key={i} className="h-12 rounded-xl bg-zinc-900 border border-zinc-800 animate-pulse" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-12 text-center">
          <p className="text-zinc-400 font-semibold mb-1">No signals yet</p>
          <p className="text-zinc-600 text-sm">
            {unified.length === 0
              ? "Signals from bots, Scout, and Forge will appear here as they fire."
              : "No signals match the current filter."}
          </p>
          {unified.length === 0 && (
            <div className="flex justify-center gap-3 mt-4">
              <Link to="/strategy/scout" className="text-xs text-violet-400 hover:text-violet-300 transition-colors">
                Open Scout →
              </Link>
              <Link to="/strategy/forge" className="text-xs text-orange-400 hover:text-orange-300 transition-colors">
                Open Forge →
              </Link>
            </div>
          )}
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
          {/* Column headers */}
          <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800 bg-zinc-900/80">
            <span className="text-[10px] font-semibold text-zinc-600 uppercase w-12">Src</span>
            <span className="text-[10px] font-semibold text-zinc-600 uppercase w-10">Side</span>
            <span className="text-[10px] font-semibold text-zinc-600 uppercase w-20">Ticker</span>
            <span className="text-[10px] font-semibold text-zinc-600 uppercase flex-1">Strategy / Bot</span>
            <span className="text-[10px] font-semibold text-zinc-600 uppercase w-10 text-right">Conf</span>
            <span className="text-[10px] font-semibold text-zinc-600 uppercase w-20 text-right hidden sm:block">Entry</span>
            <span className="text-[10px] font-semibold text-zinc-600 uppercase w-14 text-right">When</span>
            <span className="w-3" />
          </div>
          {filtered.map((sig) => (
            <SignalRow key={sig.key} sig={sig} />
          ))}
        </div>
      )}

      <p className="text-xs text-zinc-700 text-center">
        Paper trading only. Not investment advice. Not a registered investment adviser.
      </p>
    </div>
  );
}

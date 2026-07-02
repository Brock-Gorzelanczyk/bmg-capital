import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Search, CheckCircle2, ChevronDown, ChevronUp, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { SectionLabel } from "@/components/design";
import { getBotLeaderboardRanking, type BotLeaderboardRow } from "@/api/performance";
import { listCandidateCatalog, getStrategyDescription, type CatalogCandidate, type StrategyDescription } from "@/api/candidates";

// ── Style / difficulty mappings ───────────────────────────────────────────────

const BOT_STYLE: Record<string, string> = {
  stock_swing:                 "Momentum",
  stock_day:                   "Momentum",
  stock_lt:                    "Trend",
  crypto_swing:                "Momentum",
  crypto_day:                  "Momentum",
  crypto_lt:                   "Trend",
  crypto_onchain:              "Event-Driven",
  crypto_quant_aggressive:     "Momentum",
  crypto_quant_mean_reversion: "Mean Reversion",
  crypto_quant_scalper:        "Mean Reversion",
  crypto_quant_alt_focus:      "Momentum",
  crypto_quant_scalp_1m:       "Momentum",
  crypto_dca_btc_eth:          "Trend",
  crypto_quant_universe_top6:  "Momentum",
  crypto_quant_defi_l2:        "Momentum",
  crypto_quant_meme_tier:      "Momentum",
  crypto_quant_10m:            "Momentum",
  crypto_quant_15m:            "Momentum",
  options_income:              "Carry",
  options_directional:         "Volatility",
};

const BOT_DIFFICULTY: Record<string, string> = {
  stock_swing: "Intermediate", stock_day: "Intermediate",
  stock_lt: "Beginner",        crypto_swing: "Intermediate",
  crypto_day: "Advanced",      crypto_lt: "Beginner",
  crypto_onchain: "Advanced",  crypto_quant_aggressive: "Advanced",
  crypto_quant_mean_reversion: "Advanced", crypto_quant_scalper: "Advanced",
  crypto_quant_alt_focus: "Advanced", crypto_quant_scalp_1m: "Advanced",
  crypto_dca_btc_eth: "Beginner",
  crypto_quant_universe_top6: "Advanced", crypto_quant_defi_l2: "Advanced",
  crypto_quant_meme_tier: "Advanced", crypto_quant_10m: "Advanced", crypto_quant_15m: "Advanced",
  options_income: "Intermediate", options_directional: "Advanced",
};

const STYLE_COLOR: Record<string, string> = {
  Momentum:       "bg-t-green/15 text-t-green border-t-green/30",
  "Mean Reversion": "bg-blue-500/15 text-blue-400 border-blue-500/30",
  Trend:          "bg-slate-500/15 text-slate-400 border-slate-500/30",
  Arbitrage:      "bg-purple-500/15 text-purple-400 border-purple-500/30",
  Volatility:     "bg-t-red/15 text-t-red border-t-red/30",
  Carry:          "bg-t-amber/15 text-t-amber border-t-amber/30",
  "Event-Driven": "bg-orange-500/15 text-orange-400 border-orange-500/30",
  "Cross-Asset":  "bg-teal-500/15 text-teal-400 border-teal-500/30",
  "Short Volatility": "bg-pink-500/15 text-pink-400 border-pink-500/30",
  Income:         "bg-t-amber/15 text-t-amber border-t-amber/30",
};

const AC_COLOR: Record<string, string> = {
  stocks: "bg-blue-500/10 text-blue-400 border-blue-500/25",
  equity: "bg-blue-500/10 text-blue-400 border-blue-500/25",
  crypto: "bg-t-green/10 text-t-green border-t-green/25",
  options: "bg-purple-500/10 text-purple-400 border-purple-500/25",
  multi:  "bg-teal-500/10 text-teal-400 border-teal-500/25",
};

const DIFFICULTY_COLOR: Record<string, string> = {
  Beginner:     "bg-lime-500/15 text-lime-400 border-lime-500/30",
  Intermediate: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  Advanced:     "bg-t-red/15 text-t-red border-t-red/30",
};

const _STYLE_NORM: Record<string, string> = {
  MOMENTUM:       "Momentum",
  MEAN_REVERSION: "Mean Reversion",
  TREND:          "Trend",
  ARBITRAGE:      "Arbitrage",
  VOLATILITY:     "Volatility",
  CARRY:          "Carry",
  EVENT_DRIVEN:   "Event-Driven",
  CROSS_ASSET:    "Cross-Asset",
  SHORT_VOLATILITY: "Short Volatility",
  INCOME:         "Income",
  QUALITY_MOMENTUM: "Momentum",
};
function normalizeStyle(raw: string | null | undefined): string {
  if (!raw) return "Other";
  if (raw in STYLE_COLOR) return raw;
  const key = raw.toUpperCase().replace(/[\s-]+/g, "_");
  return _STYLE_NORM[key] ?? raw;
}

const TIER_BADGE: Record<string, string> = {
  T3: "text-t-green border-t-green/30 bg-t-green/10",
  T2: "text-t-cyan border-t-cyan/30 bg-t-cyan/10",
  T1: "text-t-amber border-t-amber/30 bg-t-amber/10",
  T0: "text-t-muted border-t-muted/30 bg-t-muted/10",
};

const STATE_COLOR: Record<string, string> = {
  CANDIDATE:       "text-t-muted bg-t-bg2 border-t-dim",
  BACKTEST_QUEUED: "text-t-amber bg-t-amber/10 border-t-amber/30",
  BACKTEST_DONE:   "text-blue-400 bg-blue-400/10 border-blue-400/30",
  WFA_QUEUED:      "text-t-amber bg-t-amber/10 border-t-amber/30",
  WFA_DONE:        "text-purple-400 bg-purple-400/10 border-purple-400/30",
  SHADOW_PAPER:    "text-t-cyan bg-t-cyan/10 border-t-cyan/30",
  PROMOTED:        "text-t-green bg-t-green/10 border-t-green/30",
  RETIRED:         "text-t-red bg-t-red/10 border-t-red/30",
};

// ── Shared description panel ──────────────────────────────────────────────────

function DescRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[90px_1fr] gap-x-3 items-start py-1 border-b border-t-dim/40 last:border-0">
      <span className="text-[10px] text-t-gdim font-mono-t uppercase tracking-widest pt-0.5 shrink-0">
        {label}
      </span>
      <span className="text-xs text-t-body font-ui-t leading-relaxed">{value}</span>
    </div>
  );
}

function DescriptionPanel({
  id,
  assetClass,
  onScout,
}: {
  id: string;
  assetClass?: string;
  onScout?: () => void;
}) {
  const { data, isLoading, isError } = useQuery<StrategyDescription>({
    queryKey: ["strategy-desc", id],
    queryFn: () => getStrategyDescription(id),
    staleTime: Infinity,
    retry: 1,
  });

  if (isLoading) {
    return (
      <div className="mt-3 pt-3 border-t border-t-dim space-y-1.5 animate-pulse">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-3 bg-t-bg2 rounded w-full" />
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="mt-3 pt-3 border-t border-t-dim text-xs text-t-muted font-mono-t">
        Description not available.
      </div>
    );
  }

  return (
    <div className="mt-3 pt-3 border-t border-t-dim space-y-0.5">
      {/* Asset class badge */}
      <div className="flex flex-wrap gap-1.5 mb-2">
        <span className={cn(
          "text-[10px] px-2 py-0.5 rounded-full border font-bold font-mono-t",
          AC_COLOR[data.asset_class?.toLowerCase()] ?? "bg-t-bg2 text-t-muted border-t-dim"
        )}>
          {data.asset_class?.toUpperCase()}
        </span>
        {data.cadence && (
          <span className="text-[10px] px-2 py-0.5 rounded-full border font-mono-t text-t-muted border-t-dim bg-t-bg0">
            {data.cadence}
          </span>
        )}
      </div>

      <DescRow label="Thesis" value={data.thesis} />
      {data.entry_rule && <DescRow label="Entry" value={data.entry_rule} />}
      {data.exit_rule && <DescRow label="Exit" value={data.exit_rule} />}
      {data.risk && <DescRow label="Risk" value={data.risk} />}
      {data.works_best_in && <DescRow label="Best in" value={data.works_best_in} />}
      {data.avoid_in && <DescRow label="Avoid in" value={data.avoid_in} />}
      {data.academic_source && <DescRow label="Source" value={data.academic_source} />}

      {onScout && (
        <button
          onClick={(e) => { e.stopPropagation(); onScout(); }}
          className="mt-2 flex items-center gap-1 text-[11px] font-mono-t text-t-green border border-t-green/30 bg-t-green/10 px-3 py-1 rounded-lg hover:bg-t-green/20 transition-colors"
        >
          Try in Scout <ArrowUpRight size={10} />
        </button>
      )}
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Metric({ label, value, tag }: { label: string; value: string; tag?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[9px] text-t-gdim font-mono-t uppercase tracking-widest">{label}</span>
      <span className="text-sm font-bold text-t-hi font-mono-t tabular-nums">{value}</span>
      {tag && <span className="text-[9px] text-t-gdim font-mono-t">({tag})</span>}
    </div>
  );
}

function BotCard({
  row,
  expanded,
  onToggle,
  onNavigate,
  onScout,
}: {
  row: BotLeaderboardRow;
  expanded: boolean;
  onToggle: () => void;
  onNavigate: () => void;
  onScout: () => void;
}) {
  const style = BOT_STYLE[row.bot_id] ?? "Other";
  const difficulty = BOT_DIFFICULTY[row.bot_id] ?? "Intermediate";
  const isVerified = row.tier === "T2" || row.tier === "T3";
  const hasLiveData = row.trades_count > 0;

  return (
    <div
      className={cn(
        "bg-t-bg1 border rounded-2xl p-5 text-left transition-all duration-150 space-y-3 w-full",
        expanded ? "border-t-mid bg-t-bg2/30" : "border-t-dim hover:border-t-mid hover:bg-t-bg2/30"
      )}
    >
      {/* Header row — name + expand toggle */}
      <div
        className="flex items-start justify-between gap-2 cursor-pointer"
        onClick={onToggle}
      >
        <div className="min-w-0">
          <p className="text-t-hi font-semibold text-sm leading-tight font-ui-t truncate">{row.strategy_name}</p>
          <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded-full border mt-1 inline-block font-mono-t", TIER_BADGE[row.tier] ?? TIER_BADGE.T0)}>
            {row.tier}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isVerified && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-t-green/10 border border-t-green/30 text-[10px] font-bold text-t-green font-mono-t whitespace-nowrap">
              <CheckCircle2 size={10} /> VERIFIED
            </span>
          )}
          {expanded
            ? <ChevronUp size={14} className="text-t-muted" />
            : <ChevronDown size={14} className="text-t-muted" />}
        </div>
      </div>

      <span className={cn("text-[10px] px-2 py-0.5 rounded-full border font-bold font-mono-t", STYLE_COLOR[style] ?? "bg-t-bg2 text-t-muted border-t-dim")}>
        {style}
      </span>

      <div className="grid grid-cols-3 gap-2">
        {hasLiveData ? (
          <>
            <Metric label="SHARPE" value={row.sharpe_30d != null ? row.sharpe_30d.toFixed(2) : "—"} tag="live" />
            <Metric label="WIN" value={row.win_rate != null ? `${(row.win_rate * 100).toFixed(0)}%` : "—"} tag="live" />
            <Metric label="MAX DD" value={row.max_drawdown_pct != null ? `${(row.max_drawdown_pct * 100).toFixed(1)}%` : "—"} tag="live" />
          </>
        ) : (
          <div className="col-span-3 text-t-gdim text-xs font-mono-t">No live data yet</div>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 pt-1 border-t border-t-dim">
        <span className={cn("text-[10px] px-1.5 py-0.5 rounded border font-mono-t font-bold", DIFFICULTY_COLOR[difficulty])}>
          {difficulty}
        </span>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            <span className={cn("w-1.5 h-1.5 rounded-full", row.enabled ? "bg-t-green" : "bg-t-muted")} />
            <span className="text-[10px] text-t-muted font-mono-t">
              {row.enabled
                ? `LIVE · ${row.days_live}d deployed`
                : (row.paused_reason === "admin_lock" || row.paused_reason === "health_halt" || row.is_admin_locked)
                  ? "DISABLED · frozen"
                  : `OFF · ${row.days_live}d`}
            </span>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); onNavigate(); }}
            className="text-[10px] font-mono-t text-t-muted hover:text-t-mid2 border border-t-dim/50 px-2 py-0.5 rounded hover:border-t-mid transition-colors"
          >
            Detail →
          </button>
        </div>
      </div>

      {/* Expanded description */}
      {expanded && (
        <DescriptionPanel id={row.bot_id} onScout={onScout} />
      )}
    </div>
  );
}

function CandidateCard({
  c,
  expanded,
  onToggle,
  onNavigate,
  onScout,
}: {
  c: CatalogCandidate;
  expanded: boolean;
  onToggle: () => void;
  onNavigate: () => void;
  onScout: () => void;
}) {
  const style = normalizeStyle(c.style);

  return (
    <div
      className={cn(
        "bg-t-bg1 border rounded-2xl p-5 text-left transition-all duration-150 space-y-3 w-full",
        expanded ? "border-t-mid bg-t-bg2/30" : "border-t-dim hover:border-t-mid hover:bg-t-bg2/30"
      )}
    >
      <div
        className="flex items-start justify-between gap-2 cursor-pointer"
        onClick={onToggle}
      >
        <p className="text-t-hi font-semibold text-sm leading-tight font-ui-t truncate min-w-0">
          {c.name}
        </p>
        <div className="flex items-center gap-2 shrink-0">
          <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded-full border font-mono-t whitespace-nowrap", STATE_COLOR.CANDIDATE)}>
            CANDIDATE
          </span>
          {expanded
            ? <ChevronUp size={14} className="text-t-muted" />
            : <ChevronDown size={14} className="text-t-muted" />}
        </div>
      </div>

      <span className={cn("text-[10px] px-2 py-0.5 rounded-full border font-bold font-mono-t", STYLE_COLOR[style] ?? "bg-t-bg2 text-t-muted border-t-dim")}>
        {style}
      </span>

      <div className="grid grid-cols-1 gap-1">
        {c.description && (
          <div className="text-xs text-t-muted font-ui-t leading-relaxed line-clamp-2">
            {c.description}
          </div>
        )}
        {c.expected_sharpe && (
          <div className="text-[10px] text-t-gdim font-mono-t">Expected Sharpe: {c.expected_sharpe}</div>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 pt-1 border-t border-t-dim">
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-t-muted" />
          <span className="text-[10px] text-t-muted font-mono-t">NOT LIVE</span>
          {c.asset_class && (
            <span className={cn(
              "ml-1 text-[10px] px-1.5 py-0.5 rounded border font-mono-t font-bold",
              AC_COLOR[c.asset_class.toLowerCase()] ?? "bg-t-bg2 text-t-muted border-t-dim"
            )}>
              {c.asset_class.toUpperCase()}
            </span>
          )}
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onNavigate(); }}
          className="text-[10px] font-mono-t text-t-muted hover:text-t-mid2 border border-t-dim/50 px-2 py-0.5 rounded hover:border-t-mid transition-colors"
        >
          Detail →
        </button>
      </div>

      {/* Expanded description */}
      {expanded && (
        <DescriptionPanel id={c.file} onScout={onScout} />
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const AC_LABELS: Record<string, string> = {
  stock: "Stocks", crypto: "Crypto", options: "Options", quant: "Quant",
};

export default function StrategyLibraryPage() {
  const [filter, setFilter] = useState("All");
  const [statusFilter, setStatusFilter] = useState<"all" | "deployed" | "incubation">("all");
  const [acFilter, setAcFilter] = useState<"all" | "stock" | "crypto" | "options" | "quant">("all");
  const [sortBy, setSortBy] = useState<"name" | "sharpe" | "winrate">("name");
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const navigate = useNavigate();

  const { data: lbData, isLoading: botsLoading, isError: botsError } = useQuery({
    queryKey: ["bot-leaderboard-ranking", "pnl"],
    queryFn: () => getBotLeaderboardRanking("pnl"),
    staleTime: 120_000,
    retry: 1,
  });

  const { data: candidateData, isLoading: cLoading, isError: cError } = useQuery({
    queryKey: ["strategy-lab-candidates"],
    queryFn: listCandidateCatalog,
    staleTime: 120_000,
    retry: 1,
  });

  const bots = lbData?.strategies ?? [];
  const candidates = candidateData?.candidates ?? [];

  const nTotal    = bots.length + candidates.length;
  const nVerified = bots.filter((b) => b.tier === "T2" || b.tier === "T3").length;
  const nCandidates = candidates.length;

  const styleCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const b of bots) {
      const s = BOT_STYLE[b.bot_id] ?? "Other";
      counts[s] = (counts[s] ?? 0) + 1;
    }
    for (const c of candidates) {
      const s = normalizeStyle(c.style);
      counts[s] = (counts[s] ?? 0) + 1;
    }
    return counts;
  }, [bots, candidates]);

  const styleChips = ["All", ...Object.keys(styleCounts).sort()];

  const filtered = useMemo(() => {
    type Item =
      | { kind: "bot"; b: BotLeaderboardRow }
      | { kind: "candidate"; c: CatalogCandidate };

    let all: Item[] = [
      ...bots.map((b) => ({ kind: "bot" as const, b })),
      ...candidates.map((c) => ({ kind: "candidate" as const, c })),
    ];

    if (statusFilter === "deployed") all = all.filter((i) => i.kind === "bot");
    if (statusFilter === "incubation") all = all.filter((i) => i.kind === "candidate");

    if (acFilter !== "all") {
      all = all.filter((item) => {
        if (item.kind === "bot") return item.b.bot_id.includes(acFilter === "stock" ? "stock" : acFilter === "quant" ? "quant" : acFilter);
        return (item.c.asset_class ?? "").toLowerCase().startsWith(acFilter);
      });
    }

    const q = search.toLowerCase();
    const result = all.filter((item) => {
      if (filter !== "All") {
        const s = item.kind === "bot" ? BOT_STYLE[item.b.bot_id] : normalizeStyle(item.c.style);
        if (s !== filter) return false;
      }
      if (q) {
        const name = item.kind === "bot" ? item.b.strategy_name : item.c.name;
        if (!name.toLowerCase().includes(q)) return false;
      }
      return true;
    });

    if (sortBy === "sharpe") {
      result.sort((a, b) => {
        const sa = a.kind === "bot" ? (a.b.sharpe_30d ?? -99) : (a.c.expected_sharpe ? parseFloat(a.c.expected_sharpe) : -99);
        const sb = b.kind === "bot" ? (b.b.sharpe_30d ?? -99) : (b.c.expected_sharpe ? parseFloat(b.c.expected_sharpe) : -99);
        return sb - sa;
      });
    } else if (sortBy === "winrate") {
      result.sort((a, b) => {
        const wa = a.kind === "bot" ? (a.b.win_rate ?? 0) : 0;
        const wb = b.kind === "bot" ? (b.b.win_rate ?? 0) : 0;
        return wb - wa;
      });
    }

    return result;
  }, [bots, candidates, filter, statusFilter, acFilter, sortBy, search]);

  const isLoading = botsLoading || cLoading;
  const isError = botsError && cError;

  function handleToggle(id: string) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  return (
    <div className="min-h-screen bg-t-bg0 text-t-hi animate-page-in">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8 space-y-6">

        {/* Paper trading notice */}
        <div className="flex items-center gap-2 bg-t-amber/10 border border-t-amber/30 rounded-xl px-4 py-2.5 text-xs">
          <span className="w-1.5 h-1.5 rounded-full bg-t-amber shrink-0" />
          <span className="font-mono-t text-t-amber tracking-wide font-bold">
            PAPER TRADING ONLY — SIMULATED FILLS, NO REAL CAPITAL AT RISK
          </span>
        </div>

        {/* Header */}
        <div>
          <SectionLabel as="h1" className="text-base mb-1">// STRATEGY LIBRARY</SectionLabel>
          {!isLoading && !isError && (
            <p className="text-sm text-t-muted font-mono-t">
              {nTotal} strategies &middot; {nVerified} verified &amp; deployed &middot; {nCandidates} in incubation
              &nbsp;·&nbsp;
              <span className="text-t-gdim">click any card to expand description</span>
            </p>
          )}
        </div>

        {/* Filters row 1 — status + asset class + sort */}
        <div className="flex flex-wrap items-center gap-2">
          {(["all", "deployed", "incubation"] as const).map((v) => (
            <button key={v} onClick={() => setStatusFilter(v)}
              className={cn("px-3 py-1.5 rounded-lg font-mono-t text-[11px] uppercase tracking-widest transition-all",
                statusFilter === v ? "bg-t-green/20 text-t-green border border-t-green/40" : "bg-t-bg1 border border-t-dim text-t-muted hover:text-t-mid2"
              )}>
              {v === "all" ? "All" : v === "deployed" ? "Deployed" : "Incubation"}
            </button>
          ))}
          <span className="text-t-dim text-[10px] font-mono-t mx-1">|</span>
          {(["all", "stock", "crypto", "options", "quant"] as const).map((v) => (
            <button key={v} onClick={() => setAcFilter(v)}
              className={cn("px-3 py-1.5 rounded-lg font-mono-t text-[11px] uppercase tracking-widest transition-all",
                acFilter === v ? "bg-t-accent/20 text-t-accent border border-t-accent/40" : "bg-t-bg1 border border-t-dim text-t-muted hover:text-t-mid2"
              )}>
              {v === "all" ? "All Classes" : AC_LABELS[v] ?? v}
            </button>
          ))}
          <span className="text-t-dim text-[10px] font-mono-t mx-1">|</span>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
            className="bg-t-bg1 border border-t-dim rounded-lg px-3 py-1.5 text-[11px] font-mono-t text-t-muted outline-none cursor-pointer">
            <option value="name">Sort: Name</option>
            <option value="sharpe">Sort: Sharpe</option>
            <option value="winrate">Sort: Win Rate</option>
          </select>
        </div>

        {/* Filters row 2 — style chips + search */}
        <div className="flex flex-wrap items-center gap-2">
          {styleChips.map((s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={cn(
                "px-3 py-1.5 rounded-lg font-mono-t text-[11px] uppercase tracking-widest transition-all duration-150",
                filter === s
                  ? "bg-t-bg2 text-t-hi"
                  : "bg-t-bg1 border border-t-dim text-t-muted hover:text-t-mid2 hover:border-t-mid"
              )}
            >
              {s}{s !== "All" ? ` (${styleCounts[s] ?? 0})` : ""}
            </button>
          ))}
          <div className="flex items-center gap-2 ml-auto bg-t-bg1 border border-t-dim rounded-lg px-3 py-1.5">
            <Search size={12} className="text-t-muted shrink-0" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search..."
              className="bg-transparent text-xs text-t-hi placeholder-t-muted outline-none w-32 font-mono-t"
            />
          </div>
        </div>

        {/* Content */}
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-48 bg-t-bg1 border border-t-dim rounded-2xl animate-pulse" />
            ))}
          </div>
        ) : isError ? (
          <div className="text-center py-16 text-t-muted font-mono-t text-sm">
            Strategy data unavailable. Retry.
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-16 text-t-muted font-mono-t text-sm">
            {filter !== "All"
              ? `No ${filter} strategies in library yet. Add candidates via the pipeline.`
              : "No strategies match your search."}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filtered.map((item, idx) =>
              item.kind === "bot" ? (
                <BotCard
                  key={`bot-${idx}`}
                  row={item.b}
                  expanded={expandedId === item.b.bot_id}
                  onToggle={() => handleToggle(item.b.bot_id)}
                  onNavigate={() => navigate(`/strategy/${item.b.bot_id}`)}
                  onScout={() => navigate(`/strategy/scout?ticker=&strategy=${item.b.bot_id}`)}
                />
              ) : (
                <CandidateCard
                  key={`cand-${idx}`}
                  c={item.c}
                  expanded={expandedId === item.c.file}
                  onToggle={() => handleToggle(item.c.file)}
                  onNavigate={() => navigate(`/candidates/${item.c.file}`)}
                  onScout={() => navigate(`/strategy/scout?strategy=${item.c.file}`)}
                />
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}

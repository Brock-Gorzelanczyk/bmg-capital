import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Search, Star, ExternalLink, TrendingUp, Clock, BarChart2, Zap, Filter, BookOpen, ChevronDown, ChevronUp } from "lucide-react";
import client from "@/api/client";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

interface StrategyEntry {
  id: number;
  module_name: string;
  display_name: string;
  tagline: string;
  category: string;
  asset_class: string;
  time_horizon: string;
  difficulty: string;
  risk_profile: string;
  published_sharpe: number | null;
  win_rate_pub: number | null;
  max_dd_pub: number | null;
  decay_risk: string;
  source_url: string | null;
  paper_citation: string | null;
  suggested_bot: string | null;
  is_top_pick: boolean;
  description_md: string | null;
  mechanics_md: string | null;
  beginner_summary: string | null;
  how_it_decides: string | null;
  why_it_works: string | null;
  when_it_fails: string | null;
}

interface LibraryResponse {
  strategies: StrategyEntry[];
  total: number;
  categories: Record<string, number>;
}

// ─── API ──────────────────────────────────────────────────────────────────────

function getStrategyLibrary(params?: {
  category?: string;
  asset_class?: string;
  difficulty?: string;
  search?: string;
  sort?: string;
}): Promise<LibraryResponse> {
  const q = new URLSearchParams();
  if (params?.category) q.set("category", params.category);
  if (params?.asset_class) q.set("asset_class", params.asset_class);
  if (params?.difficulty) q.set("difficulty", params.difficulty);
  if (params?.search) q.set("search", params.search);
  if (params?.sort) q.set("sort", params.sort);
  return client
    .get<LibraryResponse>(`/strategy-library?${q}`)
    .then((r) => r.data ?? { strategies: [], total: 0, categories: {} })
    .catch(() => ({ strategies: [], total: 0, categories: {} }));
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const DIFFICULTY_COLOR: Record<string, string> = {
  beginner: "bg-lime-500/15 text-lime-400 border-lime-500/30",
  intermediate: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  advanced: "bg-t-red/15 text-t-red border-t-red/30",
};

const HORIZON_ICON: Record<string, typeof TrendingUp> = {
  intraday: Zap,
  swing: BarChart2,
  position: TrendingUp,
  long_term: Clock,
};

const ASSET_COLOR: Record<string, string> = {
  stocks: "text-blue-400",
  crypto: "text-orange-400",
  options: "text-purple-400",
  multi: "text-teal-400",
};

const BOT_LABEL: Record<string, string> = {
  stock_swing: "Stock Swing",
  stock_day: "Stock Day",
  stock_lt: "Stock LT",
  crypto_swing: "Crypto Swing",
  crypto_day: "Crypto Day",
  crypto_lt: "Crypto LT",
  options_income: "Options Income",
  options_directional: "Options Directional",
};

function sharpeColor(v: number | null): string {
  if (v == null) return "text-t-muted";
  if (v >= 2) return "text-lime-400";
  if (v >= 1) return "text-yellow-400";
  return "text-t-red";
}

// ─── Strategy Card ────────────────────────────────────────────────────────────

function StrategyCard({ s }: { s: StrategyEntry }) {
  const [expanded, setExpanded] = useState(false);
  const [beginnerExpanded, setBeginnerExpanded] = useState(false);
  const navigate = useNavigate();
  const HorizonIcon = HORIZON_ICON[s.time_horizon] ?? TrendingUp;
  const hasBeginnerGuide = !!(s.beginner_summary || s.how_it_decides || s.why_it_works || s.when_it_fails);

  return (
    <div
      className={cn(
        "bg-t-bg1 border rounded-2xl p-5 space-y-3 transition-all cursor-pointer card-hover",
        s.is_top_pick ? "border-teal-500/40" : "border-t-dim"
      )}
      onClick={() => setExpanded((v) => !v)}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {s.is_top_pick && (
              <Star className="w-3.5 h-3.5 text-teal-400 fill-teal-400 flex-shrink-0" />
            )}
            <h3 className="text-sm font-bold text-t-hi truncate">{s.display_name}</h3>
            <span className={cn(
              "text-[10px] font-semibold px-1.5 py-0.5 rounded-full border",
              DIFFICULTY_COLOR[s.difficulty] ?? "bg-t-bg2 text-t-mid2 border-t-mid"
            )}>
              {s.difficulty}
            </span>
          </div>
          <p className="text-xs text-t-muted mt-0.5 leading-relaxed">{s.tagline}</p>
        </div>
        <div className="flex items-center gap-1 text-t-muted flex-shrink-0">
          <HorizonIcon className="w-3.5 h-3.5" />
          <span className="text-[10px]">{s.time_horizon}</span>
        </div>
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-4 text-xs">
        <div>
          <p className="text-[9px] text-t-muted uppercase tracking-wide">Sharpe</p>
          <p className={cn("font-bold font-mono-t tabular-nums mt-0.5", sharpeColor(s.published_sharpe))}>
            {s.published_sharpe != null ? s.published_sharpe.toFixed(2) : "—"}
          </p>
        </div>
        <div>
          <p className="text-[9px] text-t-muted uppercase tracking-wide">Win Rate</p>
          <p className="font-bold font-mono-t tabular-nums text-t-hi mt-0.5">
            {s.win_rate_pub != null ? `${(s.win_rate_pub * 100).toFixed(0)}%` : "—"}
          </p>
        </div>
        <div>
          <p className="text-[9px] text-t-muted uppercase tracking-wide">Max DD</p>
          <p className="font-bold font-mono-t tabular-nums text-t-red mt-0.5">
            {s.max_dd_pub != null ? `${(s.max_dd_pub * 100).toFixed(0)}%` : "—"}
          </p>
        </div>
        <div className="ml-auto text-right">
          <p className="text-[9px] text-t-muted uppercase tracking-wide">Asset</p>
          <p className={cn("font-semibold mt-0.5 capitalize", ASSET_COLOR[s.asset_class] ?? "text-t-mid2")}>
            {s.asset_class}
          </p>
        </div>
      </div>

      {/* Tags row */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-t-bg2 border border-t-mid text-t-mid2">
          {s.category}
        </span>
        {s.suggested_bot && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-teal-500/10 border border-teal-500/20 text-teal-500">
            {BOT_LABEL[s.suggested_bot] ?? s.suggested_bot}
          </span>
        )}
        <span className={cn(
          "text-[10px] px-2 py-0.5 rounded-full border",
          s.decay_risk === "low"
            ? "bg-lime-500/10 border-lime-500/20 text-lime-500"
            : s.decay_risk === "medium"
            ? "bg-yellow-500/10 border-yellow-500/20 text-yellow-500"
            : "bg-t-red/10 border-t-red/20 text-t-red"
        )}>
          decay: {s.decay_risk}
        </span>
        <button
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/screener?preset=${s.module_name}`);
          }}
          className="ml-auto text-[10px] font-semibold text-blue-400 hover:text-blue-300 border border-blue-500/30 bg-blue-500/10 hover:bg-blue-500/20 px-2 py-0.5 rounded-full transition-colors flex-shrink-0"
        >
          Run as Screen →
        </button>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="pt-2 border-t border-t-dim space-y-3" onClick={(e) => e.stopPropagation()}>
          {s.description_md && (
            <div>
              <p className="text-[10px] text-t-muted uppercase tracking-wide font-semibold mb-1">What it does</p>
              <p className="text-xs text-t-hi leading-relaxed">{s.description_md}</p>
            </div>
          )}
          {s.mechanics_md && (
            <div>
              <p className="text-[10px] text-t-muted uppercase tracking-wide font-semibold mb-1">How it works</p>
              <p className="text-xs text-t-mid2 leading-relaxed">{s.mechanics_md}</p>
            </div>
          )}
          {s.paper_citation && (
            <div className="flex items-center gap-2">
              <p className="text-[10px] text-t-muted">Source:</p>
              {s.source_url ? (
                <a
                  href={s.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[10px] text-teal-400 hover:text-teal-300 flex items-center gap-1"
                  onClick={(e) => e.stopPropagation()}
                >
                  {s.paper_citation}
                  <ExternalLink className="w-2.5 h-2.5" />
                </a>
              ) : (
                <p className="text-[10px] text-t-muted">{s.paper_citation}</p>
              )}
            </div>
          )}

          {/* Beginner Guide section */}
          {hasBeginnerGuide && (
            <div className="border-t border-t-dim pt-2">
              <button
                onClick={(e) => { e.stopPropagation(); setBeginnerExpanded((v) => !v); }}
                className="flex items-center gap-1.5 text-[10px] font-semibold text-lime-400 hover:text-lime-300 transition-colors w-full text-left"
              >
                <BookOpen className="w-3 h-3 flex-shrink-0" />
                Beginner Guide
                {beginnerExpanded
                  ? <ChevronUp className="w-3 h-3 ml-auto" />
                  : <ChevronDown className="w-3 h-3 ml-auto" />
                }
              </button>
              {beginnerExpanded && (
                <div className="mt-2 space-y-2 bg-lime-500/5 border border-lime-500/15 rounded-xl p-3">
                  {s.beginner_summary && (
                    <div>
                      <p className="text-[9px] text-lime-600 uppercase tracking-wide font-semibold mb-0.5">What it is</p>
                      <p className="text-xs text-t-hi leading-relaxed">{s.beginner_summary}</p>
                    </div>
                  )}
                  {s.how_it_decides && (
                    <div>
                      <p className="text-[9px] text-lime-600 uppercase tracking-wide font-semibold mb-0.5">How it decides</p>
                      <p className="text-xs text-t-mid2 leading-relaxed">{s.how_it_decides}</p>
                    </div>
                  )}
                  {s.why_it_works && (
                    <div>
                      <p className="text-[9px] text-lime-600 uppercase tracking-wide font-semibold mb-0.5">Why it works</p>
                      <p className="text-xs text-t-mid2 leading-relaxed">{s.why_it_works}</p>
                    </div>
                  )}
                  {s.when_it_fails && (
                    <div>
                      <p className="text-[9px] text-lime-600 uppercase tracking-wide font-semibold mb-0.5">When it fails</p>
                      <p className="text-xs text-t-mid2 leading-relaxed">{s.when_it_fails}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

const SORT_OPTIONS = [
  { value: "sharpe", label: "Best Sharpe" },
  { value: "top_pick", label: "Top Picks First" },
  { value: "alphabetical", label: "A → Z" },
];

const ASSET_OPTIONS = ["stocks", "crypto", "options", "multi"];
const DIFFICULTY_OPTIONS = ["beginner", "intermediate", "advanced"];

export default function StrategyLibraryPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [assetClass, setAssetClass] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [sort, setSort] = useState("sharpe");
  const [showFilters, setShowFilters] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["strategy-library", search, category, assetClass, difficulty, sort],
    queryFn: () =>
      getStrategyLibrary({
        search: search || undefined,
        category: category || undefined,
        asset_class: assetClass || undefined,
        difficulty: difficulty || undefined,
        sort,
      }),
    staleTime: 60_000,
  });

  const strategies = Array.isArray(data?.strategies) ? data.strategies : [];
  const categories = data?.categories ?? {};
  const total = data?.total ?? 0;

  const categoryList = useMemo(
    () => Object.keys(categories).sort((a, b) => categories[b] - categories[a]),
    [categories]
  );

  return (
    <div className="animate-page-in max-w-4xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate("/strategy")}
              className="text-xs text-t-muted hover:text-t-hi transition-colors"
            >
              Strategy Lab
            </button>
            <span className="text-t-dim">/</span>
            <span className="text-xs text-t-hi font-semibold">Library</span>
          </div>
          <h1 className="text-xl font-bold text-t-hi mt-1">Strategy Library</h1>
          <p className="text-xs text-t-muted mt-0.5">
            {total} strategies across {categoryList.length} categories — click any card to expand
          </p>
        </div>
        <button
          onClick={() => navigate("/strategy/library/custom-bot")}
          className="px-4 py-2 rounded-xl bg-teal-500/15 border border-teal-500/30 text-teal-400 text-sm font-semibold hover:bg-teal-500/25 transition-colors flex-shrink-0"
        >
          + Custom Bot
        </button>
      </div>

      {/* Search + filter bar */}
      <div className="space-y-3">
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-t-muted" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search strategies…"
              className="w-full bg-t-bg1 border border-t-dim rounded-xl pl-9 pr-4 py-2.5 text-sm text-t-hi placeholder-t-muted focus:outline-none focus:border-teal-500/50"
            />
          </div>
          <button
            onClick={() => setShowFilters((v) => !v)}
            className={cn(
              "px-3 py-2 rounded-xl border text-sm font-semibold transition-colors flex items-center gap-1.5",
              showFilters
                ? "bg-teal-500/15 border-teal-500/40 text-teal-400"
                : "bg-t-bg1 border-t-dim text-t-muted hover:text-t-hi"
            )}
          >
            <Filter className="w-4 h-4" />
            Filters
          </button>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="bg-t-bg1 border border-t-dim rounded-xl px-3 py-2 text-sm text-t-hi focus:outline-none focus:border-teal-500/50"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {showFilters && (
          <div className="bg-t-bg1 border border-t-dim rounded-xl p-4 space-y-4">
            {/* Category filter */}
            <div>
              <p className="text-[10px] text-t-muted uppercase tracking-wide font-semibold mb-2">Category</p>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => setCategory("")}
                  className={cn(
                    "text-xs px-2.5 py-1 rounded-full border transition-colors",
                    !category ? "bg-teal-500/15 border-teal-500/40 text-teal-400" : "border-t-mid text-t-muted hover:text-t-hi"
                  )}
                >
                  All
                </button>
                {categoryList.map((cat) => (
                  <button
                    key={cat}
                    onClick={() => setCategory(cat === category ? "" : cat)}
                    className={cn(
                      "text-xs px-2.5 py-1 rounded-full border transition-colors",
                      category === cat ? "bg-teal-500/15 border-teal-500/40 text-teal-400" : "border-t-mid text-t-muted hover:text-t-hi"
                    )}
                  >
                    {cat} <span className="text-t-dim">({categories[cat]})</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Asset class filter */}
            <div>
              <p className="text-[10px] text-t-muted uppercase tracking-wide font-semibold mb-2">Asset Class</p>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => setAssetClass("")}
                  className={cn(
                    "text-xs px-2.5 py-1 rounded-full border transition-colors",
                    !assetClass ? "bg-teal-500/15 border-teal-500/40 text-teal-400" : "border-t-mid text-t-muted hover:text-t-hi"
                  )}
                >
                  All
                </button>
                {ASSET_OPTIONS.map((a) => (
                  <button
                    key={a}
                    onClick={() => setAssetClass(a === assetClass ? "" : a)}
                    className={cn(
                      "text-xs px-2.5 py-1 rounded-full border transition-colors capitalize",
                      assetClass === a ? "bg-teal-500/15 border-teal-500/40 text-teal-400" : "border-t-mid text-t-muted hover:text-t-hi"
                    )}
                  >
                    {a}
                  </button>
                ))}
              </div>
            </div>

            {/* Difficulty filter */}
            <div>
              <p className="text-[10px] text-t-muted uppercase tracking-wide font-semibold mb-2">Difficulty</p>
              <div className="flex gap-2">
                <button
                  onClick={() => setDifficulty("")}
                  className={cn(
                    "text-xs px-2.5 py-1 rounded-full border transition-colors",
                    !difficulty ? "bg-teal-500/15 border-teal-500/40 text-teal-400" : "border-t-mid text-t-muted hover:text-t-hi"
                  )}
                >
                  All
                </button>
                {DIFFICULTY_OPTIONS.map((d) => (
                  <button
                    key={d}
                    onClick={() => setDifficulty(d === difficulty ? "" : d)}
                    className={cn(
                      "text-xs px-2.5 py-1 rounded-full border transition-colors capitalize",
                      difficulty === d ? "bg-teal-500/15 border-teal-500/40 text-teal-400" : "border-t-mid text-t-muted hover:text-t-hi"
                    )}
                  >
                    {d}
                  </button>
                ))}
              </div>
            </div>

            {/* Clear all */}
            {(category || assetClass || difficulty || search) && (
              <button
                onClick={() => { setCategory(""); setAssetClass(""); setDifficulty(""); setSearch(""); }}
                className="text-xs text-t-red hover:text-t-red/80 transition-colors"
              >
                Clear all filters
              </button>
            )}
          </div>
        )}
      </div>

      {/* Results */}
      {isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-28 bg-t-bg1 border border-t-dim rounded-2xl animate-pulse" />
          ))}
        </div>
      ) : strategies.length === 0 ? (
        <div className="py-16 text-center">
          <p className="text-t-muted text-sm">No strategies match your filters.</p>
          <button
            onClick={() => { setCategory(""); setAssetClass(""); setDifficulty(""); setSearch(""); }}
            className="mt-2 text-xs text-teal-400 hover:text-teal-300 underline underline-offset-2"
          >
            Clear filters
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {strategies.map((s) => (
            <StrategyCard key={s.id} s={s} />
          ))}
        </div>
      )}
    </div>
  );
}

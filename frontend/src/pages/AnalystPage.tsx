import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Brain, AlertTriangle, Star, RefreshCw, TrendingUp, ChevronRight, X } from "lucide-react";
import { toast } from "sonner";
import {
  getAnalystSummary,
  getAnalystRuns,
  analyzeSymbol,
  type WatchlistAnalysis,
  type AnalystSummaryItem,
} from "@/api/analyst";
import { getBots } from "@/api/bots";
import { cn } from "@/lib/utils";

// ─── Conviction stars ─────────────────────────────────────────────────────────

function ConvictionStars({ score, size = "sm" }: { score: number | null; size?: "sm" | "md" }) {
  if (score === null) return <span className="text-xs text-zinc-600">—</span>;
  const sz = size === "md" ? "text-base" : "text-xs";
  return (
    <span className={cn("tracking-tight font-bold", sz, score >= 4 ? "text-lime-400" : score === 3 ? "text-yellow-400" : "text-zinc-500")}>
      {"★".repeat(score)}{"☆".repeat(5 - score)}
    </span>
  );
}

// ─── Thesis slide-out panel ───────────────────────────────────────────────────

function ThesisPanel({ item, onClose }: { item: WatchlistAnalysis | AnalystSummaryItem | null; onClose: () => void }) {
  if (!item) return null;
  const analysis = item as WatchlistAnalysis;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div
        className="relative bg-zinc-950 border-l border-zinc-800 w-full max-w-lg h-full overflow-y-auto p-6 space-y-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-xl font-bold text-white">{item.symbol}</h2>
            <p className="text-xs text-zinc-500 mt-0.5">
              {"bot_name" in item ? item.bot_name?.replace(/_/g, " ") : ""} ·{" "}
              {"ts" in item && item.ts ? new Date(item.ts).toLocaleString() : ""}
            </p>
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors mt-0.5">
            <X size={16} />
          </button>
        </div>

        {/* Conviction */}
        <div className="flex items-center gap-3">
          <ConvictionStars score={item.conviction_score} size="md" />
          <span className="text-sm text-zinc-400">Conviction {item.conviction_score ?? "—"} / 5</span>
          {item.concerns_flag && (
            <span className="flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-400">
              <AlertTriangle size={10} />
              Concerns
            </span>
          )}
        </div>

        {/* Thesis */}
        {analysis.thesis_md && (
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
            <p className="text-sm text-zinc-300 leading-relaxed">{analysis.thesis_md}</p>
          </div>
        )}

        {/* Reasons to own */}
        {Array.isArray(analysis.reasons_to_own) && analysis.reasons_to_own.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold text-lime-400 uppercase tracking-wider mb-2">Reasons to Own</h3>
            <ul className="space-y-1.5">
              {analysis.reasons_to_own.map((r, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-zinc-300">
                  <span className="text-lime-400 mt-0.5 flex-shrink-0">↑</span>
                  {r}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Risks */}
        {Array.isArray(analysis.risks) && analysis.risks.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold text-red-400 uppercase tracking-wider mb-2">Risks</h3>
            <ul className="space-y-1.5">
              {analysis.risks.map((r, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-zinc-300">
                  <span className="text-red-400 mt-0.5 flex-shrink-0">↓</span>
                  {r}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Suggested hold */}
        {analysis.suggested_hold && (
          <div className="bg-zinc-800/50 border border-zinc-700 rounded-xl px-4 py-3">
            <p className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5">Suggested Holding Window</p>
            <p className="text-sm font-semibold text-white">{analysis.suggested_hold}</p>
          </div>
        )}

        {/* Footer */}
        {analysis.model_used && (
          <p className="text-[10px] text-zinc-700">
            Analyzed using {analysis.model_used}
            {analysis.cost_usd ? ` · $${analysis.cost_usd.toFixed(5)}` : ""}
          </p>
        )}
      </div>
    </div>
  );
}

// ─── Summary card ─────────────────────────────────────────────────────────────

function SummaryCard({
  item,
  onClick,
}: {
  item: AnalystSummaryItem;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left bg-zinc-900 border border-zinc-800 hover:border-zinc-700 rounded-xl p-4 transition-colors"
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-white">{item.symbol}</span>
          {item.concerns_flag && (
            <AlertTriangle size={12} className="text-amber-400 flex-shrink-0" />
          )}
        </div>
        <ConvictionStars score={item.conviction_score} />
      </div>
      <p className="text-xs text-zinc-500 mb-1 capitalize">{item.bot_name?.replace(/_/g, " ")}</p>
      {item.thesis_preview && (
        <p className="text-xs text-zinc-400 leading-relaxed line-clamp-2">{item.thesis_preview}…</p>
      )}
      <div className="flex items-center gap-2 mt-2">
        {item.suggested_hold && (
          <span className="text-[10px] text-zinc-600">{item.suggested_hold}</span>
        )}
        <span className="ml-auto text-[10px] text-zinc-700">
          {item.ts ? new Date(item.ts).toLocaleDateString() : ""}
        </span>
      </div>
    </button>
  );
}

// ─── On-demand analyze ────────────────────────────────────────────────────────

function QuickAnalyze() {
  const qc = useQueryClient();
  const [symbol, setSymbol] = useState("");
  const [botProfileId, setBotProfileId] = useState<number | null>(null);
  const [result, setResult] = useState<WatchlistAnalysis | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);

  const { data: botsData } = useQuery({
    queryKey: ["bots-v2"],
    queryFn: getBots,
    staleTime: 120_000,
  });
  const bots = botsData?.bots ?? [];

  const analyzeMut = useMutation({
    mutationFn: () => {
      if (!symbol || !botProfileId) throw new Error("Fill in symbol and bot");
      return analyzeSymbol(symbol.toUpperCase(), botProfileId, true);
    },
    onSuccess: (data) => {
      setResult(data);
      setPanelOpen(true);
      qc.invalidateQueries({ queryKey: ["analyst-summary"] });
      toast.success(`Analysis complete for ${symbol.toUpperCase()}`);
    },
    onError: (e: Error) => toast.error(e.message || "Analysis failed"),
  });

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <h2 className="text-sm font-semibold text-zinc-300 mb-3 flex items-center gap-2">
        <Brain size={14} className="text-[#84cc16]" />
        Analyze Any Symbol
      </h2>
      <div className="flex gap-2 flex-wrap">
        <input
          type="text"
          placeholder="NVDA, BTC-USD…"
          value={symbol}
          onChange={e => setSymbol(e.target.value.toUpperCase())}
          className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-lime-500/50 w-32"
        />
        <select
          value={botProfileId ?? ""}
          onChange={e => setBotProfileId(Number(e.target.value) || null)}
          className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-300 focus:outline-none focus:border-lime-500/50 flex-1 min-w-[140px]"
        >
          <option value="">Select bot…</option>
          {bots.map(b => (
            <option key={b.profile.id} value={b.profile.id}>
              {b.profile.name.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <button
          onClick={() => analyzeMut.mutate()}
          disabled={analyzeMut.isPending || !symbol || !botProfileId}
          className="px-4 py-2 rounded-lg bg-[#84cc16] text-black text-sm font-bold hover:bg-lime-400 transition-colors disabled:opacity-50"
        >
          {analyzeMut.isPending ? "Analyzing…" : "Analyze"}
        </button>
      </div>
      {panelOpen && result && (
        <ThesisPanel item={result} onClose={() => setPanelOpen(false)} />
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AnalystPage() {
  const navigate = useNavigate();
  const [selectedItem, setSelectedItem] = useState<AnalystSummaryItem | null>(null);
  const [filterConviction, setFilterConviction] = useState<number | null>(null);
  const [tab, setTab] = useState<"top" | "concerns" | "runs">("top");

  const { data: summary, isLoading, refetch } = useQuery({
    queryKey: ["analyst-summary"],
    queryFn: getAnalystSummary,
    staleTime: 60_000,
    refetchInterval: 120_000,
  });

  const { data: runs = [] } = useQuery({
    queryKey: ["analyst-runs"],
    queryFn: () => getAnalystRuns(),
    staleTime: 60_000,
    enabled: tab === "runs",
  });

  const topPicks = (summary?.top_picks ?? []).filter(
    p => filterConviction === null || p.conviction_score === filterConviction
  );
  const concerns = summary?.concerns ?? [];

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Brain size={20} className="text-[#84cc16]" />
            <h1 className="text-2xl font-bold text-white">AI Analyst</h1>
          </div>
          <p className="text-zinc-500 text-sm">
            Claude-powered thesis on every name across all bot watchlists. Grounded in fundamentals, technicals, and strategy votes.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate("/strategy")}
            className="text-xs text-zinc-500 hover:text-zinc-300 flex items-center gap-1 transition-colors"
          >
            Strategy Lab
            <ChevronRight size={12} />
          </button>
          <button
            onClick={() => refetch()}
            className="text-xs px-3 py-1.5 rounded-lg border border-zinc-700 text-zinc-400 hover:text-white flex items-center gap-1.5 transition-colors"
          >
            <RefreshCw size={11} />
            Refresh
          </button>
        </div>
      </div>

      {/* Summary metrics */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Analyzed Today", value: isLoading ? "—" : String(summary?.total_analyzed ?? 0), icon: <Brain size={14} className="text-[#84cc16]" /> },
          { label: "High Conviction", value: isLoading ? "—" : String(summary?.num_high_conviction ?? 0), icon: <Star size={14} className="text-lime-400" /> },
          { label: "Concerns Flagged", value: isLoading ? "—" : String(summary?.num_flagged ?? 0), icon: <AlertTriangle size={14} className="text-amber-400" /> },
        ].map(m => (
          <div key={m.label} className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3">
            <div className="flex items-center gap-1.5 mb-1">
              {m.icon}
              <p className="text-[10px] text-zinc-500 uppercase tracking-wider">{m.label}</p>
            </div>
            <p className="text-2xl font-bold text-white">{m.value}</p>
          </div>
        ))}
      </div>

      {/* Quick analyze */}
      <QuickAnalyze />

      {/* Tabs */}
      <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1">
        {([["top", "Top Picks"], ["concerns", "Concerns"], ["runs", "Run History"]] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              "text-sm font-semibold py-2 px-4 rounded-lg transition-colors flex-1",
              tab === key ? "bg-zinc-700 text-white" : "text-zinc-500 hover:text-zinc-300"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Conviction filter (top tab only) */}
      {tab === "top" && (
        <div className="flex gap-1.5 flex-wrap">
          <button
            onClick={() => setFilterConviction(null)}
            className={cn(
              "text-xs font-semibold px-3 py-1 rounded-lg border transition-colors",
              filterConviction === null ? "bg-lime-500/15 border-lime-500/30 text-lime-400" : "bg-zinc-800 border-zinc-700 text-zinc-500 hover:text-zinc-300"
            )}
          >
            All
          </button>
          {[5, 4, 3, 2, 1].map(s => (
            <button
              key={s}
              onClick={() => setFilterConviction(filterConviction === s ? null : s)}
              className={cn(
                "text-xs font-semibold px-3 py-1 rounded-lg border transition-colors",
                filterConviction === s ? "bg-lime-500/15 border-lime-500/30 text-lime-400" : "bg-zinc-800 border-zinc-700 text-zinc-500 hover:text-zinc-300"
              )}
            >
              {"★".repeat(s)}
            </button>
          ))}
        </div>
      )}

      {/* Content */}
      {tab === "top" && (
        isLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 animate-pulse">
            {[0,1,2,3,4,5].map(i => <div key={i} className="h-28 bg-zinc-800 rounded-xl" />)}
          </div>
        ) : topPicks.length === 0 ? (
          <div className="text-center py-16 text-zinc-500">
            <Brain size={32} className="mx-auto mb-3 text-zinc-700" />
            <p className="text-sm">No analyses yet.</p>
            <p className="text-xs text-zinc-600 mt-1">Use "Refresh" on any bot's watchlist, or analyze a symbol above.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {topPicks.map(item => (
              <SummaryCard key={`${item.bot_profile_id}-${item.symbol}`} item={item} onClick={() => setSelectedItem(item)} />
            ))}
          </div>
        )
      )}

      {tab === "concerns" && (
        concerns.length === 0 ? (
          <div className="text-center py-16 text-zinc-500">
            <AlertTriangle size={32} className="mx-auto mb-3 text-zinc-700" />
            <p className="text-sm">No concerns flagged.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {concerns.map(item => (
              <SummaryCard key={`${item.bot_profile_id}-${item.symbol}`} item={item} onClick={() => setSelectedItem(item)} />
            ))}
          </div>
        )
      )}

      {tab === "runs" && (
        runs.length === 0 ? (
          <div className="text-center py-16 text-zinc-500">
            <p className="text-sm">No run history yet.</p>
          </div>
        ) : (
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-zinc-600 border-b border-zinc-800">
                  <th className="text-left px-4 py-3 font-medium">Date</th>
                  <th className="text-left px-4 py-3 font-medium">Bot</th>
                  <th className="text-right px-4 py-3 font-medium">Analyzed</th>
                  <th className="text-right px-4 py-3 font-medium">High Conviction</th>
                  <th className="text-right px-4 py-3 font-medium">Concerns</th>
                  <th className="text-right px-4 py-3 font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {runs.map(r => (
                  <tr key={r.id} className="border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/20">
                    <td className="px-4 py-2.5 text-zinc-400">{r.date}</td>
                    <td className="px-4 py-2.5 text-zinc-300">{String(r.bot_profile_id)}</td>
                    <td className="px-4 py-2.5 text-right text-white">{r.num_analyzed}</td>
                    <td className="px-4 py-2.5 text-right text-lime-400">{r.num_high_conviction}</td>
                    <td className="px-4 py-2.5 text-right text-amber-400">{r.num_flagged_concerns}</td>
                    <td className="px-4 py-2.5 text-right text-zinc-500">${r.total_cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {/* Footer */}
      <p className="text-xs text-center text-zinc-700">
        AI-generated research. Not investment advice. Powered by Claude · Grounded in real market data.
      </p>

      {/* Slide-out panel */}
      <ThesisPanel item={selectedItem} onClose={() => setSelectedItem(null)} />
    </div>
  );
}

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Search, Plus, Trash2, Clock, ArrowRight, Star, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { SectionLabel } from "@/components/design";
import client from "@/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

interface WorkshopChart {
  id: number;
  ticker: string;
  strategy_id: string;
  name: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
  rating_overall: number | null;
  rating_chart_pattern: number | null;
  rating_indicator_confluence: number | null;
  rating_volume: number | null;
  rating_risk_reward: number | null;
  rating_conviction: "low" | "medium" | "high" | null;
  rating_notes: string | null;
  rating_updated_at: string | null;
}

interface RatingPayload {
  overall: number;
  chart_pattern: number | null;
  indicator_confluence: number | null;
  volume: number | null;
  risk_reward: number | null;
  conviction: "low" | "medium" | "high" | null;
  notes: string | null;
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function listCharts(): Promise<WorkshopChart[]> {
  const res = await client.get<{ charts: WorkshopChart[] }>("/strategy-workshop/charts");
  return res.data.charts ?? [];
}

async function deleteChart(id: number): Promise<void> {
  await client.delete(`/strategy-workshop/charts/${id}`);
}

async function saveRating(id: number, payload: RatingPayload): Promise<WorkshopChart> {
  const res = await client.put<WorkshopChart>(`/strategy-workshop/charts/${id}/rating`, payload);
  return res.data;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(ts: string): string {
  try {
    const diff = Date.now() - new Date(ts).getTime();
    const mins = Math.floor(diff / 60000);
    const hrs  = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);
    if (days > 0) return `${days}d ago`;
    if (hrs > 0)  return `${hrs}h ago`;
    if (mins > 0) return `${mins}m ago`;
    return "just now";
  } catch { return ts; }
}

function strategyLabel(sid: string): string {
  return sid.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function ratingDotClass(overall: number | null): string {
  if (overall === null) return "border border-t-dim bg-transparent";
  if (overall <= 2)     return "bg-t-red";
  if (overall === 3)    return "bg-yellow-500";
  return "bg-t-green";
}

// ── Star row ──────────────────────────────────────────────────────────────────

function StarRow({ value, onChange }: { value: number | null; onChange: (v: number) => void }) {
  const [hover, setHover] = useState<number | null>(null);
  const active = hover ?? value ?? 0;
  return (
    <div className="flex gap-1">
      {[1, 2, 3, 4, 5].map(n => (
        <button
          key={n}
          type="button"
          onClick={() => onChange(n)}
          onMouseEnter={() => setHover(n)}
          onMouseLeave={() => setHover(null)}
          className="transition-colors"
        >
          <Star
            size={18}
            className={n <= active ? "text-yellow-400 fill-yellow-400" : "text-t-dim"}
          />
        </button>
      ))}
    </div>
  );
}

// ── Mini 1-5 slider ───────────────────────────────────────────────────────────

function MiniRatingRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-[10px] text-t-muted font-mono-t w-40 shrink-0">{label}</span>
      <div className="flex gap-1">
        {[1, 2, 3, 4, 5].map(n => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(value === n ? null : n)}
            className={cn(
              "w-5 h-5 rounded text-[9px] font-bold font-mono-t transition-colors",
              value === n
                ? "bg-t-violet text-t-bg0"
                : "bg-t-bg2 text-t-faint hover:bg-t-violet/30 hover:text-t-hi"
            )}
          >
            {n}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Rating section ─────────────────────────────────────────────────────────────

function RatingSection({
  chart,
  onSave,
  isSaving,
}: {
  chart: WorkshopChart;
  onSave: (payload: RatingPayload) => void;
  isSaving: boolean;
}) {
  const [overall, setOverall] = useState<number | null>(chart.rating_overall);
  const [conviction, setConviction] = useState<"low" | "medium" | "high" | null>(chart.rating_conviction);
  const [chartPattern, setChartPattern] = useState<number | null>(chart.rating_chart_pattern);
  const [confluence, setConfluence] = useState<number | null>(chart.rating_indicator_confluence);
  const [volume, setVolume] = useState<number | null>(chart.rating_volume);
  const [riskReward, setRiskReward] = useState<number | null>(chart.rating_risk_reward);
  const [notes, setNotes] = useState<string>(chart.rating_notes ?? "");
  const [expanded, setExpanded] = useState(false);

  const canSave = overall !== null && conviction !== null;

  const handleSave = () => {
    if (!canSave) return;
    onSave({
      overall: overall!,
      chart_pattern: chartPattern,
      indicator_confluence: confluence,
      volume,
      risk_reward: riskReward,
      conviction,
      notes: notes.trim() || null,
    });
  };

  const convictionOpts: { val: "low" | "medium" | "high"; label: string; color: string }[] = [
    { val: "low",    label: "Low",    color: "text-t-red border-t-red/40 bg-t-red/10" },
    { val: "medium", label: "Medium", color: "text-yellow-400 border-yellow-400/40 bg-yellow-400/10" },
    { val: "high",   label: "High",   color: "text-t-green border-t-green/40 bg-t-green/10" },
  ];

  return (
    <div className="bg-t-bg0 border border-t-dim rounded-xl p-4 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-mono-t text-t-gdim uppercase tracking-widest">// SETUP RATING</p>
        {chart.rating_updated_at && (
          <span className="text-[9px] text-t-faint font-mono-t">Rated {timeAgo(chart.rating_updated_at)}</span>
        )}
      </div>

      {/* Overall stars */}
      <div className="space-y-1.5">
        <p className="text-[10px] text-t-muted font-mono-t">Overall Quality <span className="text-t-red">*</span></p>
        <StarRow value={overall} onChange={setOverall} />
      </div>

      {/* Conviction */}
      <div className="space-y-1.5">
        <p className="text-[10px] text-t-muted font-mono-t">Conviction <span className="text-t-red">*</span></p>
        <div className="flex gap-2">
          {convictionOpts.map(({ val, label, color }) => (
            <button
              key={val}
              type="button"
              onClick={() => setConviction(conviction === val ? null : val)}
              className={cn(
                "px-3 py-1 rounded-lg text-[10px] font-mono-t border transition-colors",
                conviction === val ? color : "text-t-muted border-t-dim hover:border-t-mid"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Detailed breakdown (expandable) */}
      <div>
        <button
          type="button"
          onClick={() => setExpanded(e => !e)}
          className="flex items-center gap-1.5 text-[10px] text-t-muted font-mono-t hover:text-t-hi transition-colors"
        >
          {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          Detailed breakdown
        </button>

        {expanded && (
          <div className="mt-3 space-y-2.5">
            <MiniRatingRow label="Chart Pattern Quality"   value={chartPattern} onChange={setChartPattern} />
            <MiniRatingRow label="Indicator Confluence"    value={confluence}   onChange={setConfluence} />
            <MiniRatingRow label="Volume Confirmation"     value={volume}       onChange={setVolume} />
            <MiniRatingRow label="Risk / Reward Ratio"     value={riskReward}   onChange={setRiskReward} />
            <div className="pt-1">
              <p className="text-[10px] text-t-muted font-mono-t mb-1">Rating notes</p>
              <textarea
                value={notes}
                onChange={e => setNotes(e.target.value)}
                rows={2}
                placeholder="Optional — what made this setup stand out or fail…"
                className="w-full bg-t-bg1 border border-t-dim rounded-lg px-3 py-2 text-xs text-t-hi placeholder-t-faint font-mono-t outline-none resize-none focus:border-t-mid transition-colors"
              />
            </div>
          </div>
        )}
      </div>

      {/* Save button */}
      <button
        type="button"
        onClick={handleSave}
        disabled={!canSave || isSaving}
        className={cn(
          "w-full py-2 rounded-lg text-xs font-mono-t font-bold transition-colors",
          canSave
            ? "bg-t-green text-t-bg0 hover:bg-t-green/80"
            : "bg-t-bg2 text-t-faint cursor-not-allowed"
        )}
      >
        {isSaving ? "Saving…" : "Save Rating"}
      </button>
    </div>
  );
}

// ── Chart list item ───────────────────────────────────────────────────────────

function ChartListItem({
  chart,
  selected,
  onClick,
  onDelete,
}: {
  chart: WorkshopChart;
  selected: boolean;
  onClick: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "p-3 rounded-xl cursor-pointer border transition-all group",
        selected
          ? "border-t-mid bg-t-bg2"
          : "border-t-dim bg-t-bg1 hover:border-t-mid hover:bg-t-bg2/50"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          {/* Rating dot */}
          <div className={cn("w-2.5 h-2.5 rounded-full shrink-0 mt-0.5", ratingDotClass(chart.rating_overall))} />
          <div className="min-w-0">
            <p className="text-xs font-semibold text-t-hi font-ui-t truncate leading-tight">{chart.name}</p>
            <p className="text-[10px] text-t-muted font-mono-t mt-0.5">
              {chart.ticker} × {strategyLabel(chart.strategy_id)}
            </p>
          </div>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-t-muted hover:text-t-red"
        >
          <Trash2 size={12} />
        </button>
      </div>
      <div className="flex items-center gap-1 mt-1.5">
        <Clock size={9} className="text-t-faint" />
        <span className="text-[9px] text-t-faint font-mono-t">{timeAgo(chart.updated_at)}</span>
        {chart.rating_overall !== null && (
          <>
            <span className="text-[9px] text-t-faint font-mono-t">·</span>
            <Star size={8} className="text-yellow-400 fill-yellow-400" />
            <span className="text-[9px] text-t-faint font-mono-t">{chart.rating_overall}/5</span>
          </>
        )}
      </div>
    </div>
  );
}

// ── Main view ─────────────────────────────────────────────────────────────────

export default function StrategyWorkshopPage() {
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: charts = [], isLoading, isError } = useQuery<WorkshopChart[]>({
    queryKey: ["workshop-charts"],
    queryFn: listCharts,
    staleTime: 30_000,
    retry: 2,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteChart,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workshop-charts"] });
      if (charts.find(c => c.id === selectedId)) setSelectedId(null);
      toast.success("Chart deleted");
    },
    onError: () => toast.error("Delete failed"),
  });

  const ratingMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: RatingPayload }) =>
      saveRating(id, payload),
    onSuccess: (updated) => {
      qc.setQueryData<WorkshopChart[]>(["workshop-charts"], prev =>
        prev ? prev.map(c => c.id === updated.id ? updated : c) : prev
      );
      toast.success("Rating saved");
    },
    onError: () => toast.error("Failed to save rating"),
  });

  const filtered = charts.filter(c =>
    !search || c.name.toLowerCase().includes(search.toLowerCase()) ||
    c.ticker.toLowerCase().includes(search.toLowerCase()) ||
    c.strategy_id.toLowerCase().includes(search.toLowerCase())
  );

  const selected = charts.find(c => c.id === selectedId) ?? null;

  // Aggregate stats
  const rated = charts.filter(c => c.rating_overall !== null);
  const avgRating = rated.length > 0
    ? (rated.reduce((sum, c) => sum + (c.rating_overall ?? 0), 0) / rated.length).toFixed(1)
    : null;

  return (
    <div className="min-h-screen bg-t-bg0 text-t-hi animate-page-in">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">

        {/* Header */}
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <SectionLabel as="h1" className="text-base mb-1">// WORKSHOP</SectionLabel>
            <p className="text-sm text-t-muted font-mono-t">
              Saved Scout chart views · annotate setups · track triggers
            </p>
          </div>
          <button
            onClick={() => navigate("/strategy/scout")}
            className="flex items-center gap-2 px-4 py-2 text-sm font-mono-t text-t-green border border-t-green/30 rounded-lg hover:bg-t-green/10 transition-colors"
          >
            <Plus size={14} /> New chart
          </button>
        </div>

        <div className="flex gap-5" style={{ minHeight: 600 }}>

          {/* Left rail — chart list */}
          <div className="w-72 shrink-0 flex flex-col gap-3">
            {/* Search */}
            <div className="flex items-center gap-2 bg-t-bg1 border border-t-dim rounded-xl px-3 py-2">
              <Search size={12} className="text-t-muted shrink-0" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search charts..."
                className="bg-transparent text-xs text-t-hi placeholder-t-muted outline-none flex-1 font-mono-t"
              />
            </div>

            {/* Aggregate stat */}
            {charts.length > 0 && (
              <p className="text-[10px] text-t-faint font-mono-t px-1">
                {charts.length} chart{charts.length !== 1 ? "s" : ""}
                {" · "}{rated.length} rated
                {avgRating ? ` · Avg quality: ${avgRating}/5` : ""}
              </p>
            )}

            {/* Legend */}
            <div className="flex items-center gap-3 px-1">
              <div className="flex items-center gap-1">
                <div className="w-2 h-2 rounded-full border border-t-dim bg-transparent" />
                <span className="text-[9px] text-t-faint font-mono-t">unrated</span>
              </div>
              <div className="flex items-center gap-1">
                <div className="w-2 h-2 rounded-full bg-t-red" />
                <span className="text-[9px] text-t-faint font-mono-t">1-2</span>
              </div>
              <div className="flex items-center gap-1">
                <div className="w-2 h-2 rounded-full bg-yellow-500" />
                <span className="text-[9px] text-t-faint font-mono-t">3</span>
              </div>
              <div className="flex items-center gap-1">
                <div className="w-2 h-2 rounded-full bg-t-green" />
                <span className="text-[9px] text-t-faint font-mono-t">4-5</span>
              </div>
            </div>

            {/* List */}
            {isLoading ? (
              <div className="space-y-2">
                {[0, 1, 2].map(i => <div key={i} className="h-20 bg-t-bg1 border border-t-dim rounded-xl animate-pulse" />)}
              </div>
            ) : isError ? (
              <div className="text-xs text-t-muted font-mono-t text-center py-6">
                Failed to load charts.
              </div>
            ) : filtered.length === 0 ? (
              <div className="text-center py-12 space-y-3">
                <p className="text-xs text-t-muted font-mono-t">
                  {search ? "No charts match your search." : "No saved charts yet."}
                </p>
                {!search && (
                  <button
                    onClick={() => navigate("/strategy/scout")}
                    className="text-xs font-mono-t text-t-green hover:underline"
                  >
                    → Go to Scout and ARM a setup
                  </button>
                )}
              </div>
            ) : (
              <div className="space-y-1.5 overflow-y-auto" style={{ maxHeight: 560 }}>
                {filtered.map(chart => (
                  <ChartListItem
                    key={chart.id}
                    chart={chart}
                    selected={selectedId === chart.id}
                    onClick={() => setSelectedId(chart.id)}
                    onDelete={() => deleteMutation.mutate(chart.id)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Main area — chart viewer */}
          <div className="flex-1 min-w-0">
            {selected ? (
              <div className="bg-t-bg1 border border-t-dim rounded-2xl p-6 h-full space-y-4">
                {/* Selected chart header */}
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-base font-semibold font-ui-t text-t-hi">{selected.name}</h2>
                    <p className="text-xs text-t-muted font-mono-t mt-0.5">
                      {selected.ticker} × {strategyLabel(selected.strategy_id)}
                      &nbsp;·&nbsp;saved {timeAgo(selected.updated_at)}
                    </p>
                  </div>
                  <button
                    onClick={() => navigate(`/strategy/scout/chart/${encodeURIComponent(selected.ticker)}/${selected.strategy_id}`)}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm font-mono-t text-t-violet border border-t-violet/30 rounded-lg hover:bg-t-violet/10 shrink-0"
                  >
                    Open chart <ArrowRight size={14} />
                  </button>
                </div>

                {/* Rating section */}
                <RatingSection
                  key={selected.id}
                  chart={selected}
                  onSave={(payload) => ratingMutation.mutate({ id: selected.id, payload })}
                  isSaving={ratingMutation.isPending}
                />

                {/* Notes */}
                {selected.notes && (
                  <div className="bg-t-bg0 border border-t-dim rounded-xl p-4">
                    <p className="text-[10px] font-mono-t text-t-gdim uppercase tracking-widest mb-2">// NOTES</p>
                    <p className="text-sm text-t-body font-ui-t leading-relaxed whitespace-pre-wrap">{selected.notes}</p>
                  </div>
                )}

                {/* Chart preview — navigate out to full page */}
                <div
                  className="bg-t-bg0 border border-t-dim rounded-xl overflow-hidden cursor-pointer hover:border-t-mid transition-colors group"
                  style={{ height: 220 }}
                  onClick={() => navigate(`/strategy/scout/chart/${encodeURIComponent(selected.ticker)}/${selected.strategy_id}`)}
                >
                  <div className="h-full flex flex-col items-center justify-center gap-3 text-t-muted group-hover:text-t-mid2 transition-colors">
                    <div className="w-12 h-12 rounded-full border border-t-dim flex items-center justify-center group-hover:border-t-mid transition-colors">
                      <ArrowRight size={20} />
                    </div>
                    <p className="text-sm font-mono-t">Click to open full chart for {selected.ticker}</p>
                    <p className="text-xs text-t-faint font-mono-t">includes MA overlays + past triggers</p>
                  </div>
                </div>

                {/* Meta info */}
                <div className="grid grid-cols-2 gap-3 text-xs font-mono-t">
                  <div className="bg-t-bg0 border border-t-dim rounded-xl px-3 py-2.5">
                    <p className="text-[9px] text-t-gdim uppercase tracking-widest mb-1">TICKER</p>
                    <p className="text-t-hi font-bold">{selected.ticker}</p>
                  </div>
                  <div className="bg-t-bg0 border border-t-dim rounded-xl px-3 py-2.5">
                    <p className="text-[9px] text-t-gdim uppercase tracking-widest mb-1">STRATEGY</p>
                    <p className="text-t-hi font-bold truncate">{strategyLabel(selected.strategy_id)}</p>
                  </div>
                </div>
              </div>
            ) : (
              /* Empty state */
              <div className="h-full flex items-center justify-center bg-t-bg1 border border-t-dim rounded-2xl p-8">
                <div className="text-center space-y-4 max-w-sm">
                  <div className="w-16 h-16 rounded-2xl bg-t-bg2 border border-t-dim flex items-center justify-center mx-auto">
                    <SectionLabel className="text-lg">✎</SectionLabel>
                  </div>
                  <div>
                    <p className="text-t-body font-semibold font-ui-t mb-1">Your saved charts live here</p>
                    <p className="text-t-muted text-sm font-ui-t leading-relaxed">
                      Use Scout to find setups, then click "Save to Workshop" to annotate,
                      track, and monitor them over time.
                    </p>
                  </div>
                  <button
                    onClick={() => navigate("/strategy/scout")}
                    className="flex items-center gap-2 px-5 py-2.5 text-sm font-mono-t text-t-bg0 bg-t-green rounded-lg font-bold mx-auto hover:bg-t-green/80"
                  >
                    Go to Scout <ArrowRight size={14} />
                  </button>
                  {charts.length > 0 && (
                    <p className="text-xs text-t-muted font-mono-t">or select a chart from the list →</p>
                  )}
                </div>
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}

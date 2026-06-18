import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Search, Plus, Trash2, Clock, ArrowRight } from "lucide-react";
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
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function listCharts(): Promise<WorkshopChart[]> {
  const res = await client.get<{ charts: WorkshopChart[] }>("/strategy-workshop/charts");
  return res.data.charts ?? [];
}

async function deleteChart(id: number): Promise<void> {
  await client.delete(`/strategy-workshop/charts/${id}`);
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
        <div className="min-w-0">
          <p className="text-xs font-semibold text-t-hi font-ui-t truncate leading-tight">{chart.name}</p>
          <p className="text-[10px] text-t-muted font-mono-t mt-0.5">
            {chart.ticker} × {strategyLabel(chart.strategy_id)}
          </p>
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

  const filtered = charts.filter(c =>
    !search || c.name.toLowerCase().includes(search.toLowerCase()) ||
    c.ticker.toLowerCase().includes(search.toLowerCase()) ||
    c.strategy_id.toLowerCase().includes(search.toLowerCase())
  );

  const selected = charts.find(c => c.id === selectedId) ?? null;

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
                    onClick={() => navigate(`/strategy/scout/chart/${selected.ticker}/${selected.strategy_id}`)}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm font-mono-t text-t-violet border border-t-violet/30 rounded-lg hover:bg-t-violet/10 shrink-0"
                  >
                    Open chart <ArrowRight size={14} />
                  </button>
                </div>

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
                  style={{ height: 280 }}
                  onClick={() => navigate(`/strategy/scout/chart/${selected.ticker}/${selected.strategy_id}`)}
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

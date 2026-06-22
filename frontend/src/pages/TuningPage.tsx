import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle,
  ArrowUp,
  CheckCircle2,
  Flame,
  Gauge,
  PlayCircle,
  RefreshCw,
  Siren,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Skeleton, StatCardSkeleton, RowCardSkeleton } from "@/components/Skeleton";
import { getTuningRecommendations, getPromotionCandidates, type Severity, type TuningRow } from "@/api/tuning";
import { promoteHypothesis } from "@/api/hypotheses";

type WindowKey = 1 | 7 | 30;

function severityCls(s: Severity): string {
  switch (s) {
    case "red":  return "bg-t-red/15 text-t-red border-t-red/40";
    case "warn": return "bg-amber-900/20 text-amber-300 border-amber-700/40";
    case "ok":   return "bg-t-green/15 text-t-green border-t-green/40";
    default:     return "bg-t-bg2 text-t-muted border-t-dim";
  }
}

function RowCard({ row, icon: Icon }: { row: TuningRow; icon: any }) {
  return (
    <div className="border border-t-dim bg-t-bg1 rounded-xl p-3 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          <Icon size={14} className="text-t-muted mt-0.5 flex-shrink-0" />
          <div className="min-w-0">
            <div className="text-xs font-semibold text-t-hi truncate">{row.strategy}</div>
            <div className="text-[10px] text-t-muted font-mono">
              {row.analyzed} analyzed · {row.executed} executed · {Math.round(row.reject_rate * 100)}% rejected · avg score {row.avg_score}
            </div>
          </div>
        </div>
        <span className={cn(
          "text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border flex-shrink-0",
          severityCls(row.action.severity),
        )}>
          {row.action.label}
        </span>
      </div>
      {row.action.detail && (
        <div className="text-[11px] text-t-mid2 leading-snug">{row.action.detail}</div>
      )}
      {row.top_filter_reason !== "none" && (
        <div className="text-[10px] text-t-muted">
          top filter: <span className="text-amber-400">{row.top_filter_reason}</span> ({row.top_filter_count})
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  icon: Icon,
  rows,
  emptyHint,
  iconColor,
}: {
  title: string;
  icon: any;
  rows: TuningRow[];
  emptyHint?: string;
  iconColor?: string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-t-muted font-bold">
        <Icon size={12} className={iconColor ?? ""} /> {title} <span className="text-t-hi">({rows.length})</span>
      </div>
      {rows.length === 0 ? (
        <div className="text-[11px] italic text-t-muted px-2 py-3">
          {emptyHint ?? "—"}
        </div>
      ) : (
        rows.map((r) => <RowCard key={r.strategy + title} row={r} icon={Icon} />)
      )}
    </div>
  );
}

export default function TuningPage() {
  const [days, setDays] = useState<WindowKey>(1);
  const qc = useQueryClient();

  const { data: rec, isLoading: recLoading, refetch: refetchRec, isFetching: recFetching } = useQuery({
    queryKey: ["tuning-recommendations", days],
    queryFn: () => getTuningRecommendations(days),
    refetchInterval: 60_000,
    staleTime: 55_000,
  });

  const { data: promo, isLoading: promoLoading, refetch: refetchPromo } = useQuery({
    queryKey: ["promotion-candidates"],
    queryFn: getPromotionCandidates,
    refetchInterval: 5 * 60_000,
    staleTime: 4 * 60_000,
  });

  const promoteMut = useMutation({
    mutationFn: (id: number) => promoteHypothesis(id),
    onSuccess: () => {
      toast.success("Promoted to LIVE");
      qc.invalidateQueries({ queryKey: ["promotion-candidates"] });
      qc.invalidateQueries({ queryKey: ["hypotheses-live"] });
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? err?.message ?? "request failed";
      toast.error(`Promotion failed: ${typeof msg === "string" ? msg : "unknown"}`);
    },
  });

  if (recLoading || promoLoading) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-6 pb-24 md:pb-6 space-y-5">
        <div className="space-y-2">
          <Skeleton h="11px" w="120px" />
          <Skeleton h="28px" w="220px" />
          <Skeleton h="14px" w="60%" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCardSkeleton /><StatCardSkeleton /><StatCardSkeleton /><StatCardSkeleton />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="space-y-2"><Skeleton h="12px" w="40%" /><RowCardSkeleton /><RowCardSkeleton /></div>
          <div className="space-y-2"><Skeleton h="12px" w="40%" /><RowCardSkeleton /><RowCardSkeleton /></div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="space-y-2"><Skeleton h="12px" w="40%" /><RowCardSkeleton /><RowCardSkeleton /></div>
          <div className="space-y-2"><Skeleton h="12px" w="40%" /><RowCardSkeleton /><RowCardSkeleton /></div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 pb-24 md:pb-6 space-y-5 animate-page-in">

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <p className="text-[10px] font-semibold text-t-muted uppercase tracking-widest mb-0.5">
            // STRATEGY LAB · OPS
          </p>
          <h1 className="text-2xl font-bold text-t-hi flex items-center gap-2">
            <Gauge size={22} className="text-violet-400" /> Tuning Advisor
          </h1>
          <p className="text-t-muted text-sm mt-1">
            Monday-morning triage: which strategies need attention, which are ready to promote.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {([
            [1, "TODAY"],
            [7, "7D"],
            [30, "30D"],
          ] as [WindowKey, string][]).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setDays(k)}
              className={cn(
                "text-[10px] font-bold px-3 py-1.5 rounded border transition-colors",
                days === k
                  ? "bg-t-bg2 border-t-mid text-t-hi"
                  : "border-t-dim text-t-muted hover:text-t-hi",
              )}
            >
              {label}
            </button>
          ))}
          <button
            onClick={() => { refetchRec(); refetchPromo(); }}
            disabled={recFetching}
            className="flex items-center gap-1.5 bg-t-bg1 border border-t-dim hover:border-t-mid text-t-mid2 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw size={12} className={cn(recFetching && "animate-spin")} /> Refresh
          </button>
        </div>
      </div>

      {/* Summary bar */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-t-bg1 border border-t-dim rounded-xl px-4 py-3">
          <div className="text-[10px] uppercase tracking-widest text-t-muted">Strategies Active</div>
          <div className="text-2xl font-bold font-mono-t text-t-hi">{rec?.total_strategies_with_activity ?? 0}</div>
        </div>
        <div className="bg-t-bg1 border border-t-dim rounded-xl px-4 py-3">
          <div className="text-[10px] uppercase tracking-widest text-t-muted">Signals Analyzed</div>
          <div className="text-2xl font-bold font-mono-t text-t-hi">{rec?.total_analyzed ?? 0}</div>
        </div>
        <div className="bg-t-bg1 border border-t-dim rounded-xl px-4 py-3">
          <div className="text-[10px] uppercase tracking-widest text-t-muted">Executed</div>
          <div className="text-2xl font-bold font-mono-t text-t-green">{rec?.total_executed ?? 0}</div>
        </div>
        <div className="bg-t-bg1 border border-t-dim rounded-xl px-4 py-3">
          <div className="text-[10px] uppercase tracking-widest text-t-muted">Promo Candidates</div>
          <div className="text-2xl font-bold font-mono-t text-violet-400">{promo?.candidates.length ?? 0}</div>
        </div>
      </div>

      {/* Red flags */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Section
          title="Red Flags — high signal, zero executed"
          icon={Siren}
          iconColor="text-t-red"
          rows={rec?.red_flags ?? []}
          emptyHint="No red flags. Every strategy with ≥50 signals also has at least one execution."
        />
        <Section
          title="Volume Bombs — > 500/day"
          icon={Flame}
          iconColor="text-amber-400"
          rows={rec?.volume_bombs ?? []}
          emptyHint="No volume bombs. All strategies under 500 signals/day."
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Section
          title="Top by Volume"
          icon={ArrowUp}
          rows={rec?.by_volume ?? []}
          emptyHint="No signal activity in this window."
        />
        <Section
          title="Top by Rejection Rate"
          icon={AlertTriangle}
          iconColor="text-amber-400"
          rows={rec?.by_reject_rate ?? []}
          emptyHint="No strategies with ≥10 analyzed signals yet."
        />
      </div>

      {/* Promotion candidates */}
      <div className="border border-violet-700/30 bg-violet-900/10 rounded-2xl p-5 space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2 text-sm font-bold text-violet-300">
            <TrendingUp size={16} /> Ready to Promote — TESTING → LIVE
          </div>
          <div className="text-[10px] text-t-muted">
            Rule: ≥ {promo?.rules.min_trades} trades · WR ≥ {promo?.rules.min_win_rate}% · EXP ≥ +{promo?.rules.min_expected_r.toFixed(2)}R
          </div>
        </div>

        {(promo?.candidates ?? []).length === 0 ? (
          <div className="text-[11px] italic text-t-muted py-2">
            No candidates yet. Strategies need real trades + winning record before they qualify.
          </div>
        ) : (
          <div className="space-y-2">
            {promo!.candidates.map((c) => (
              <div key={c.id} className="bg-t-bg1 border border-t-dim rounded-lg p-3 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-bold text-t-hi truncate">{c.name}</div>
                  <div className="text-[10px] text-t-muted font-mono">
                    {c.n_trades} trades · WR {c.win_rate.toFixed(1)}% · EXP +{c.expected_r.toFixed(3)}R
                  </div>
                  {c.why && <div className="text-[11px] text-t-green mt-0.5">{c.why}</div>}
                </div>
                <button
                  onClick={() => promoteMut.mutate(c.id)}
                  disabled={promoteMut.isPending}
                  className="flex items-center gap-1.5 bg-t-green/15 border border-t-green/40 text-t-green hover:bg-t-green/25 text-xs font-bold uppercase tracking-wider px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
                >
                  <PlayCircle size={12} /> Promote
                </button>
              </div>
            ))}
          </div>
        )}

        {(promo?.rejected ?? []).length > 0 && (
          <details className="text-[11px] text-t-muted">
            <summary className="cursor-pointer hover:text-t-hi">
              {promo!.rejected.length} testing hypotheses not yet qualified
            </summary>
            <ul className="mt-2 space-y-1 pl-2">
              {promo!.rejected.map((r) => (
                <li key={r.id} className="font-mono">
                  <span className="text-t-mid2">{r.name}</span> — {r.why_not}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      {/* Edge wisdom */}
      <div className="text-[10px] text-center italic text-t-muted py-3">
        Tune what's broken. Promote what works. Retire what doesn't. The system tells you which is which.
      </div>

      {rec?.error && (
        <div className="border border-t-red/30 bg-t-red/5 rounded p-3 text-xs text-t-red">
          <CheckCircle2 size={12} className="inline mr-1" /> Backend reported: {rec.error}
        </div>
      )}
    </div>
  );
}

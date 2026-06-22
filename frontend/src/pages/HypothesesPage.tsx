import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  PauseCircle,
  PlayCircle,
  XCircle,
  RefreshCw,
  Brain,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Skeleton, RowCardSkeleton } from "@/components/Skeleton";
import {
  getLiveHypotheses,
  promoteHypothesis,
  retireHypothesis,
  demoteHypothesisToTesting,
  type Hypothesis,
  type SystemEvent,
} from "@/api/hypotheses";

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const diffMs = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diffMs / 60_000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

function directionPill(direction: Hypothesis["direction"]) {
  const map = {
    long:  { label: "LONG",  cls: "bg-t-green/15 text-t-green border-t-green/30" },
    short: { label: "SHORT", cls: "bg-t-red/15   text-t-red   border-t-red/30" },
    both:  { label: "BOTH",  cls: "bg-violet-600/15 text-violet-300 border-violet-700/30" },
  } as const;
  const e = map[direction] ?? map.both;
  return (
    <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded border tracking-wider", e.cls)}>
      {e.label}
    </span>
  );
}

function statusPill(status: Hypothesis["status"]) {
  const map = {
    live:    { label: "LIVE",    cls: "bg-t-green/15 text-t-green border-t-green/30" },
    testing: { label: "TESTING", cls: "bg-amber-600/15 text-amber-400 border-amber-700/30" },
    retired: { label: "RETIRED", cls: "bg-t-bg2 text-t-muted border-t-dim" },
  } as const;
  const e = map[status] ?? map.testing;
  return (
    <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded border tracking-wider", e.cls)}>
      {e.label}
    </span>
  );
}

// ── Components ────────────────────────────────────────────────────────────────

function HypothesisCard({ h, onAction }: { h: Hypothesis; onAction: (id: number, action: "live" | "testing" | "retired") => void }) {
  const lastSym = h.last_trade?.side?.toUpperCase()?.[0] ?? "—";  // B / S
  const outcomeColor = h.last_trade
    ? h.last_trade.outcome === "win"
      ? "text-t-green"
      : h.last_trade.outcome === "loss"
      ? "text-t-red"
      : "text-amber-400"
    : "text-t-muted";

  return (
    <div className="border border-t-dim bg-t-bg1 rounded-xl p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-bold text-t-hi truncate">{h.name}</span>
            {directionPill(h.direction)}
            {statusPill(h.status)}
          </div>
          <div className="text-[10px] text-t-muted font-mono mt-0.5">{h.strategy_id}</div>
        </div>
        <div className="flex items-center gap-1">
          {h.status !== "live" && (
            <button
              onClick={() => onAction(h.id, "live")}
              title="Promote to LIVE"
              className="text-t-green hover:bg-t-green/10 rounded p-1"
            >
              <PlayCircle size={14} />
            </button>
          )}
          {h.status !== "testing" && (
            <button
              onClick={() => onAction(h.id, "testing")}
              title="Move to TESTING"
              className="text-amber-400 hover:bg-amber-900/20 rounded p-1"
            >
              <PauseCircle size={14} />
            </button>
          )}
          {h.status !== "retired" && (
            <button
              onClick={() => onAction(h.id, "retired")}
              title="Retire"
              className="text-t-muted hover:bg-t-bg2 rounded p-1"
            >
              <XCircle size={14} />
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-4 gap-2 text-center">
        <div>
          <div className="text-[9px] text-t-muted uppercase tracking-widest">N</div>
          <div className="text-base font-bold font-mono-t text-t-hi">{h.n_trades}</div>
        </div>
        <div>
          <div className="text-[9px] text-t-muted uppercase tracking-widest">W</div>
          <div className="text-base font-bold font-mono-t text-t-green">{h.n_wins}</div>
        </div>
        <div>
          <div className="text-[9px] text-t-muted uppercase tracking-widest">WR</div>
          <div className={cn("text-base font-bold font-mono-t",
            h.win_rate >= 50 ? "text-t-green" : h.win_rate > 0 ? "text-amber-400" : "text-t-muted")}>
            {h.win_rate.toFixed(1)}%
          </div>
        </div>
        <div>
          <div className="text-[9px] text-t-muted uppercase tracking-widest">EXP</div>
          <div className={cn("text-base font-bold font-mono-t",
            h.expected_r > 0 ? "text-t-green" : h.expected_r < 0 ? "text-t-red" : "text-t-muted")}>
            {h.expected_r > 0 ? "+" : ""}{h.expected_r.toFixed(3)}R
          </div>
        </div>
      </div>

      <div className="text-[10px] text-t-muted font-mono flex items-center gap-2 flex-wrap">
        <span>Last:</span>
        {h.last_trade ? (
          <>
            <span className="text-t-hi">{lastSym} @ {h.last_trade.price?.toFixed(2) ?? "—"}</span>
            <span className={outcomeColor}>{h.last_trade.outcome.toUpperCase()}</span>
            <span className={outcomeColor}>
              {h.last_trade.pnl_dollars >= 0 ? "+" : "-"}${Math.abs(h.last_trade.pnl_dollars).toFixed(2)}
            </span>
            <span className="text-t-muted">· {h.last_trade.session}</span>
          </>
        ) : (
          <span className="text-t-muted italic">no closed trades yet</span>
        )}
        <span className="ml-auto text-t-muted">
          sig {timeAgo(h.last_signal_ts)} ago
        </span>
      </div>
    </div>
  );
}

function FactorBar({ label, value }: { label: string; value: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  const color = pct > 66 ? "bg-t-green" : pct > 33 ? "bg-violet-500" : "bg-t-dim";
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-[10px]">
        <span className="text-t-muted font-bold uppercase tracking-widest">{label}</span>
        <span className="text-t-hi font-mono-t">{pct}</span>
      </div>
      <div className="h-1.5 bg-t-bg2 rounded overflow-hidden">
        <div className={cn("h-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function FactorExposureCard({ exposures, summary }: { exposures: Record<string, number>; summary: { live: number; testing: number; retired: number; lessons: number } }) {
  const labels: [string, string][] = [
    ["MOM", "mom"], ["TRD", "trd"], ["VOL", "vol"],
    ["FLW", "flw"], ["MR", "mr"], ["TIME", "time"], ["HYP", "hyp"],
  ];
  return (
    <div className="border border-t-dim bg-t-bg1 rounded-xl p-4 space-y-3">
      <div className="text-[10px] uppercase tracking-widest text-t-muted font-bold">FACTOR EXPOSURE</div>
      <div className="space-y-2">
        {labels.map(([label, key]) => (
          <FactorBar key={key} label={label} value={exposures[key] ?? 0} />
        ))}
      </div>
      <div className="border-t border-t-dim pt-3 mt-3 grid grid-cols-2 gap-2 text-[10px]">
        <div className="text-t-muted">LIVE</div>
        <div className="text-t-hi font-mono-t text-right">{summary.live}</div>
        <div className="text-t-muted">TESTING</div>
        <div className="text-t-hi font-mono-t text-right">{summary.testing}</div>
        <div className="text-t-muted">RETIRED</div>
        <div className="text-t-hi font-mono-t text-right">{summary.retired}</div>
        <div className="text-t-muted">LESSONS</div>
        <div className="text-t-hi font-mono-t text-right">{summary.lessons}</div>
      </div>
    </div>
  );
}

function SystemEventLog({ events }: { events: SystemEvent[] }) {
  return (
    <div className="border border-t-dim bg-t-bg1 rounded-xl p-4 space-y-2">
      <div className="text-[10px] uppercase tracking-widest text-t-muted font-bold flex items-center gap-1.5">
        <Activity size={11} /> SYSTEM EVENTS
      </div>
      {events.length === 0 ? (
        <div className="text-[10px] text-t-muted italic">no events yet</div>
      ) : (
        <ul className="space-y-1.5 text-[10px] font-mono">
          {events.slice(0, 8).map((e) => (
            <li key={e.id} className="flex items-start gap-2">
              <ChevronRight size={10} className="text-t-muted flex-shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <span className="text-t-muted">{timeAgo(e.ts)} ago</span>
                <span className="text-violet-400 ml-1.5">[{e.event_type}]</span>
                <div className="text-t-hi truncate">{e.message}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function HypothesesPage() {
  const [filter, setFilter] = useState<"all" | "live" | "testing" | "retired">("all");
  const qc = useQueryClient();

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["hypotheses-live"],
    queryFn: getLiveHypotheses,
    refetchInterval: 30_000,
    staleTime: 25_000,
  });

  const mutation = useMutation({
    mutationFn: async ({ id, action }: { id: number; action: "live" | "testing" | "retired" }) => {
      if (action === "live") return promoteHypothesis(id);
      if (action === "retired") return retireHypothesis(id);
      return demoteHypothesisToTesting(id);
    },
    onSuccess: (_d, vars) => {
      toast.success(`Hypothesis ${vars.action === "live" ? "promoted to LIVE" : vars.action === "retired" ? "retired" : "moved to TESTING"}`);
      qc.invalidateQueries({ queryKey: ["hypotheses-live"] });
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? err?.message ?? "request failed";
      toast.error(`Action failed: ${typeof msg === "string" ? msg : "unknown"}`);
    },
  });

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-6 pb-24 md:pb-6 space-y-5">
        <div className="space-y-2">
          <Skeleton h="11px" w="180px" />
          <Skeleton h="28px" w="240px" />
          <Skeleton h="14px" w="55%" />
        </div>
        <Skeleton h="40px" />
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-4">
          <div className="space-y-3">
            <RowCardSkeleton /><RowCardSkeleton /><RowCardSkeleton /><RowCardSkeleton />
          </div>
          <div className="space-y-3">
            <Skeleton h="220px" />
            <Skeleton h="180px" />
          </div>
        </div>
      </div>
    );
  }

  if (!data) {
    return <div className="max-w-7xl mx-auto px-4 py-12 text-center text-t-muted">Failed to load.</div>;
  }

  const hyps = filter === "all" ? data.hypotheses : data.hypotheses.filter((h) => h.status === filter);

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 pb-24 md:pb-6 space-y-5 animate-page-in">

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <p className="text-[10px] font-semibold text-t-muted uppercase tracking-widest mb-0.5">
            // STRATEGY LAB · RESEARCH
          </p>
          <h1 className="text-2xl font-bold text-t-hi flex items-center gap-2">
            <Brain size={22} className="text-violet-400" /> Hypothesis Tracker
          </h1>
          <p className="text-t-muted text-sm mt-1">
            Each strategy is a testable hypothesis about market edge. Promote / retire as evidence accumulates.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {(["all", "live", "testing", "retired"] as const).map((k) => (
            <button
              key={k}
              onClick={() => setFilter(k)}
              className={cn(
                "text-[10px] font-bold uppercase tracking-widest px-2.5 py-1.5 rounded border transition-colors",
                filter === k
                  ? "bg-t-bg2 border-t-mid text-t-hi"
                  : "border-t-dim text-t-muted hover:text-t-hi",
              )}
            >
              {k}
            </button>
          ))}
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-1.5 bg-t-bg1 border border-t-dim hover:border-t-mid text-t-mid2 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw size={12} className={cn(isFetching && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {/* Status bar (JARVIS-style summary) */}
      <div className="border border-t-dim bg-t-bg1 rounded-xl px-4 py-2.5 text-[10px] font-mono flex items-center gap-4 flex-wrap text-t-muted">
        <span>TOTAL <span className="text-t-hi font-bold">{data.summary.total}</span></span>
        <span>LIVE <span className="text-t-green font-bold">{data.summary.live}</span></span>
        <span>TESTING <span className="text-amber-400 font-bold">{data.summary.testing}</span></span>
        <span>RETIRED <span className="text-t-muted font-bold">{data.summary.retired}</span></span>
        <span className="ml-auto">LESSONS <span className="text-violet-400 font-bold">{data.summary.lessons}</span></span>
        <span>1m FEED <span className="text-t-green font-bold">LIVE</span></span>
      </div>

      {/* Two-column layout: cards left, sidebar right */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-4">

        {/* Cards */}
        <div className="space-y-3">
          {hyps.length === 0 ? (
            <div className="border border-t-dim bg-t-bg1 rounded-xl p-8 text-center text-t-muted text-sm">
              No hypotheses match the filter.
            </div>
          ) : (
            hyps.map((h) => (
              <HypothesisCard
                key={h.id}
                h={h}
                onAction={(id, action) => mutation.mutate({ id, action })}
              />
            ))
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-3">
          <FactorExposureCard exposures={data.factor_exposures} summary={data.summary} />
          <SystemEventLog events={data.system_events} />
        </div>
      </div>

      {/* Bottom status line */}
      <div className="text-[10px] font-mono text-t-muted border-t border-t-dim pt-3">
        {new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}{" "}
        <span className="text-violet-400">[hypothesisEngine]</span> {data.summary.live} live, {data.summary.testing} in testing —{" "}
        {data.summary.total} total hypotheses tracked.
      </div>
    </div>
  );
}

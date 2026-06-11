import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { FlaskConical, Play, TrendingUp, RefreshCw, ChevronRight, CheckCircle, XCircle, AlertCircle, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  listCandidates,
  syncCandidates,
  runBacktest,
  runWfa,
  getPromotionEval,
  type Candidate,
  type CandidateState,
} from "@/api/candidates";

// ── Helpers ────────────────────────────────────────────────────────────────────

const STATE_CONFIG: Record<CandidateState, { label: string; color: string; bg: string }> = {
  CANDIDATE:       { label: "Candidate",      color: "text-zinc-400",         bg: "bg-zinc-800/60" },
  BACKTEST_QUEUED: { label: "BT Queued",       color: "text-amber-400",        bg: "bg-amber-900/30" },
  BACKTEST_DONE:   { label: "BT Done",         color: "text-blue-400",         bg: "bg-blue-900/30" },
  WFA_QUEUED:      { label: "WFA Queued",      color: "text-amber-400",        bg: "bg-amber-900/30" },
  WFA_DONE:        { label: "WFA Done",        color: "text-blue-400",         bg: "bg-blue-900/30" },
  SHADOW_PAPER:    { label: "Shadow Paper",    color: "text-purple-400",       bg: "bg-purple-900/30" },
  PROMOTED:        { label: "Promoted",        color: "text-emerald-400",      bg: "bg-emerald-900/30" },
  RETIRED:         { label: "Retired",         color: "text-zinc-600",         bg: "bg-zinc-900/30" },
};

function StateBadge({ state }: { state: CandidateState }) {
  const cfg = STATE_CONFIG[state] ?? STATE_CONFIG.CANDIDATE;
  return (
    <span className={cn("inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider", cfg.color, cfg.bg)}>
      {cfg.label}
    </span>
  );
}

function GateBadge({ passes, score }: { passes: boolean | null; score?: number }) {
  if (passes === null) return <span className="text-[10px] text-zinc-600">—</span>;
  if (passes) return (
    <span className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-400">
      <CheckCircle size={11} /> Pass {score != null ? `(${(score * 100).toFixed(0)}%)` : ""}
    </span>
  );
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-bold text-rose-400">
      <XCircle size={11} /> Fail {score != null ? `(${(score * 100).toFixed(0)}%)` : ""}
    </span>
  );
}

function fmt(v: number | null | undefined, decimals = 2): string {
  if (v == null) return "—";
  return v.toFixed(decimals);
}

// ── Gate eval row with lazy fetch ─────────────────────────────────────────────

function GateCell({ name }: { name: string }) {
  const [fetch, setFetch] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["promotion-eval", name],
    queryFn: () => getPromotionEval(name),
    enabled: fetch,
    staleTime: 30_000,
  });

  if (!fetch) {
    return (
      <button
        onClick={(e) => { e.stopPropagation(); setFetch(true); }}
        className="text-[10px] text-blue-400 hover:text-blue-300 cursor-pointer"
      >
        Check
      </button>
    );
  }
  if (isLoading) return <span className="text-[10px] text-zinc-500">…</span>;
  if (!data) return <span className="text-[10px] text-zinc-600">—</span>;
  return <GateBadge passes={data.passes} score={data.score} />;
}

// ── Action buttons ─────────────────────────────────────────────────────────────

function ActionButtons({ candidate }: { candidate: Candidate }) {
  const qc = useQueryClient();
  const [showDetail, setShowDetail] = useState(false);

  const btMut = useMutation({
    mutationFn: () => runBacktest(candidate.name, "2021-01-01", "2024-12-31"),
    onSuccess: (d) => {
      toast.success(`Backtest enqueued (job: ${d.job_id.slice(0, 8)}…)`);
      qc.invalidateQueries({ queryKey: ["candidates"] });
    },
    onError: () => toast.error("Failed to enqueue backtest"),
  });

  const wfaMut = useMutation({
    mutationFn: () => runWfa(candidate.name, 5, 1, 21),
    onSuccess: (d) => {
      toast.success(`WFA enqueued (job: ${d.job_id.slice(0, 8)}…)`);
      qc.invalidateQueries({ queryKey: ["candidates"] });
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "WFA requires BACKTEST_DONE state"),
  });

  const canBt  = !["BACKTEST_QUEUED", "WFA_QUEUED", "RETIRED"].includes(candidate.state);
  const canWfa = candidate.state === "BACKTEST_DONE";

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <button
        onClick={(e) => { e.stopPropagation(); btMut.mutate(); }}
        disabled={!canBt || btMut.isPending}
        className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-semibold bg-blue-900/40 text-blue-300 hover:bg-blue-800/50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
      >
        <Play size={9} className={btMut.isPending ? "animate-spin" : ""} />
        Backtest
      </button>
      <button
        onClick={(e) => { e.stopPropagation(); wfaMut.mutate(); }}
        disabled={!canWfa || wfaMut.isPending}
        className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-semibold bg-purple-900/40 text-purple-300 hover:bg-purple-800/50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
      >
        <TrendingUp size={9} className={wfaMut.isPending ? "animate-spin" : ""} />
        WFA
      </button>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function CandidatesPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<CandidateState | "ALL">("ALL");

  const { data, isLoading, error } = useQuery({
    queryKey: ["candidates"],
    queryFn: listCandidates,
    staleTime: 30_000,
    refetchInterval: 15_000,
  });

  const syncMut = useMutation({
    mutationFn: syncCandidates,
    onSuccess: (d) => {
      toast.success(`Synced ${d.synced} new candidates (${d.total} total)`);
      qc.invalidateQueries({ queryKey: ["candidates"] });
    },
    onError: () => toast.error("Sync failed"),
  });

  const candidates = data?.candidates ?? [];
  const filtered = filter === "ALL" ? candidates : candidates.filter((c) => c.state === filter);

  const stateCounts = candidates.reduce<Record<string, number>>((acc, c) => {
    acc[c.state] = (acc[c.state] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="max-w-[1600px] mx-auto pb-20 md:pb-6 space-y-5">

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-2">
            <FlaskConical size={20} className="text-purple-400" /> Strategy Candidates
          </h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">
            {candidates.length} candidates · backtest → WFA → shadow → promotion
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => syncMut.mutate()}
            disabled={syncMut.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] hover:border-[var(--border-emphasis)] text-[var(--text-secondary)] text-xs font-semibold rounded-lg transition-all cursor-pointer disabled:opacity-60"
          >
            <RefreshCw size={12} className={syncMut.isPending ? "animate-spin" : ""} />
            Sync candidates/
          </button>
        </div>
      </div>

      {/* State summary pills */}
      <div className="flex flex-wrap gap-2">
        {(["ALL", "CANDIDATE", "BACKTEST_DONE", "WFA_DONE", "SHADOW_PAPER", "PROMOTED", "RETIRED"] as const).map((s) => {
          const count = s === "ALL" ? candidates.length : (stateCounts[s] ?? 0);
          const cfg = s === "ALL" ? null : STATE_CONFIG[s];
          return (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all cursor-pointer",
                filter === s
                  ? "bg-[var(--bg-elevated)] border-[var(--border-emphasis)] text-[var(--text-primary)]"
                  : "bg-transparent border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
              )}
            >
              {s === "ALL" ? "All" : (cfg?.label ?? s)}
              <span className={cn("text-[10px] font-bold", filter === s ? "text-[var(--text-primary)]" : "opacity-60")}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Table */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-[var(--text-tertiary)] text-sm gap-2">
            <Clock size={14} className="animate-spin" /> Loading candidates…
          </div>
        ) : error ? (
          <div className="flex items-center justify-center py-20 text-rose-400 text-sm gap-2">
            <AlertCircle size={14} /> Failed to load — sync candidates first
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 gap-3 text-[var(--text-tertiary)]">
            <FlaskConical size={32} className="opacity-30" />
            <p className="text-sm">No candidates yet — click <strong>Sync candidates/</strong> to import</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/40">
                  {["Name", "State", "Backtest", "WFE", "DSR", "OOS Sharpe", "Gate", "Actions"].map((h) => (
                    <th key={h} className={cn(
                      "px-4 py-3 font-semibold text-[var(--text-tertiary)] tracking-wider uppercase text-[10px]",
                      h === "Name" || h === "Actions" ? "text-left" : "text-center"
                    )}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((c, i) => {
                  const bt = c.latest_backtest;
                  const wfa = c.latest_wfa;
                  return (
                    <tr
                      key={c.id}
                      className={cn(
                        "border-b border-[var(--border-subtle)]/40 hover:bg-[var(--bg-elevated-2)]/30 transition-colors",
                        i % 2 === 0 ? "" : "bg-[var(--bg-elevated-2)]/15"
                      )}
                    >
                      {/* Name */}
                      <td className="px-4 py-3">
                        <div className="font-mono font-semibold text-[var(--text-primary)] text-[11px]">
                          {c.name.replace(/_/g, " ")}
                        </div>
                        <div className="text-[9px] text-[var(--text-tertiary)] mt-0.5 font-mono truncate max-w-[160px]">
                          {c.file_path.split("/").pop()}
                        </div>
                      </td>

                      {/* State */}
                      <td className="px-4 py-3 text-center">
                        <StateBadge state={c.state} />
                      </td>

                      {/* Backtest (net sharpe) */}
                      <td className="px-4 py-3 text-center">
                        {bt ? (
                          <div>
                            <span className={cn("font-mono font-bold text-[11px]", (bt.net_sharpe ?? 0) >= 1 ? "text-emerald-400" : (bt.net_sharpe ?? 0) >= 0.5 ? "text-amber-400" : "text-rose-400")}>
                              {fmt(bt.net_sharpe)}
                            </span>
                            <div className="text-[9px] text-[var(--text-tertiary)]">sharpe</div>
                          </div>
                        ) : <span className="text-zinc-600">—</span>}
                      </td>

                      {/* WFE */}
                      <td className="px-4 py-3 text-center">
                        {wfa?.wfe != null ? (
                          <span className={cn("font-mono font-bold text-[11px]", wfa.wfe >= 0.5 ? "text-emerald-400" : "text-rose-400")}>
                            {fmt(wfa.wfe)}
                          </span>
                        ) : <span className="text-zinc-600">—</span>}
                      </td>

                      {/* DSR */}
                      <td className="px-4 py-3 text-center">
                        {wfa?.dsr != null ? (
                          <span className={cn("font-mono font-bold text-[11px]", wfa.dsr >= 0.9 ? "text-emerald-400" : "text-amber-400")}>
                            {fmt(wfa.dsr)}
                          </span>
                        ) : <span className="text-zinc-600">—</span>}
                      </td>

                      {/* OOS Sharpe */}
                      <td className="px-4 py-3 text-center">
                        {wfa?.aggregate_oos_sharpe != null ? (
                          <span className={cn("font-mono font-bold text-[11px]", wfa.aggregate_oos_sharpe >= 0.75 ? "text-emerald-400" : "text-rose-400")}>
                            {fmt(wfa.aggregate_oos_sharpe)}
                          </span>
                        ) : <span className="text-zinc-600">—</span>}
                      </td>

                      {/* Gate status (lazy) */}
                      <td className="px-4 py-3 text-center">
                        {["WFA_DONE", "SHADOW_PAPER", "PROMOTED"].includes(c.state)
                          ? <GateCell name={c.name} />
                          : <span className="text-zinc-600 text-[10px]">—</span>
                        }
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-3">
                        <ActionButtons candidate={c} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="text-[10px] text-[var(--text-tertiary)] text-center">
        Gate status: WFE ≥ 0.50 · OOS Sharpe ≥ 0.75 · DSR ≥ 0.90 · PBO ≤ 0.10 · Net Sharpe ≥ 0.50 · Shadow ≥ 63 days.
        Promotion gates are recommendations. Manual YAML update required to allocate capital.
      </p>
    </div>
  );
}

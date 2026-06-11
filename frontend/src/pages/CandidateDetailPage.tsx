import { useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowLeft, FlaskConical, CheckCircle2, XCircle, AlertTriangle,
  Play, TrendingUp, Clock, ChevronRight, ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getCandidate, getBacktestHistory, getWfaHistory, getPromotionEval, promoteCandidate, runBacktest, runWfa,
  type CandidateState, type BacktestRunSummary, type WfaRunSummary,
} from "@/api/candidates";

// ── Types ──────────────────────────────────────────────────────────────────────

type Tab = "overview" | "backtest" | "wfa" | "promotion" | "source";

const STATE_CONFIG: Record<CandidateState, { label: string; color: string; bg: string }> = {
  CANDIDATE:       { label: "Candidate",    color: "text-zinc-400",    bg: "bg-zinc-800/60" },
  BACKTEST_QUEUED: { label: "BT Queued",    color: "text-amber-400",   bg: "bg-amber-900/30" },
  BACKTEST_DONE:   { label: "BT Done",      color: "text-blue-400",    bg: "bg-blue-900/30" },
  WFA_QUEUED:      { label: "WFA Queued",   color: "text-amber-400",   bg: "bg-amber-900/30" },
  WFA_DONE:        { label: "WFA Done",     color: "text-blue-400",    bg: "bg-blue-900/30" },
  SHADOW_PAPER:    { label: "Shadow Paper", color: "text-purple-400",  bg: "bg-purple-900/30" },
  PROMOTED:        { label: "Promoted",     color: "text-emerald-400", bg: "bg-emerald-900/30" },
  RETIRED:         { label: "Retired",      color: "text-zinc-600",    bg: "bg-zinc-900/30" },
};

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined, d = 2): string {
  return v == null ? "—" : v.toFixed(d);
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  try { return new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }); }
  catch { return s; }
}

function StateBadge({ state }: { state: CandidateState }) {
  const cfg = STATE_CONFIG[state] ?? STATE_CONFIG.CANDIDATE;
  return (
    <span className={cn("inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider", cfg.color, cfg.bg)}>
      {cfg.label}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    queued:  "text-amber-400 bg-amber-900/30",
    running: "text-blue-400 bg-blue-900/30",
    done:    "text-emerald-400 bg-emerald-900/30",
    failed:  "text-rose-400 bg-rose-900/30",
  };
  return (
    <span className={cn("inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider", map[status] ?? "text-zinc-400 bg-zinc-800/60")}>
      {status === "running" && <Clock size={9} className="animate-spin mr-1" />}
      {status}
    </span>
  );
}

function MetricCard({ label, value, sub, pass }: { label: string; value: string; sub?: string; pass?: boolean }) {
  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 flex flex-col gap-1">
      <p className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">{label}</p>
      <p className={cn("text-xl font-bold font-mono-t tabular-nums", pass === true ? "text-emerald-400" : pass === false ? "text-rose-400" : "text-[var(--text-primary)]")}>
        {value}
      </p>
      {sub && <p className="text-[10px] text-[var(--text-tertiary)]">{sub}</p>}
    </div>
  );
}

// ── Overview tab ──────────────────────────────────────────────────────────────

function OverviewTab({ candidateName, state, latestBt, latestWfa, onRunBacktest, onRunWfa, isRunningBt, isRunningWfa }: {
  candidateName: string;
  state: CandidateState;
  latestBt: BacktestRunSummary | null;
  latestWfa: WfaRunSummary | null;
  onRunBacktest: () => void;
  onRunWfa: () => void;
  isRunningBt: boolean;
  isRunningWfa: boolean;
}) {
  const canBt  = !["BACKTEST_QUEUED", "WFA_QUEUED", "RETIRED"].includes(state);
  const canWfa = state === "BACKTEST_DONE";

  return (
    <div className="space-y-6">
      {/* Latest backtest summary */}
      <section>
        <h3 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-3">Latest Backtest</h3>
        {latestBt ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <MetricCard label="Net Sharpe" value={fmt(latestBt.net_sharpe)} pass={latestBt.net_sharpe != null ? latestBt.net_sharpe >= 0.5 : undefined} />
            <MetricCard label="Max Drawdown" value={latestBt.max_drawdown_pct != null ? `${fmt(latestBt.max_drawdown_pct)}%` : "—"} />
            <MetricCard label="Win Rate" value={latestBt.win_rate != null ? `${fmt(latestBt.win_rate, 1)}%` : "—"} />
            <MetricCard label="Trades" value={latestBt.n_trades != null ? String(latestBt.n_trades) : "—"} />
          </div>
        ) : (
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-6 flex flex-col items-center gap-3 text-center">
            <FlaskConical size={28} className="text-zinc-600" />
            <p className="text-sm text-[var(--text-tertiary)]">Not backtested yet</p>
            <button
              onClick={onRunBacktest}
              disabled={!canBt || isRunningBt}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-900/40 text-blue-300 text-xs font-semibold rounded-lg hover:bg-blue-800/50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
            >
              <Play size={11} className={isRunningBt ? "animate-spin" : ""} />
              Run Backtest
            </button>
          </div>
        )}
        {latestBt && (
          <div className="mt-2 flex items-center justify-between">
            <span className="text-[10px] text-[var(--text-tertiary)]">
              {latestBt.start_date} — {latestBt.end_date} · <StatusBadge status={latestBt.status} />
            </span>
            <Link to={`/candidates/${candidateName}/backtest/${latestBt.job_id}`} className="text-[10px] text-blue-400 hover:text-blue-300 flex items-center gap-0.5">
              View full result <ChevronRight size={11} />
            </Link>
          </div>
        )}
      </section>

      {/* Latest WFA summary */}
      <section>
        <h3 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-3">Latest WFA</h3>
        {latestWfa ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <MetricCard label="WFE" value={fmt(latestWfa.wfe)} pass={latestWfa.wfe != null ? latestWfa.wfe >= 0.5 : undefined} />
            <MetricCard label="PBO" value={fmt(latestWfa.pbo)} pass={latestWfa.pbo != null ? latestWfa.pbo <= 0.1 : undefined} />
            <MetricCard label="DSR" value={fmt(latestWfa.dsr)} pass={latestWfa.dsr != null ? latestWfa.dsr >= 0.9 : undefined} />
            <MetricCard label="OOS Sharpe" value={fmt(latestWfa.aggregate_oos_sharpe)} pass={latestWfa.aggregate_oos_sharpe != null ? latestWfa.aggregate_oos_sharpe >= 0.75 : undefined} />
          </div>
        ) : (
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-6 flex flex-col items-center gap-3 text-center">
            <TrendingUp size={28} className="text-zinc-600" />
            <p className="text-sm text-[var(--text-tertiary)]">
              {state === "BACKTEST_DONE" ? "Ready for WFA" : "Backtest required first"}
            </p>
            {canWfa && (
              <button
                onClick={onRunWfa}
                disabled={isRunningWfa}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-900/40 text-purple-300 text-xs font-semibold rounded-lg hover:bg-purple-800/50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
              >
                <TrendingUp size={11} className={isRunningWfa ? "animate-spin" : ""} />
                Run WFA
              </button>
            )}
          </div>
        )}
        {latestWfa && (
          <div className="mt-2 flex items-center justify-between">
            <span className="text-[10px] text-[var(--text-tertiary)]">
              IS {latestWfa.is_years}y / OOS {latestWfa.oos_years}y · <StatusBadge status={latestWfa.status} />
            </span>
            <Link to={`/candidates/${candidateName}/wfa/${latestWfa.job_id}`} className="text-[10px] text-blue-400 hover:text-blue-300 flex items-center gap-0.5">
              View full result <ChevronRight size={11} />
            </Link>
          </div>
        )}
      </section>
    </div>
  );
}

// ── Backtest History tab ───────────────────────────────────────────────────────

function BacktestHistoryTab({ candidateName }: { candidateName: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["backtest-history", candidateName],
    queryFn: () => getBacktestHistory(candidateName),
    staleTime: 15_000,
  });
  const runs = data?.runs ?? [];

  if (isLoading) return <div className="py-12 text-center text-sm text-[var(--text-tertiary)]">Loading…</div>;

  if (runs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3 text-[var(--text-tertiary)]">
        <FlaskConical size={32} className="opacity-30" />
        <p className="text-sm">No backtest runs yet</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/40">
            {["Date", "Date Range", "Sharpe (net)", "Max DD", "Trades", "Status", ""].map((h) => (
              <th key={h} className={cn("px-4 py-3 text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider", h === "Date" || h === "" ? "text-left" : "text-center")}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.job_id} className="border-b border-[var(--border-subtle)]/40 hover:bg-[var(--bg-elevated-2)]/20 transition-colors">
              <td className="px-4 py-3 font-mono text-[11px] text-[var(--text-secondary)]">{fmtDate(r.started_at)}</td>
              <td className="px-4 py-3 text-center text-[var(--text-tertiary)]">{r.start_date ?? "—"} – {r.end_date ?? "—"}</td>
              <td className="px-4 py-3 text-center">
                {r.net_sharpe != null ? (
                  <span className={cn("font-mono font-bold", r.net_sharpe >= 1 ? "text-emerald-400" : r.net_sharpe >= 0.5 ? "text-amber-400" : "text-rose-400")}>
                    {fmt(r.net_sharpe)}
                  </span>
                ) : <span className="text-zinc-600">—</span>}
              </td>
              <td className="px-4 py-3 text-center font-mono text-[var(--text-secondary)]">
                {r.max_drawdown_pct != null ? `${fmt(r.max_drawdown_pct)}%` : "—"}
              </td>
              <td className="px-4 py-3 text-center text-[var(--text-secondary)]">{r.n_trades ?? "—"}</td>
              <td className="px-4 py-3 text-center"><StatusBadge status={r.status} /></td>
              <td className="px-4 py-3 text-right">
                {r.status === "done" && (
                  <Link to={`/candidates/${candidateName}/backtest/${r.job_id}`} className="text-[10px] text-blue-400 hover:text-blue-300 flex items-center gap-0.5 justify-end">
                    View <ExternalLink size={10} />
                  </Link>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── WFA History tab ───────────────────────────────────────────────────────────

function WfaHistoryTab({ candidateName }: { candidateName: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["wfa-history", candidateName],
    queryFn: () => getWfaHistory(candidateName),
    staleTime: 15_000,
  });
  const runs = data?.runs ?? [];

  if (isLoading) return <div className="py-12 text-center text-sm text-[var(--text-tertiary)]">Loading…</div>;

  if (runs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3 text-[var(--text-tertiary)]">
        <TrendingUp size={32} className="opacity-30" />
        <p className="text-sm">No WFA runs yet</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/40">
            {["Date", "IS Years", "OOS Years", "WFE", "PBO", "DSR", "OOS Sharpe", "Status", ""].map((h) => (
              <th key={h} className={cn("px-4 py-3 text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider", h === "Date" || h === "" ? "text-left" : "text-center")}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.job_id} className="border-b border-[var(--border-subtle)]/40 hover:bg-[var(--bg-elevated-2)]/20 transition-colors">
              <td className="px-4 py-3 font-mono text-[11px] text-[var(--text-secondary)]">{fmtDate(r.started_at)}</td>
              <td className="px-4 py-3 text-center text-[var(--text-secondary)]">{r.is_years ?? "—"}</td>
              <td className="px-4 py-3 text-center text-[var(--text-secondary)]">{r.oos_years ?? "—"}</td>
              <td className="px-4 py-3 text-center">
                {r.wfe != null ? <span className={cn("font-mono font-bold", r.wfe >= 0.5 ? "text-emerald-400" : "text-rose-400")}>{fmt(r.wfe)}</span> : <span className="text-zinc-600">—</span>}
              </td>
              <td className="px-4 py-3 text-center">
                {r.pbo != null ? <span className={cn("font-mono font-bold", r.pbo <= 0.1 ? "text-emerald-400" : "text-rose-400")}>{fmt(r.pbo)}</span> : <span className="text-zinc-600">—</span>}
              </td>
              <td className="px-4 py-3 text-center">
                {r.dsr != null ? <span className={cn("font-mono font-bold", r.dsr >= 0.9 ? "text-emerald-400" : "text-amber-400")}>{fmt(r.dsr)}</span> : <span className="text-zinc-600">—</span>}
              </td>
              <td className="px-4 py-3 text-center">
                {r.aggregate_oos_sharpe != null ? <span className={cn("font-mono font-bold", r.aggregate_oos_sharpe >= 0.75 ? "text-emerald-400" : "text-rose-400")}>{fmt(r.aggregate_oos_sharpe)}</span> : <span className="text-zinc-600">—</span>}
              </td>
              <td className="px-4 py-3 text-center"><StatusBadge status={r.status} /></td>
              <td className="px-4 py-3 text-right">
                {r.status === "done" && (
                  <Link to={`/candidates/${candidateName}/wfa/${r.job_id}`} className="text-[10px] text-blue-400 hover:text-blue-300 flex items-center gap-0.5 justify-end">
                    View <ExternalLink size={10} />
                  </Link>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Promotion tab ─────────────────────────────────────────────────────────────

const HARD_GATES = [
  { key: "wfe",              label: "WFE",              threshold: "≥ 0.50",  pass: (v: number) => v >= 0.5  },
  { key: "oos_sharpe",       label: "OOS Sharpe",       threshold: "≥ 0.75",  pass: (v: number) => v >= 0.75 },
  { key: "dsr",              label: "DSR",              threshold: "≥ 0.90",  pass: (v: number) => v >= 0.9  },
  { key: "pbo",              label: "PBO",              threshold: "< 0.10",  pass: (v: number) => v <= 0.1  },
  { key: "net_sharpe",       label: "Net Sharpe",       threshold: "≥ 0.50",  pass: (v: number) => v >= 0.5  },
  { key: "shadow_days",      label: "Shadow Period",    threshold: "≥ 63 days", pass: (v: number) => v >= 63 },
];
const SOFT_GATES = [
  { key: "total_cost_pct",  label: "Cost Drag",         threshold: "< 30%",   pass: (v: number) => v < 30  },
];

function PromotionTab({ candidateName, state }: { candidateName: string; state: CandidateState }) {
  const qc = useQueryClient();
  const hasBacktest = !["CANDIDATE", "BACKTEST_QUEUED"].includes(state);
  const hasWfa = !["CANDIDATE", "BACKTEST_QUEUED", "BACKTEST_DONE", "WFA_QUEUED"].includes(state);

  const { data: gate, isLoading, error } = useQuery({
    queryKey: ["promotion-eval", candidateName],
    queryFn: () => getPromotionEval(candidateName),
    enabled: hasWfa,
    staleTime: 30_000,
  });

  const promoteMut = useMutation({
    mutationFn: () => promoteCandidate(candidateName),
    onSuccess: (d) => {
      toast.success(d.message);
      qc.invalidateQueries({ queryKey: ["candidate", candidateName] });
    },
    onError: (e: any) => {
      const detail = e?.response?.data?.detail;
      const msg = typeof detail === "object" ? detail?.message : detail;
      toast.error(msg || "Promotion failed — gates not met");
    },
  });

  if (!hasBacktest) {
    return (
      <div className="bg-rose-950/30 border border-rose-800/50 rounded-xl p-6 flex flex-col gap-2">
        <p className="text-rose-400 font-semibold text-sm">Backtest required</p>
        <p className="text-[var(--text-tertiary)] text-xs">Run a backtest first, then WFA, before promotion gates can be evaluated.</p>
      </div>
    );
  }

  if (!hasWfa) {
    return (
      <div className="bg-amber-950/30 border border-amber-800/50 rounded-xl p-6 flex flex-col gap-2">
        <p className="text-amber-400 font-semibold text-sm">WFA required</p>
        <p className="text-[var(--text-tertiary)] text-xs">Walk-forward analysis must be completed before promotion gates can be evaluated.</p>
      </div>
    );
  }

  if (isLoading) return <div className="py-12 text-center text-sm text-[var(--text-tertiary)]">Evaluating gates…</div>;
  if (error || !gate) return <div className="py-12 text-center text-sm text-rose-400">Failed to load gate evaluation</div>;

  return (
    <div className="space-y-5">
      {/* Hard gates */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/30">
          <p className="text-[10px] font-bold text-[var(--text-tertiary)] uppercase tracking-wider">Hard Gates — must all pass</p>
        </div>
        <div className="divide-y divide-[var(--border-subtle)]/40">
          {HARD_GATES.map(({ key, label, threshold, pass }) => {
            const val = gate.details[key] ?? null;
            const failing = gate.hard_failures.some(f => f.toLowerCase().includes(label.toLowerCase()));
            const passed = val != null ? pass(val) : null;
            return (
              <div key={key} className="flex items-center justify-between px-4 py-3">
                <div className="flex items-center gap-2">
                  {passed === true  && <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />}
                  {passed === false && <XCircle size={14} className="text-rose-400 shrink-0" />}
                  {passed === null  && <div className="w-3.5 h-3.5 rounded-full border border-zinc-600 shrink-0" />}
                  <span className="text-sm text-[var(--text-primary)]">{label}</span>
                  <span className="text-[10px] text-[var(--text-tertiary)]">{threshold}</span>
                </div>
                <span className={cn("font-mono text-sm font-bold tabular-nums", passed === true ? "text-emerald-400" : passed === false ? "text-rose-400" : "text-zinc-600")}>
                  {val != null ? (key === "shadow_days" ? `${Math.round(val)}d` : key === "total_cost_pct" ? `${fmt(val, 1)}%` : fmt(val)) : "—"}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Soft gates */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/30">
          <p className="text-[10px] font-bold text-[var(--text-tertiary)] uppercase tracking-wider">Soft Warnings — non-blocking</p>
        </div>
        <div className="divide-y divide-[var(--border-subtle)]/40">
          {SOFT_GATES.map(({ key, label, threshold, pass }) => {
            const val = gate.details[key] ?? null;
            const warning = gate.soft_warnings.some(w => w.toLowerCase().includes("cost"));
            const passed = val != null ? pass(val) : null;
            return (
              <div key={key} className="flex items-center justify-between px-4 py-3">
                <div className="flex items-center gap-2">
                  {passed === false ? <AlertTriangle size={14} className="text-amber-400 shrink-0" /> : <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />}
                  <span className="text-sm text-[var(--text-primary)]">{label}</span>
                  <span className="text-[10px] text-[var(--text-tertiary)]">{threshold}</span>
                </div>
                <span className={cn("font-mono text-sm font-bold tabular-nums", passed === false ? "text-amber-400" : "text-emerald-400")}>
                  {val != null ? `${fmt(val, 1)}%` : "—"}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Result card */}
      {gate.passes ? (
        <div className="bg-emerald-950/30 border border-emerald-700/50 rounded-xl p-6 flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={18} className="text-emerald-400" />
            <p className="text-emerald-400 font-bold text-sm">READY FOR PROMOTION</p>
          </div>
          <p className="text-[var(--text-tertiary)] text-xs">All hard gates pass. Click below to promote to T1. You'll still need to create a YAML profile and enable the bot manually.</p>
          <button
            onClick={() => promoteMut.mutate()}
            disabled={promoteMut.isPending || state === "PROMOTED"}
            className="self-start flex items-center gap-1.5 px-4 py-2 bg-emerald-700/60 hover:bg-emerald-700/80 text-emerald-200 text-xs font-bold rounded-lg disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-colors"
          >
            {promoteMut.isPending ? <Clock size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
            {state === "PROMOTED" ? "Already Promoted" : "Graduate to T1"}
          </button>
        </div>
      ) : (
        <div className="bg-rose-950/30 border border-rose-800/50 rounded-xl p-4 space-y-2">
          <p className="text-rose-400 font-bold text-sm flex items-center gap-2"><XCircle size={15} /> Not ready for promotion</p>
          {gate.hard_failures.length > 0 && (
            <ul className="list-disc list-inside text-xs text-[var(--text-tertiary)] space-y-1">
              {gate.hard_failures.map(f => <li key={f}>{f}</li>)}
            </ul>
          )}
        </div>
      )}

      <p className="text-[10px] text-[var(--text-tertiary)] text-center">
        Score: {(gate.score * 100).toFixed(0)}% · Promotion gates are enforced server-side. Manual YAML update required to allocate capital.
      </p>
    </div>
  );
}

// ── Source tab ────────────────────────────────────────────────────────────────

function SourceTab({ filePath, assetClass, style, metadataJson }: {
  filePath: string;
  assetClass: string | null;
  style: string | null;
  metadataJson: string | null;
}) {
  let meta: Record<string, unknown> | null = null;
  try { if (metadataJson) meta = JSON.parse(metadataJson); } catch {}

  return (
    <div className="space-y-5">
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-3">
        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">Strategy File</span>
          <code className="text-xs text-[var(--text-secondary)] font-mono bg-[var(--bg-elevated-2)]/60 px-2 py-1 rounded">
            {filePath}
          </code>
          <p className="text-[10px] text-zinc-600">Source code is not displayed (security boundary). Edit the file directly on the server.</p>
        </div>
        <div className="grid grid-cols-2 gap-3 pt-1">
          <div>
            <span className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">Asset Class</span>
            <p className="text-sm text-[var(--text-primary)] mt-0.5">{assetClass ?? "—"}</p>
          </div>
          <div>
            <span className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">Style</span>
            <p className="text-sm text-[var(--text-primary)] mt-0.5">{style ?? "—"}</p>
          </div>
        </div>
      </div>

      {meta && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/30">
            <p className="text-[10px] font-bold text-[var(--text-tertiary)] uppercase tracking-wider">CANDIDATE_CONFIG</p>
          </div>
          <pre className="px-4 py-4 text-[11px] text-[var(--text-secondary)] font-mono overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(meta, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function CandidateDetailPage() {
  const { candidateName } = useParams<{ candidateName: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("overview");

  const name = candidateName ?? "";

  const { data: candidate, isLoading, error } = useQuery({
    queryKey: ["candidate", name],
    queryFn: () => getCandidate(name),
    staleTime: 15_000,
    refetchInterval: (q) => {
      const state = q.state.data?.state;
      return state && ["BACKTEST_QUEUED", "WFA_QUEUED"].includes(state) ? 8_000 : false;
    },
  });

  const btMut = useMutation({
    mutationFn: () => runBacktest(name, "2021-01-01", "2024-12-31"),
    onSuccess: (d) => {
      toast.success("Backtest queued");
      qc.invalidateQueries({ queryKey: ["candidate", name] });
      qc.invalidateQueries({ queryKey: ["backtest-history", name] });
      navigate(`/candidates/${name}/backtest/${d.job_id}`);
    },
    onError: () => toast.error("Failed to enqueue backtest"),
  });

  const wfaMut = useMutation({
    mutationFn: () => runWfa(name, 5, 1, 21),
    onSuccess: (d) => {
      toast.success("WFA queued");
      qc.invalidateQueries({ queryKey: ["candidate", name] });
      qc.invalidateQueries({ queryKey: ["wfa-history", name] });
      navigate(`/candidates/${name}/wfa/${d.job_id}`);
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "WFA requires BACKTEST_DONE state"),
  });

  const TABS: { key: Tab; label: string }[] = [
    { key: "overview",  label: "Overview" },
    { key: "backtest",  label: "Backtest History" },
    { key: "wfa",       label: "WFA History" },
    { key: "promotion", label: "Promotion" },
    { key: "source",    label: "Source" },
  ];

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto pb-20 md:pb-6 space-y-4">
        <div className="animate-pulse space-y-3">
          <div className="h-6 bg-zinc-800 rounded w-48" />
          <div className="h-10 bg-zinc-800 rounded w-72" />
          <div className="grid grid-cols-4 gap-3">
            {[...Array(4)].map((_, i) => <div key={i} className="h-20 bg-zinc-800 rounded-xl" />)}
          </div>
        </div>
      </div>
    );
  }

  if (error || !candidate) {
    return (
      <div className="max-w-4xl mx-auto py-20 text-center">
        <p className="text-rose-400 text-sm">Candidate not found</p>
        <Link to="/candidates" className="mt-4 inline-block text-xs text-blue-400 hover:text-blue-300">← Back to Candidates</Link>
      </div>
    );
  }

  const stateCfg = STATE_CONFIG[candidate.state] ?? STATE_CONFIG.CANDIDATE;

  return (
    <div className="max-w-4xl mx-auto pb-20 md:pb-6 space-y-5">

      {/* Header */}
      <div className="space-y-2">
        <Link to="/candidates" className="inline-flex items-center gap-1 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors">
          <ArrowLeft size={12} /> Candidates
        </Link>
        <div className="flex items-start gap-3 flex-wrap">
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">
              {candidate.name.replace(/_/g, " ")}
            </h1>
          </div>
          <StateBadge state={candidate.state} />
        </div>

        {/* Subheader strip */}
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--text-tertiary)]">
          {candidate.asset_class && <span>Asset Class: <span className="text-[var(--text-secondary)]">{candidate.asset_class}</span></span>}
          {candidate.style && <span>Style: <span className="text-[var(--text-secondary)]">{candidate.style}</span></span>}
          <span>Created: <span className="text-[var(--text-secondary)]">{fmtDate(candidate.created_at)}</span></span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-[var(--border-subtle)] overflow-x-auto">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              "px-4 py-2.5 text-xs font-semibold whitespace-nowrap border-b-2 transition-colors cursor-pointer -mb-px",
              tab === key
                ? "border-blue-500 text-[var(--text-primary)]"
                : "border-transparent text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div>
        {tab === "overview" && (
          <OverviewTab
            candidateName={name}
            state={candidate.state}
            latestBt={candidate.latest_backtest as BacktestRunSummary | null}
            latestWfa={candidate.latest_wfa as WfaRunSummary | null}
            onRunBacktest={() => btMut.mutate()}
            onRunWfa={() => wfaMut.mutate()}
            isRunningBt={btMut.isPending}
            isRunningWfa={wfaMut.isPending}
          />
        )}
        {tab === "backtest" && <BacktestHistoryTab candidateName={name} />}
        {tab === "wfa" && <WfaHistoryTab candidateName={name} />}
        {tab === "promotion" && <PromotionTab candidateName={name} state={candidate.state} />}
        {tab === "source" && (
          <SourceTab
            filePath={candidate.file_path}
            assetClass={candidate.asset_class}
            style={candidate.style}
            metadataJson={(candidate as any).metadata_json ?? null}
          />
        )}
      </div>
    </div>
  );
}

import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Clock, AlertTriangle } from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import { cn } from "@/lib/utils";
import { getWfaResult } from "@/api/candidates";

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined, d = 2): string {
  return v == null ? "—" : v.toFixed(d);
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  try { return new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }); }
  catch { return s; }
}

// ── Walk data parsing ──────────────────────────────────────────────────────────

interface WalkEntry {
  walk: number;
  is_start?: string;
  is_end?: string;
  oos_start?: string;
  oos_end?: string;
  is_sharpe?: number | null;
  oos_sharpe?: number | null;
  wfe?: number | null;
  best_params?: Record<string, unknown>;
}

function parseWalks(json: string | null): WalkEntry[] {
  if (!json) return [];
  try {
    const parsed = JSON.parse(json);
    if (!Array.isArray(parsed)) return [];
    return parsed as WalkEntry[];
  } catch { return []; }
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SummaryCard({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 flex flex-col gap-1">
      <p className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">{label}</p>
      <p className={cn("text-xl font-bold font-mono-t tabular-nums",
        good === true ? "text-emerald-400" : good === false ? "text-rose-400" : "text-[var(--text-primary)]"
      )}>
        {value}
      </p>
    </div>
  );
}

function StatusBanner({ status, error }: { status: string; error: string | null }) {
  if (status === "done") return null;
  if (status === "failed") {
    return (
      <div className="flex items-start gap-2 bg-rose-950/30 border border-rose-800/50 rounded-xl p-4">
        <AlertTriangle size={16} className="text-rose-400 shrink-0 mt-0.5" />
        <div>
          <p className="text-rose-400 font-semibold text-sm">WFA failed</p>
          {error && <p className="text-[var(--text-tertiary)] text-xs mt-1 font-mono">{error}</p>}
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 bg-blue-950/30 border border-blue-800/50 rounded-xl p-4">
      <Clock size={14} className="text-blue-400 animate-spin shrink-0" />
      <p className="text-blue-400 text-sm font-semibold">
        {status === "running" ? "WFA is running…" : "WFA is queued…"} Auto-refreshing every 5s.
      </p>
    </div>
  );
}

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-xs shadow-lg">
      <p className="text-zinc-400 mb-1">Walk {label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} className="font-mono font-bold" style={{ color: p.fill }}>
          {p.name}: {typeof p.value === "number" ? p.value.toFixed(3) : p.value}
        </p>
      ))}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function WfaResultPage() {
  const { candidateName, jobId } = useParams<{ candidateName: string; jobId: string }>();
  const name = candidateName ?? "";
  const id   = jobId ?? "";

  const { data, isLoading, error } = useQuery({
    queryKey: ["wfa-result", name, id],
    queryFn: () => getWfaResult(name, id),
    staleTime: 5_000,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "done" || s === "failed" ? false : 5_000;
    },
  });

  const walks = useMemo(() => parseWalks(data?.walks_json ?? null), [data?.walks_json]);

  const chartData = useMemo(() =>
    walks.map(w => ({
      walk: `W${w.walk}`,
      "IS Sharpe":  w.is_sharpe  ?? 0,
      "OOS Sharpe": w.oos_sharpe ?? 0,
    })),
  [walks]);

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto pb-20 space-y-4 animate-pulse">
        <div className="h-5 bg-zinc-800 rounded w-36" />
        <div className="h-8 bg-zinc-800 rounded w-64" />
        <div className="grid grid-cols-4 gap-3">{[...Array(4)].map((_, i) => <div key={i} className="h-20 bg-zinc-800 rounded-xl" />)}</div>
        <div className="h-64 bg-zinc-800 rounded-xl" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="max-w-4xl mx-auto py-20 text-center">
        <p className="text-rose-400 text-sm">WFA result not found</p>
        <Link to={`/candidates/${name}`} className="mt-4 inline-block text-xs text-blue-400 hover:text-blue-300">← Back to {name}</Link>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto pb-20 md:pb-6 space-y-6">

      {/* Header */}
      <div className="space-y-1">
        <Link to={`/candidates/${name}`} className="inline-flex items-center gap-1 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]">
          <ArrowLeft size={12} /> {name.replace(/_/g, " ")}
        </Link>
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">
            WFA <span className="text-[var(--text-tertiary)] font-mono text-base">{id.slice(0, 8)}…</span>
          </h1>
          <span className={cn("inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider",
            data.status === "done"    ? "text-emerald-400 bg-emerald-900/30" :
            data.status === "failed"  ? "text-rose-400 bg-rose-900/30" :
            data.status === "running" ? "text-blue-400 bg-blue-900/30" :
                                        "text-amber-400 bg-amber-900/30"
          )}>
            {data.status === "running" && <Clock size={9} className="animate-spin mr-1" />}
            {data.status}
          </span>
        </div>
        <p className="text-xs text-[var(--text-tertiary)]">
          IS {data.is_years}y / OOS {data.oos_years}y / embargo {data.embargo_days}d
          {data.n_walks != null && ` · ${data.n_walks} walks`}
        </p>
      </div>

      <StatusBanner status={data.status} error={data.error_message} />

      {/* Summary cards */}
      {data.status === "done" && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <SummaryCard label="WFE" value={fmt(data.wfe)} good={data.wfe != null ? data.wfe >= 0.5 : undefined} />
            <SummaryCard label="PBO" value={fmt(data.pbo)} good={data.pbo != null ? data.pbo <= 0.1 : undefined} />
            <SummaryCard label="DSR" value={fmt(data.dsr)} good={data.dsr != null ? data.dsr >= 0.9 : undefined} />
            <SummaryCard label="N Walks" value={data.n_walks != null ? String(data.n_walks) : "—"} />
          </div>

          {/* Aggregate Sharpe */}
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: "Aggregate IS Sharpe",  value: fmt(data.aggregate_is_sharpe) },
              { label: "Aggregate OOS Sharpe", value: fmt(data.aggregate_oos_sharpe), good: data.aggregate_oos_sharpe != null ? data.aggregate_oos_sharpe >= 0.75 : undefined },
            ].map(({ label, value, good }) => (
              <div key={label} className="bg-[var(--bg-elevated)]/60 border border-[var(--border-subtle)]/60 rounded-xl px-4 py-3 flex flex-col gap-1">
                <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">{label}</p>
                <p className={cn("font-mono font-bold tabular-nums text-lg",
                  good === true ? "text-emerald-400" : good === false ? "text-rose-400" : "text-[var(--text-secondary)]"
                )}>
                  {value}
                </p>
              </div>
            ))}
          </div>

          {/* IS vs OOS bar chart */}
          {chartData.length > 0 && (
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-4">
              <p className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-4">
                IS vs OOS Sharpe per Walk
              </p>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 8 }} barCategoryGap="30%">
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="walk" tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} tickLine={false} axisLine={false} width={36} />
                  <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
                  <Legend wrapperStyle={{ fontSize: 11, color: "var(--text-tertiary)" }} />
                  <Bar dataKey="IS Sharpe"  fill="#3b82f6" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="OOS Sharpe" fill="#a78bfa" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              <p className="text-[10px] text-zinc-600 text-center mt-2">
                Decay from IS→OOS indicates overfitting risk. WFE = OOS/IS Sharpe ratio.
              </p>
            </div>
          )}

          {/* Per-walk table */}
          {walks.length > 0 && (
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
              <div className="px-4 py-3 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/30">
                <p className="text-[10px] font-bold text-[var(--text-tertiary)] uppercase tracking-wider">Per-Walk Results</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-[var(--border-subtle)]/60 bg-[var(--bg-elevated-2)]/20">
                      {["Walk", "IS Range", "OOS Range", "IS Sharpe", "OOS Sharpe", "WFE", "Best Params"].map(h => (
                        <th key={h} className={cn("px-4 py-2.5 text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider", h === "Walk" || h === "IS Range" || h === "OOS Range" || h === "Best Params" ? "text-left" : "text-center")}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {walks.map((w) => (
                      <tr key={w.walk} className="border-b border-[var(--border-subtle)]/30 hover:bg-[var(--bg-elevated-2)]/15 transition-colors">
                        <td className="px-4 py-2.5 font-mono font-bold text-[var(--text-secondary)]">W{w.walk}</td>
                        <td className="px-4 py-2.5 text-[var(--text-tertiary)]">
                          {w.is_start && w.is_end ? `${w.is_start} – ${w.is_end}` : "—"}
                        </td>
                        <td className="px-4 py-2.5 text-[var(--text-tertiary)]">
                          {w.oos_start && w.oos_end ? `${w.oos_start} – ${w.oos_end}` : "—"}
                        </td>
                        <td className="px-4 py-2.5 text-center">
                          {w.is_sharpe != null ? (
                            <span className="font-mono font-bold text-blue-400">{fmt(w.is_sharpe)}</span>
                          ) : <span className="text-zinc-600">—</span>}
                        </td>
                        <td className="px-4 py-2.5 text-center">
                          {w.oos_sharpe != null ? (
                            <span className={cn("font-mono font-bold", w.oos_sharpe >= 0.75 ? "text-emerald-400" : w.oos_sharpe >= 0 ? "text-amber-400" : "text-rose-400")}>
                              {fmt(w.oos_sharpe)}
                            </span>
                          ) : <span className="text-zinc-600">—</span>}
                        </td>
                        <td className="px-4 py-2.5 text-center">
                          {w.wfe != null ? (
                            <span className={cn("font-mono font-bold", w.wfe >= 0.5 ? "text-emerald-400" : "text-rose-400")}>{fmt(w.wfe)}</span>
                          ) : <span className="text-zinc-600">—</span>}
                        </td>
                        <td className="px-4 py-2.5 text-[var(--text-tertiary)] max-w-[180px] truncate">
                          {w.best_params ? (
                            <span className="font-mono text-[10px]">
                              {Object.entries(w.best_params).slice(0, 3).map(([k, v]) => `${k}=${v}`).join(", ")}
                            </span>
                          ) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

import { useState, type ReactNode } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle, Cpu, Gauge, RefreshCw, ShieldAlert, Activity,
  Layers, Siren, Snowflake, ScanLine, GitCompareArrows, FlaskConical,
  PlayCircle, BellRing, CheckSquare, Eraser,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { BracketFrame, SectionLabel } from "@/components/design";
import {
  getPortfolioHealth, getConcentration, getBotHeartbeats,
  getAllocationInventory, getStopAsymmetry, getDisciplineGateRate,
  getCooldownStorm, getLegacyQuarantineAudit, getDirectionalReconcile,
  getLastDryRun, runAllocatorDryRun, testOpsAlert, forceEodComplete,
  sweepStaleWatchlist, getCashFloorStatus,
  type DryRunResponse, type OpsAlertResponse,
} from "@/api/adminDiagnostics";
import { getCrossSleeveQuarantine } from "@/api/adminQuarantine";

// ─── Helpers ────────────────────────────────────────────────────────────────

const fmtTime = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch { return iso; }
};

const fmtMoney = (n: number | null | undefined): string => {
  if (n == null || isNaN(n)) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
};

const fmtCents = (c: number | null | undefined): string => {
  if (c == null) return "—";
  return fmtMoney(c / 100);
};

const fmtPct = (n: number | null | undefined, digits = 2): string => {
  if (n == null || isNaN(n)) return "—";
  return `${n.toFixed(digits)}%`;
};

const errMsg = (err: unknown): string => {
  if (!err) return "Unknown error";
  const e = err as { response?: { data?: { detail?: string; error?: string } }; message?: string };
  return e.response?.data?.detail ?? e.response?.data?.error ?? e.message ?? String(err);
};

// ─── DiagnosticCard wrapper ─────────────────────────────────────────────────

interface DiagnosticCardProps {
  title: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  lastUpdated?: string;
  isLoading?: boolean;
  isFetching?: boolean;
  error?: unknown;
  onRefetch: () => void;
  children: ReactNode;
  full?: boolean;
}

function DiagnosticCard({
  title, icon: Icon, lastUpdated, isLoading, isFetching, error, onRefetch, children, full,
}: DiagnosticCardProps) {
  return (
    <BracketFrame
      className={cn(
        "rounded-2xl p-4 bg-t-bg1 border border-t-dim flex flex-col gap-3 min-h-[200px]",
        full && "lg:col-span-2",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          <Icon size={14} className="text-t-muted mt-0.5 flex-shrink-0" />
          <div className="min-w-0">
            <SectionLabel>{title}</SectionLabel>
            <div className="text-[10px] text-t-faint font-mono-t mt-0.5">
              {lastUpdated ? `updated ${fmtTime(lastUpdated)}` : "—"}
            </div>
          </div>
        </div>
        <button
          onClick={onRefetch}
          disabled={isFetching}
          aria-label={`Refresh ${title}`}
          className="p-1 rounded border border-t-dim hover:border-t-mid text-t-mid2 hover:text-t-hi transition-colors disabled:opacity-50"
        >
          <RefreshCw size={11} className={cn(isFetching && "animate-spin")} />
        </button>
      </div>
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center text-[11px] text-t-muted font-mono-t">
          loading…
        </div>
      ) : error ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center px-3">
          <div className="text-[11px] text-t-red font-mono-t leading-snug break-all">
            {errMsg(error)}
          </div>
          <button
            onClick={onRefetch}
            disabled={isFetching}
            className="px-3 py-1 rounded-lg border border-t-mid/40 hover:border-t-mid text-t-mid2 hover:text-t-hi text-[11px] font-medium disabled:opacity-50"
          >
            {isFetching ? "Retrying…" : "Retry"}
          </button>
        </div>
      ) : (
        <div className="flex-1 min-w-0">{children}</div>
      )}
    </BracketFrame>
  );
}

// ─── Small primitives ───────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const cls = status === "ok" ? "bg-t-green/15 text-t-green border-t-green/40"
    : status === "fresh" ? "bg-t-green/15 text-t-green border-t-green/40"
    : status === "warn" ? "bg-amber-900/20 text-amber-300 border-amber-700/40"
    : status === "stale" ? "bg-t-red/15 text-t-red border-t-red/40"
    : "bg-t-bg2 text-t-muted border-t-dim";
  return (
    <span className={cn("text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border", cls)}>
      {status}
    </span>
  );
}

function Table({ headers, children }: { headers: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-[11px] font-mono-t">
        <thead>
          <tr className="text-t-muted text-[10px] uppercase tracking-wider border-b border-t-dim">
            {headers.map((h) => <th key={h} className="text-left py-1.5 px-1.5 font-semibold whitespace-nowrap">{h}</th>)}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function EmptyRow({ cols, text }: { cols: number; text: string }) {
  return (
    <tr><td colSpan={cols} className="py-4 text-center italic text-t-muted text-[11px]">{text}</td></tr>
  );
}

// ─── Card bodies ────────────────────────────────────────────────────────────

function PortfolioHealthCard({ qcRefresh }: { qcRefresh: number }) {
  const q = useQuery({
    queryKey: ["adm-portfolio-health", qcRefresh],
    queryFn: getPortfolioHealth,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  return (
    <DiagnosticCard
      title="Portfolio Health" icon={Activity}
      lastUpdated={q.data?.as_of}
      isLoading={q.isLoading} isFetching={q.isFetching} error={q.error}
      onRefetch={() => q.refetch()}
    >
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] uppercase text-t-muted tracking-wider">Status</span>
          <StatusBadge status={q.data?.status ?? "—"} />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="bg-t-bg2 border border-t-dim rounded px-2 py-1.5">
            <div className="text-[9px] uppercase text-t-muted tracking-wider">Dashboard PV</div>
            <div className="text-sm font-mono-t text-t-hi">{fmtMoney(q.data?.dashboard_pv)}</div>
          </div>
          <div className="bg-t-bg2 border border-t-dim rounded px-2 py-1.5">
            <div className="text-[9px] uppercase text-t-muted tracking-wider">Portfolio PV</div>
            <div className="text-sm font-mono-t text-t-hi">{fmtMoney(q.data?.portfolio_pv)}</div>
          </div>
          <div className="bg-t-bg2 border border-t-dim rounded px-2 py-1.5">
            <div className="text-[9px] uppercase text-t-muted tracking-wider">Strategy Lab PV</div>
            <div className="text-sm font-mono-t text-t-hi">{fmtMoney(q.data?.strategy_lab_pv)}</div>
          </div>
        </div>
        <div className="flex items-center justify-between text-[11px] pt-1">
          <span className="text-t-muted">Max divergence</span>
          <span className={cn(
            "font-mono-t font-bold",
            (q.data?.max_divergence ?? 0) > 0.01 ? "text-amber-300" : "text-t-hi",
          )}>
            {fmtPct((q.data?.max_divergence ?? 0) * 100, 3)}
          </span>
        </div>
        {q.data?.notes && <div className="text-[10px] text-t-mid2 italic pt-1">{q.data.notes}</div>}
      </div>
    </DiagnosticCard>
  );
}

function ConcentrationCard({ qcRefresh }: { qcRefresh: number }) {
  const q = useQuery({
    queryKey: ["adm-concentration", qcRefresh],
    queryFn: () => getConcentration(20),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const rows = q.data?.rows ?? [];
  const cap = q.data?.cap_pct ?? 3;
  return (
    <DiagnosticCard
      title={`Concentration — cap ${cap}%`} icon={Layers}
      lastUpdated={q.data?.as_of}
      isLoading={q.isLoading} isFetching={q.isFetching} error={q.error}
      onRefetch={() => q.refetch()}
      full
    >
      <Table headers={["symbol", "$ notional", "% fleet", "open", "flag"]}>
        {rows.length === 0 ? <EmptyRow cols={5} text="No positions." /> : rows.map((r) => (
          <tr key={r.symbol} className={cn(
            "border-b border-t-dim/40",
            r.flagged && "bg-t-red/5",
          )}>
            <td className="py-1 px-1.5 text-t-hi font-semibold">{r.symbol}</td>
            <td className="py-1 px-1.5 text-t-mid2">{fmtMoney(r.notional_dollars)}</td>
            <td className={cn("py-1 px-1.5", r.flagged ? "text-t-red font-bold" : "text-t-mid2")}>
              {fmtPct(r.pct_of_fleet, 2)}
            </td>
            <td className="py-1 px-1.5 text-t-mid2">{r.open_positions}</td>
            <td className="py-1 px-1.5">{r.flagged && <AlertTriangle size={11} className="text-t-red" />}</td>
          </tr>
        ))}
      </Table>
    </DiagnosticCard>
  );
}

function HeartbeatCard({ qcRefresh }: { qcRefresh: number }) {
  const q = useQuery({
    queryKey: ["adm-heartbeats", qcRefresh],
    queryFn: getBotHeartbeats,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const rows = q.data?.rows ?? [];
  return (
    <DiagnosticCard
      title="Bot Heartbeats" icon={Activity}
      lastUpdated={q.data?.as_of}
      isLoading={q.isLoading} isFetching={q.isFetching} error={q.error}
      onRefetch={() => q.refetch()}
      full
    >
      <Table headers={["bot", "last signal", "last scan", "cadence", "status"]}>
        {rows.length === 0 ? <EmptyRow cols={5} text="No bots reporting." /> : rows.map((r) => (
          <tr key={r.bot_name} className="border-b border-t-dim/40">
            <td className="py-1 px-1.5 text-t-hi font-semibold">{r.bot_name}</td>
            <td className="py-1 px-1.5 text-t-mid2">{fmtTime(r.last_signal_at)}</td>
            <td className="py-1 px-1.5 text-t-mid2">{fmtTime(r.last_scan_at)}</td>
            <td className="py-1 px-1.5 text-t-mid2">{r.cadence_min}m</td>
            <td className="py-1 px-1.5"><StatusBadge status={r.status} /></td>
          </tr>
        ))}
      </Table>
    </DiagnosticCard>
  );
}

function InventoryCard({ qcRefresh }: { qcRefresh: number }) {
  const q = useQuery({
    queryKey: ["adm-inventory", qcRefresh],
    queryFn: getAllocationInventory,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const rows = q.data?.rows ?? [];
  const cls = (c: string) => c === "active" ? "text-t-green"
    : c === "incubating" ? "text-violet-300"
    : c === "retired" ? "text-t-muted"
    : "text-t-red font-bold";
  return (
    <DiagnosticCard
      title="Allocation Inventory" icon={Layers}
      lastUpdated={q.data?.as_of}
      isLoading={q.isLoading} isFetching={q.isFetching} error={q.error}
      onRefetch={() => q.refetch()}
      full
    >
      <Table headers={["bot", "classification", "capital"]}>
        {rows.length === 0 ? <EmptyRow cols={3} text="No allocations." /> : rows.map((r, i) => (
          <tr key={`${r.bot_name}-${i}`} className={cn(
            "border-b border-t-dim/40",
            r.classification === "orphan" && "bg-t-red/5",
          )}>
            <td className="py-1 px-1.5 text-t-hi font-semibold">{r.bot_name}</td>
            <td className={cn("py-1 px-1.5 uppercase tracking-wider text-[10px]", cls(r.classification))}>
              {r.classification}
            </td>
            <td className="py-1 px-1.5 text-t-mid2">{fmtCents(r.capital_cents)}</td>
          </tr>
        ))}
      </Table>
    </DiagnosticCard>
  );
}

function StopAsymmetryCard({ qcRefresh }: { qcRefresh: number }) {
  const q = useQuery({
    queryKey: ["adm-stop-asymmetry", qcRefresh],
    queryFn: () => getStopAsymmetry(7),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const rows = q.data?.rows ?? [];
  return (
    <DiagnosticCard
      title="Stop-Hit Asymmetry — 7d" icon={Siren}
      lastUpdated={q.data?.as_of}
      isLoading={q.isLoading} isFetching={q.isFetching} error={q.error}
      onRefetch={() => q.refetch()}
      full
    >
      <Table headers={["bot", "closes", "stops", "stop %"]}>
        {rows.length === 0 ? <EmptyRow cols={4} text="No closes." /> : rows.map((r) => {
          const flagged = r.stop_pct > 45 && r.total_closes > 200;
          return (
            <tr key={r.bot} className={cn("border-b border-t-dim/40", flagged && "bg-t-red/5")}>
              <td className="py-1 px-1.5 text-t-hi font-semibold">{r.bot}</td>
              <td className="py-1 px-1.5 text-t-mid2">{r.total_closes}</td>
              <td className="py-1 px-1.5 text-t-mid2">{r.stops}</td>
              <td className={cn("py-1 px-1.5", flagged ? "text-t-red font-bold" : "text-t-mid2")}>
                {fmtPct(r.stop_pct, 1)}
              </td>
            </tr>
          );
        })}
      </Table>
    </DiagnosticCard>
  );
}

function GateRateCard({ qcRefresh }: { qcRefresh: number }) {
  const q = useQuery({
    queryKey: ["adm-gate-rate", qcRefresh],
    queryFn: () => getDisciplineGateRate(7),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const rows = q.data?.rows ?? [];
  return (
    <DiagnosticCard
      title="Discipline Gate Rate — 7d" icon={ShieldAlert}
      lastUpdated={q.data?.as_of}
      isLoading={q.isLoading} isFetching={q.isFetching} error={q.error}
      onRefetch={() => q.refetch()}
      full
    >
      <Table headers={["strategy", "total", "gated", "gate %", "state"]}>
        {rows.length === 0 ? <EmptyRow cols={5} text="No signals." /> : rows.map((r) => {
          const starved = r.gate_pct > 85;
          const unfiltered = r.gate_pct < 15;
          return (
            <tr key={r.strategy} className={cn(
              "border-b border-t-dim/40",
              starved && "bg-t-red/5",
              unfiltered && "bg-amber-900/10",
            )}>
              <td className="py-1 px-1.5 text-t-hi font-semibold">{r.strategy}</td>
              <td className="py-1 px-1.5 text-t-mid2">{r.total}</td>
              <td className="py-1 px-1.5 text-t-mid2">{r.gated}</td>
              <td className={cn(
                "py-1 px-1.5",
                starved ? "text-t-red font-bold" : unfiltered ? "text-amber-300 font-bold" : "text-t-mid2",
              )}>{fmtPct(r.gate_pct, 1)}</td>
              <td className="py-1 px-1.5 text-[10px] uppercase tracking-wider">
                {starved ? <span className="text-t-red font-bold">STARVED</span>
                  : unfiltered ? <span className="text-amber-300 font-bold">UNFILTERED</span>
                  : <span className="text-t-muted">ok</span>}
              </td>
            </tr>
          );
        })}
      </Table>
    </DiagnosticCard>
  );
}

function CooldownStormCard({ qcRefresh }: { qcRefresh: number }) {
  const q = useQuery({
    queryKey: ["adm-cooldown-storm", qcRefresh],
    queryFn: getCooldownStorm,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const rows = q.data?.rows ?? [];
  return (
    <DiagnosticCard
      title="Cooldown Storm Check" icon={Snowflake}
      lastUpdated={q.data?.as_of}
      isLoading={q.isLoading} isFetching={q.isFetching} error={q.error}
      onRefetch={() => q.refetch()}
    >
      {rows.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-[11px] text-t-green font-mono-t text-center px-3">
          No storms — all cooldowns enforced.
        </div>
      ) : (
        <Table headers={["bot", "symbol", "entries 4h"]}>
          {rows.map((r, i) => (
            <tr key={`${r.bot}-${r.symbol}-${i}`} className="border-b border-t-dim/40 bg-t-red/5">
              <td className="py-1 px-1.5 text-t-hi font-semibold">{r.bot}</td>
              <td className="py-1 px-1.5 text-t-mid2">{r.symbol}</td>
              <td className="py-1 px-1.5 text-t-red font-bold">{r.entries_4h}</td>
            </tr>
          ))}
        </Table>
      )}
    </DiagnosticCard>
  );
}

function QuarantineCard({ qcRefresh }: { qcRefresh: number }) {
  const q = useQuery({
    queryKey: ["adm-quarantine", qcRefresh],
    queryFn: getLegacyQuarantineAudit,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const rows = q.data?.rows ?? [];
  return (
    <DiagnosticCard
      title="Legacy Quarantine Audit" icon={ScanLine}
      lastUpdated={q.data?.as_of}
      isLoading={q.isLoading} isFetching={q.isFetching} error={q.error}
      onRefetch={() => q.refetch()}
      full
    >
      <Table headers={["id", "symbol", "opened", "class", "gates"]}>
        {rows.length === 0 ? <EmptyRow cols={5} text="No quarantined options." /> : rows.map((r) => (
          <tr key={r.id} className="border-b border-t-dim/40">
            <td className="py-1 px-1.5 text-t-mid2">{r.id}</td>
            <td className="py-1 px-1.5 text-t-hi font-semibold">{r.symbol}</td>
            <td className="py-1 px-1.5 text-t-mid2">{fmtTime(r.opened_at)}</td>
            <td className={cn(
              "py-1 px-1.5 text-[10px] uppercase tracking-wider font-bold",
              r.classification === "REAL" ? "text-t-green" : "text-amber-300",
            )}>{r.classification}</td>
            <td className="py-1 px-1.5 text-t-mid2">{r.gate_count}/4</td>
          </tr>
        ))}
      </Table>
    </DiagnosticCard>
  );
}

function CrossSleeveQuarantineCard({ qcRefresh }: { qcRefresh: number }) {
  const q = useQuery({
    queryKey: ["adm-cross-sleeve-quarantine", qcRefresh],
    queryFn: () => getCrossSleeveQuarantine(10),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const rows = q.data?.rows ?? [];
  const count = q.data?.unresolved_count ?? 0;
  return (
    <DiagnosticCard
      title={`Cross-Sleeve Quarantine — ${count} unresolved`}
      icon={AlertTriangle}
      lastUpdated={q.data?.as_of}
      isLoading={q.isLoading} isFetching={q.isFetching} error={q.error}
      onRefetch={() => q.refetch()}
      full
    >
      <Table headers={["bot", "declared", "actual", "symbol", "detected", "action"]}>
        {rows.length === 0
          ? <EmptyRow cols={6} text="No cross-sleeve violations." />
          : rows.map((r) => (
              <tr key={r.id} className="border-b border-t-dim/40">
                <td className="py-1 px-1.5 text-t-hi font-semibold">{r.bot_id}</td>
                <td className="py-1 px-1.5 text-t-mid2">{r.declared_asset_class}</td>
                <td className="py-1 px-1.5 text-t-red font-bold">{r.actual_asset_class}</td>
                <td className="py-1 px-1.5 text-t-mid2">{r.actual_symbol}</td>
                <td className="py-1 px-1.5 text-t-mid2">{r.detected_at?.slice(0, 16).replace("T", " ")}</td>
                <td className="py-1 px-1.5 text-t-mid2">{r.action}</td>
              </tr>
            ))
        }
      </Table>
    </DiagnosticCard>
  );
}

function DirectionalReconcileCard({ qcRefresh }: { qcRefresh: number }) {
  const q = useQuery({
    queryKey: ["adm-directional-reconcile", qcRefresh],
    queryFn: getDirectionalReconcile,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  return (
    <DiagnosticCard
      title="Equity Directional Reconcile" icon={GitCompareArrows}
      lastUpdated={q.data?.as_of}
      isLoading={q.isLoading} isFetching={q.isFetching} error={q.error}
      onRefetch={() => q.refetch()}
      full
    >
      <div className="space-y-2 text-[11px] font-mono-t">
        {q.data?.divergent && (
          <div className="bg-t-red/10 border border-t-red/30 rounded px-2 py-1 text-t-red font-bold">
            Divergent — sources disagree
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <div className="bg-t-bg2 border border-t-dim rounded p-2">
            <div className="text-[10px] uppercase text-t-muted tracking-wider mb-1">allocation.enabled</div>
            <div className="text-t-hi font-bold">{String(q.data?.allocation_enabled ?? "—")}</div>
          </div>
          <div className="bg-t-bg2 border border-t-dim rounded p-2 min-w-0">
            <div className="text-[10px] uppercase text-t-muted tracking-wider mb-1">leaderboard entry</div>
            <pre className="text-[10px] text-t-mid2 overflow-x-auto whitespace-pre-wrap break-all">
              {q.data?.leaderboard_entry ? JSON.stringify(q.data.leaderboard_entry, null, 2) : "—"}
            </pre>
          </div>
          <div className="bg-t-bg2 border border-t-dim rounded p-2 min-w-0">
            <div className="text-[10px] uppercase text-t-muted tracking-wider mb-1">per-alloc snapshot</div>
            <pre className="text-[10px] text-t-mid2 overflow-x-auto whitespace-pre-wrap break-all">
              {q.data?.per_alloc_snapshot ? JSON.stringify(q.data.per_alloc_snapshot, null, 2) : "—"}
            </pre>
          </div>
        </div>
      </div>
    </DiagnosticCard>
  );
}

function DryRunDisplay({ data }: { data: DryRunResponse }) {
  return (
    <div className="space-y-3">
      {data.warning && (
        <div className="bg-amber-900/20 border border-amber-700/40 rounded px-2 py-1.5 text-[11px] text-amber-300 font-mono-t">
          <AlertTriangle size={11} className="inline mr-1" />{data.warning}
        </div>
      )}
      <div>
        <div className="text-[10px] uppercase text-t-muted tracking-wider mb-1">Excluded bots ({data.excluded_bots?.length ?? 0})</div>
        {(data.excluded_bots ?? []).length === 0 ? <div className="text-[11px] italic text-t-muted">none</div> : (
          <ul className="space-y-0.5 text-[11px] font-mono-t">
            {(data.excluded_bots ?? []).map((b, i) => (
              <li key={i} className="flex justify-between border-b border-t-dim/40 py-0.5">
                <span className="text-t-hi font-semibold">{b.bot}</span>
                <span className="text-t-mid2">{b.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <div className="text-[10px] uppercase text-t-muted tracking-wider mb-1">Survivors ({data.survivor_bots?.length ?? 0})</div>
        {(data.survivor_bots ?? []).length === 0 ? <div className="text-[11px] italic text-t-muted">none</div> : (
          <Table headers={["bot", "realized vol", "target wt"]}>
            {(data.survivor_bots ?? []).map((b, i) => (
              <tr key={i} className="border-b border-t-dim/40">
                <td className="py-0.5 px-1.5 text-t-hi font-semibold">{b.bot}</td>
                <td className="py-0.5 px-1.5 text-t-mid2">{(b.realized_vol * 100).toFixed(2)}%</td>
                <td className="py-0.5 px-1.5 text-t-mid2">{(b.target_weight * 100).toFixed(2)}%</td>
              </tr>
            ))}
          </Table>
        )}
      </div>
      <div>
        <div className="text-[10px] uppercase text-t-muted tracking-wider mb-1">Per-sleeve summary</div>
        {(data.per_sleeve_summary ?? []).length === 0 ? <div className="text-[11px] italic text-t-muted">none</div> : (
          <Table headers={["sleeve", "gross", "net"]}>
            {(data.per_sleeve_summary ?? []).map((s, i) => (
              <tr key={i} className="border-b border-t-dim/40">
                <td className="py-0.5 px-1.5 text-t-hi font-semibold">{s.sleeve}</td>
                <td className="py-0.5 px-1.5 text-t-mid2">{(s.gross_weight * 100).toFixed(2)}%</td>
                <td className="py-0.5 px-1.5 text-t-mid2">{(s.net_weight * 100).toFixed(2)}%</td>
              </tr>
            ))}
          </Table>
        )}
      </div>
      {(data.constraint_violations ?? []).length > 0 && (
        <div>
          <div className="text-[10px] uppercase text-t-red tracking-wider mb-1 font-bold">Constraint violations</div>
          <ul className="space-y-0.5 text-[11px] font-mono-t text-t-red">
            {data.constraint_violations.map((v, i) => <li key={i}>· {v}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function DryRunCard({ qcRefresh }: { qcRefresh: number }) {
  const q = useQuery({
    queryKey: ["adm-last-dry-run", qcRefresh],
    queryFn: getLastDryRun,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  return (
    <DiagnosticCard
      title="Vol-Targeting · Last Dry-Run" icon={FlaskConical}
      lastUpdated={q.data?.as_of}
      isLoading={q.isLoading} isFetching={q.isFetching} error={q.error}
      onRefetch={() => q.refetch()}
      full
    >
      {q.data ? <DryRunDisplay data={q.data} /> : <div className="text-[11px] italic text-t-muted">No dry-run yet.</div>}
    </DiagnosticCard>
  );
}

function CashFloorCard({ qcRefresh }: { qcRefresh: number }) {
  const q = useQuery({
    queryKey: ["adm-cash-floor", qcRefresh],
    queryFn: getCashFloorStatus,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const d = q.data;
  return (
    <DiagnosticCard
      title="Cash Floor — passive SPY/QQQ" icon={Layers}
      lastUpdated={d?.as_of}
      isLoading={q.isLoading} isFetching={q.isFetching} error={q.error}
      onRefetch={() => q.refetch()}
      full
    >
      {!d || d.error ? (
        <div className="text-[11px] italic text-t-muted">{d?.error ?? "—"}</div>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-2">
            <div className="bg-t-bg2 border border-t-dim rounded px-2 py-1.5">
              <div className="text-[9px] uppercase text-t-muted tracking-wider">Fleet NAV</div>
              <div className="text-sm font-mono-t text-t-hi">{fmtCents(d.fleet_nav_cents)}</div>
            </div>
            <div className="bg-t-bg2 border border-t-dim rounded px-2 py-1.5">
              <div className="text-[9px] uppercase text-t-muted tracking-wider">Active Deploy</div>
              <div className="text-sm font-mono-t text-t-hi">{fmtCents(d.active_deployment_cents)}</div>
            </div>
            <div className="bg-t-bg2 border border-t-dim rounded px-2 py-1.5">
              <div className="text-[9px] uppercase text-t-muted tracking-wider">Cash Now</div>
              <div className="text-sm font-mono-t text-t-hi">{fmtPct(d.actual_cash_pct, 2)}</div>
            </div>
          </div>
          <div className="text-[11px] text-t-mid2 font-mono-t">
            Floor target {fmtPct(d.cash_floor_target_pct, 0)} · CF holding{" "}
            <span className="text-t-hi font-bold">{fmtCents(d.total_cash_floor_holding_cents)}</span>{" "}
            ({fmtPct(d.cash_floor_pct_of_fleet, 2)} of fleet) ·
            {d.needs_buy ? <span className="text-t-green ml-1">needs BUY</span>
              : d.needs_trim ? <span className="text-amber-300 ml-1">needs TRIM</span>
              : <span className="text-t-muted ml-1">at target</span>}
          </div>
          <Table headers={["sym", "held $", "target $", "drift $", "drift sh", "px"]}>
            {d.current_positions.map((p) => (
              <tr key={p.symbol} className="border-b border-t-dim/40">
                <td className="py-1 px-1.5 text-t-hi font-semibold">{p.symbol}</td>
                <td className="py-1 px-1.5 text-t-mid2">{fmtCents(p.notional_cents)}</td>
                <td className="py-1 px-1.5 text-t-mid2">{fmtCents(p.target_cents)}</td>
                <td className={cn(
                  "py-1 px-1.5 font-mono-t",
                  p.drift_cents > 0 ? "text-t-green" : p.drift_cents < 0 ? "text-amber-300" : "text-t-muted",
                )}>
                  {(p.drift_cents > 0 ? "+" : "") + fmtCents(p.drift_cents)}
                </td>
                <td className="py-1 px-1.5 text-t-mid2 font-mono-t">
                  {p.drift_shares == null ? "—" : (p.drift_shares > 0 ? "+" : "") + p.drift_shares.toFixed(2)}
                </td>
                <td className="py-1 px-1.5 text-t-mid2 font-mono-t">
                  {p.live_price_usd == null ? "—" : `$${p.live_price_usd.toFixed(2)}`}
                </td>
              </tr>
            ))}
          </Table>
        </div>
      )}
    </DiagnosticCard>
  );
}

function RunDryRunCard() {
  const qc = useQueryClient();
  const [result, setResult] = useState<DryRunResponse | null>(null);
  const m = useMutation({
    mutationFn: runAllocatorDryRun,
    onSuccess: (data) => {
      setResult(data);
      qc.invalidateQueries({ queryKey: ["adm-last-dry-run"] });
      toast.success("Dry-run complete");
    },
    onError: (err) => toast.error(`Dry-run failed: ${errMsg(err)}`),
  });
  return (
    <BracketFrame className="rounded-2xl p-4 bg-t-bg1 border border-t-dim flex flex-col gap-3 min-h-[200px] lg:col-span-2">
      <div className="flex items-start gap-2">
        <PlayCircle size={14} className="text-t-muted mt-0.5" />
        <div>
          <SectionLabel>Allocator · Run Dry-Run Now</SectionLabel>
          <div className="text-[10px] text-t-faint font-mono-t mt-0.5">Triggers vol-targeting calc without applying changes</div>
        </div>
      </div>
      <div>
        <button
          onClick={() => m.mutate()}
          disabled={m.isPending}
          className="flex items-center gap-1.5 bg-t-bg2 border border-t-mid hover:border-t-hi text-t-hi text-xs font-bold uppercase tracking-wider px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
        >
          <PlayCircle size={12} /> {m.isPending ? "Running…" : "Run Dry-Run"}
        </button>
      </div>
      {result && <DryRunDisplay data={result} />}
      {m.isError && (
        <div className="text-[11px] text-t-red font-mono-t">{errMsg(m.error)}</div>
      )}
    </BracketFrame>
  );
}

function OpsAlertTestCard() {
  const [result, setResult] = useState<OpsAlertResponse | null>(null);
  const [lastSev, setLastSev] = useState<string>("");
  const m = useMutation({
    mutationFn: (sev: "info" | "warn" | "critical") => testOpsAlert(sev),
    onSuccess: (data, sev) => {
      setResult(data);
      setLastSev(sev);
      toast.success(`Sent ${sev} test alert`);
    },
    onError: (err) => toast.error(`Alert test failed: ${errMsg(err)}`),
  });
  const sevCls = (s: string) => s === "info" ? "border-t-mid text-t-mid2"
    : s === "warn" ? "border-amber-700/40 text-amber-300"
    : "border-t-red/40 text-t-red";
  return (
    <BracketFrame className="rounded-2xl p-4 bg-t-bg1 border border-t-dim flex flex-col gap-3 min-h-[200px]">
      <div className="flex items-start gap-2">
        <BellRing size={14} className="text-t-muted mt-0.5" />
        <div>
          <SectionLabel>Ops Alert · Test Webhook</SectionLabel>
          <div className="text-[10px] text-t-faint font-mono-t mt-0.5">Confirms env var + Discord routing</div>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {(["info", "warn", "critical"] as const).map((sev) => (
          <button
            key={sev}
            onClick={() => m.mutate(sev)}
            disabled={m.isPending}
            className={cn(
              "text-[11px] font-bold uppercase tracking-wider px-3 py-1.5 rounded-lg border transition-colors hover:bg-t-bg2 disabled:opacity-50",
              sevCls(sev),
            )}
          >
            {sev}
          </button>
        ))}
      </div>
      {result && (
        <div className="bg-t-bg2 border border-t-dim rounded p-2">
          <div className="text-[10px] uppercase text-t-muted tracking-wider mb-1">Response · {lastSev}</div>
          <pre className="text-[10px] text-t-mid2 overflow-x-auto whitespace-pre-wrap break-all">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
      {m.isError && <div className="text-[11px] text-t-red font-mono-t">{errMsg(m.error)}</div>}
    </BracketFrame>
  );
}

function ForceCompleteCard({ qcRefresh }: { qcRefresh: number }) {
  // Use portfolio-health to detect "halted today-row" — if status !== "ok" or notes mention halt
  const health = useQuery({
    queryKey: ["adm-portfolio-health-gate", qcRefresh],
    queryFn: getPortfolioHealth,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const halted = health.data?.status === "warn" || (health.data?.notes ?? "").toLowerCase().includes("halt");
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => forceEodComplete(reason),
    onSuccess: () => {
      toast.success("EOD force-complete dispatched");
      setReason("");
    },
    onError: (err) => toast.error(`Force-complete failed: ${errMsg(err)}`),
  });
  const enabled = halted && reason.trim().length >= 5 && !m.isPending;
  return (
    <BracketFrame className="rounded-2xl p-4 bg-t-bg1 border border-t-dim flex flex-col gap-3 min-h-[200px]">
      <div className="flex items-start gap-2">
        <CheckSquare size={14} className="text-t-muted mt-0.5" />
        <div>
          <SectionLabel>EOD Force-Complete</SectionLabel>
          <div className="text-[10px] text-t-faint font-mono-t mt-0.5">
            {halted ? "halted today-row detected" : "nav_history clean — disabled"}
          </div>
        </div>
      </div>
      <textarea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Reason (min 5 chars)…"
        rows={3}
        className="w-full bg-t-bg2 border border-t-dim rounded p-2 text-[11px] font-mono-t text-t-hi placeholder:text-t-faint focus:outline-none focus:border-t-mid resize-none"
      />
      <button
        onClick={() => m.mutate()}
        disabled={!enabled}
        className="flex items-center gap-1.5 bg-t-red/10 border border-t-red/40 text-t-red hover:bg-t-red/20 text-xs font-bold uppercase tracking-wider px-3 py-1.5 rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed self-start"
      >
        <CheckSquare size={12} /> {m.isPending ? "Sending…" : "Force Complete"}
      </button>
      {m.isError && <div className="text-[11px] text-t-red font-mono-t">{errMsg(m.error)}</div>}
    </BracketFrame>
  );
}

function WatchlistSweepCard() {
  const [result, setResult] = useState<{ removed_count: number; removed?: string[] } | null>(null);
  const m = useMutation({
    mutationFn: sweepStaleWatchlist,
    onSuccess: (data) => {
      setResult(data);
      toast.success(`Removed ${data.removed_count} stale entries`);
    },
    onError: (err) => toast.error(`Sweep failed: ${errMsg(err)}`),
  });
  return (
    <BracketFrame className="rounded-2xl p-4 bg-t-bg1 border border-t-dim flex flex-col gap-3 min-h-[200px]">
      <div className="flex items-start gap-2">
        <Eraser size={14} className="text-t-muted mt-0.5" />
        <div>
          <SectionLabel>Watchlist · Sweep Stale</SectionLabel>
          <div className="text-[10px] text-t-faint font-mono-t mt-0.5">Removes stale watchlist entries</div>
        </div>
      </div>
      <button
        onClick={() => m.mutate()}
        disabled={m.isPending}
        className="flex items-center gap-1.5 bg-t-bg2 border border-t-mid hover:border-t-hi text-t-hi text-xs font-bold uppercase tracking-wider px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50 self-start"
      >
        <Eraser size={12} /> {m.isPending ? "Sweeping…" : "Run Sweep"}
      </button>
      {result && (
        <div className="bg-t-bg2 border border-t-dim rounded p-2 text-[11px] font-mono-t">
          <div className="text-t-hi font-bold">Removed: {result.removed_count}</div>
          {result.removed && result.removed.length > 0 && (
            <div className="text-t-mid2 mt-1 break-words">{result.removed.join(", ")}</div>
          )}
        </div>
      )}
      {m.isError && <div className="text-[11px] text-t-red font-mono-t">{errMsg(m.error)}</div>}
    </BracketFrame>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function AdminDiagnosticsPage() {
  const qc = useQueryClient();
  const [qcRefresh, setQcRefresh] = useState(0);
  const asOf = new Date();

  const refreshAll = () => {
    setQcRefresh((n) => n + 1);
    qc.invalidateQueries({ predicate: (q) => Array.isArray(q.queryKey) && typeof q.queryKey[0] === "string" && q.queryKey[0].startsWith("adm-") });
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 pb-24 md:pb-6 space-y-5 animate-page-in">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <p className="text-[10px] font-semibold text-t-muted uppercase tracking-widest mb-0.5 font-mono-t">
            // ADMIN · DIAGNOSTICS
          </p>
          <h1 className="text-2xl font-bold text-t-hi flex items-center gap-2">
            <Cpu size={22} className="text-violet-400" /> Diagnostics Console
          </h1>
          <p className="text-t-muted text-sm mt-1">
            All diagnostic + admin endpoints surfaced in a single console.
          </p>
          <p className="text-t-faint text-xs mt-1 font-mono-t">
            as of {asOf.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </p>
        </div>
        <button
          onClick={refreshAll}
          className="flex items-center gap-1.5 bg-t-bg1 border border-t-dim hover:border-t-mid text-t-mid2 hover:text-t-hi text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
        >
          <RefreshCw size={12} /> Refresh all
        </button>
      </div>

      {/* Top row — health-at-a-glance */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <PortfolioHealthCard qcRefresh={qcRefresh} />
        <CooldownStormCard qcRefresh={qcRefresh} />
      </div>

      {/* Concentration + Heartbeats + Inventory */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ConcentrationCard qcRefresh={qcRefresh} />
        <HeartbeatCard qcRefresh={qcRefresh} />
        <InventoryCard qcRefresh={qcRefresh} />
        <StopAsymmetryCard qcRefresh={qcRefresh} />
        <GateRateCard qcRefresh={qcRefresh} />
        <QuarantineCard qcRefresh={qcRefresh} />
        <CrossSleeveQuarantineCard qcRefresh={qcRefresh} />
      </div>

      {/* Reconcile + Dry-run + Cash Floor */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DirectionalReconcileCard qcRefresh={qcRefresh} />
        <DryRunCard qcRefresh={qcRefresh} />
        <CashFloorCard qcRefresh={qcRefresh} />
      </div>

      {/* Actions row */}
      <div className="flex items-center gap-2 pt-2">
        <Gauge size={12} className="text-t-muted" />
        <span className="text-[10px] uppercase tracking-widest text-t-muted font-bold">Actions</span>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <RunDryRunCard />
        <OpsAlertTestCard />
        <ForceCompleteCard qcRefresh={qcRefresh} />
        <WatchlistSweepCard />
      </div>

      {/* Footer */}
      <div className="text-[10px] text-center italic text-t-muted py-3 font-mono-t">
        17 endpoints · invariants, audits, controls — one console.
      </div>
    </div>
  );
}

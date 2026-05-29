import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Database,
  ShieldCheck,
  Brain,
  RefreshCw,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

// ── API helpers ───────────────────────────────────────────────────────────────

const API_BASE = "/api/monitoring";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem("bmg_token");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${API_BASE}${path}`, { headers, ...options });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

interface HealthResult {
  db: "ok" | "error";
  api: "ok" | "error";
  latency_ms: number;
  timestamp: string;
  error?: string;
}

interface IntegrityCheck {
  name: string;
  passed: boolean;
  detail: string;
}

interface IntegrityResult {
  passed: boolean;
  checks: IntegrityCheck[];
  timestamp: string;
}

interface SentinelFinding {
  priority: "P1" | "P2" | "P3";
  title: string;
  description: string;
  action: string;
}

interface SentinelResult {
  findings: SentinelFinding[];
  generated_at: string | null;
  message?: string;
}

interface HistoryResult {
  history: HealthResult[];
}

// ── Utility components ────────────────────────────────────────────────────────

function StatusBadge({ ok, label }: { ok: boolean | null; label: string }) {
  if (ok === null) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)]">
        <Clock size={10} />
        {label}
      </span>
    );
  }
  return ok ? (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-950 text-emerald-400">
      <CheckCircle2 size={10} />
      {label}
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-red-950 text-red-400">
      <XCircle size={10} />
      {label}
    </span>
  );
}

function PriorityBadge({ priority }: { priority: "P1" | "P2" | "P3" }) {
  const colors = {
    P1: "bg-red-950 text-red-400 border-red-800",
    P2: "bg-yellow-950 text-yellow-400 border-yellow-800",
    P3: "bg-blue-950 text-blue-400 border-blue-800",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-bold border",
        colors[priority]
      )}
    >
      {priority}
    </span>
  );
}

function SectionCard({
  title,
  icon: Icon,
  children,
  className,
}: {
  title: string;
  icon: React.ElementType;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5",
        className
      )}
    >
      <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-4 flex items-center gap-2">
        <Icon size={15} className="text-[var(--accent-positive)]" />
        {title}
      </h2>
      {children}
    </div>
  );
}

function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn("animate-pulse rounded-xl bg-[var(--bg-elevated)]", className)} />
  );
}

// ── Format helpers ────────────────────────────────────────────────────────────

function fmtTimestamp(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

// ── Section: System Status Cards ──────────────────────────────────────────────

function SystemStatusSection({
  health,
  integrity,
  sentinel,
  healthLoading,
}: {
  health: HealthResult | undefined;
  integrity: IntegrityResult | undefined;
  sentinel: SentinelResult | undefined;
  healthLoading: boolean;
}) {
  const p1Count =
    sentinel?.findings.filter((f) => f.priority === "P1").length ?? 0;

  const cards = [
    {
      label: "API Health",
      icon: Activity,
      ok: health ? health.api === "ok" : null,
      sub: health ? `${health.latency_ms}ms` : "—",
      loading: healthLoading,
    },
    {
      label: "Database",
      icon: Database,
      ok: health ? health.db === "ok" : null,
      sub: health ? fmtTimestamp(health.timestamp) : "—",
      loading: healthLoading,
    },
    {
      label: "Financial Integrity",
      icon: ShieldCheck,
      ok: integrity ? integrity.passed : null,
      sub: integrity ? fmtTimestamp(integrity.timestamp) : "Not yet run",
      loading: false,
    },
    {
      label: "AI Sentinel",
      icon: Brain,
      ok: sentinel ? p1Count === 0 : null,
      sub: sentinel
        ? sentinel.findings.length === 0
          ? "No findings"
          : `${p1Count} P1 · ${sentinel.findings.length} total`
        : "Not yet run",
      loading: false,
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {cards.map(({ label, icon: Icon, ok, sub, loading }) => (
        <div
          key={label}
          className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4"
        >
          {loading ? (
            <Skeleton className="h-16" />
          ) : (
            <>
              <div className="flex items-center justify-between mb-2">
                <Icon size={16} className="text-[var(--text-tertiary)]" />
                <StatusBadge
                  ok={ok}
                  label={ok === null ? "Unknown" : ok ? "OK" : "Error"}
                />
              </div>
              <p className="text-sm font-semibold text-[var(--text-primary)]">{label}</p>
              <p className="text-[10px] text-[var(--text-tertiary)] mt-0.5 truncate">{sub}</p>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Section: Health Timeline ──────────────────────────────────────────────────

function HealthTimelineSection({ data }: { data: HistoryResult | undefined }) {
  const rows = [...(data?.history ?? [])].reverse().slice(0, 48);

  if (!data) {
    return (
      <SectionCard title="Health Timeline" icon={Clock}>
        <Skeleton className="h-48" />
      </SectionCard>
    );
  }

  if (rows.length === 0) {
    return (
      <SectionCard title="Health Timeline" icon={Clock}>
        <p className="text-[var(--text-tertiary)] text-sm">
          No health snapshots yet — checks run every 60 seconds.
        </p>
      </SectionCard>
    );
  }

  return (
    <SectionCard title="Health Timeline (last 48 checks)" icon={Clock}>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[var(--text-tertiary)] uppercase tracking-wider text-[10px] border-b border-[var(--border-subtle)]">
              <th className="text-left pb-2 font-medium">Timestamp</th>
              <th className="text-center pb-2 font-medium">API</th>
              <th className="text-center pb-2 font-medium">DB</th>
              <th className="text-right pb-2 font-medium">Latency</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr
                key={idx}
                className={cn(
                  "transition-colors hover:bg-[var(--bg-elevated-2)]/40",
                  idx % 2 === 0 ? "" : "bg-[var(--bg-elevated-2)]/20"
                )}
              >
                <td className="py-1.5 text-[var(--text-secondary)] font-mono pr-4">
                  {fmtTimestamp(row.timestamp)}
                </td>
                <td className="py-1.5 text-center">
                  {row.api === "ok" ? (
                    <CheckCircle2 size={12} className="text-emerald-400 mx-auto" />
                  ) : (
                    <XCircle size={12} className="text-red-400 mx-auto" />
                  )}
                </td>
                <td className="py-1.5 text-center">
                  {row.db === "ok" ? (
                    <CheckCircle2 size={12} className="text-emerald-400 mx-auto" />
                  ) : (
                    <XCircle size={12} className="text-red-400 mx-auto" />
                  )}
                </td>
                <td className="py-1.5 text-right font-mono text-[var(--text-tertiary)]">
                  {row.latency_ms}ms
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}

// ── Section: Financial Integrity ──────────────────────────────────────────────

function FinancialIntegritySection({
  data,
  onRefresh,
  isRefreshing,
}: {
  data: IntegrityResult | undefined;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  return (
    <SectionCard title="Financial Integrity" icon={ShieldCheck}>
      <div className="flex items-center justify-between mb-3">
        {data && (
          <div className="flex items-center gap-2">
            <StatusBadge ok={data.passed} label={data.passed ? "All Checks Pass" : "Issues Found"} />
            <span className="text-[10px] text-[var(--text-tertiary)]">
              Last run: {fmtTimestamp(data.timestamp)}
            </span>
          </div>
        )}
        {!data && <span className="text-[var(--text-tertiary)] text-sm">Not yet run</span>}
        <button
          onClick={onRefresh}
          disabled={isRefreshing}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-50 transition-colors"
        >
          <RefreshCw size={11} className={isRefreshing ? "animate-spin" : ""} />
          Run Now
        </button>
      </div>

      {!data && <Skeleton className="h-24" />}

      {data && data.checks.length === 0 && (
        <p className="text-[var(--text-tertiary)] text-sm">No checks ran.</p>
      )}

      {data && data.checks.length > 0 && (
        <div className="space-y-2">
          {data.checks.map((check, idx) => (
            <div
              key={idx}
              className={cn(
                "flex items-start gap-3 p-3 rounded-lg border",
                check.passed
                  ? "bg-emerald-950/30 border-emerald-900/50"
                  : "bg-red-950/30 border-red-900/50"
              )}
            >
              <div className="mt-0.5 shrink-0">
                {check.passed ? (
                  <CheckCircle2 size={14} className="text-emerald-400" />
                ) : (
                  <XCircle size={14} className="text-red-400" />
                )}
              </div>
              <div className="min-w-0">
                <p
                  className={cn(
                    "text-xs font-semibold",
                    check.passed ? "text-emerald-300" : "text-red-300"
                  )}
                >
                  {check.name}
                </p>
                <p className="text-[11px] text-[var(--text-tertiary)] mt-0.5 break-words">
                  {check.detail}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

// ── Section: AI Sentinel ──────────────────────────────────────────────────────

function AISentinelSection({
  data,
  onRun,
  isRunning,
}: {
  data: SentinelResult | undefined;
  onRun: () => void;
  isRunning: boolean;
}) {
  const priorityColors = {
    P1: "bg-red-950/40 border-red-900/60",
    P2: "bg-yellow-950/40 border-yellow-900/60",
    P3: "bg-blue-950/40 border-blue-900/60",
  };

  return (
    <SectionCard title="AI Sentinel Digest" icon={Brain}>
      <div className="flex items-center justify-between mb-3">
        {data?.generated_at ? (
          <span className="text-[10px] text-[var(--text-tertiary)]">
            Generated: {fmtTimestamp(data.generated_at)}
          </span>
        ) : (
          <span className="text-[var(--text-tertiary)] text-sm">
            {data?.message ?? "No sentinel run yet."}
          </span>
        )}
        <button
          onClick={onRun}
          disabled={isRunning}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-50 transition-colors"
        >
          {isRunning ? (
            <RefreshCw size={11} className="animate-spin" />
          ) : (
            <Zap size={11} />
          )}
          {isRunning ? "Running…" : "Run Sentinel"}
        </button>
      </div>

      {!data && <Skeleton className="h-32" />}

      {data && data.findings.length === 0 && (
        <div className="flex items-center gap-3 p-4 rounded-lg bg-emerald-950/30 border border-emerald-900/50">
          <CheckCircle2 size={16} className="text-emerald-400 shrink-0" />
          <p className="text-sm text-emerald-300">No findings — system looks healthy.</p>
        </div>
      )}

      {data && data.findings.length > 0 && (
        <div className="space-y-3">
          {data.findings.map((finding, idx) => (
            <div
              key={idx}
              className={cn(
                "p-4 rounded-lg border",
                priorityColors[finding.priority] ?? "bg-[var(--bg-elevated-2)] border-[var(--border-subtle)]"
              )}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <PriorityBadge priority={finding.priority} />
                <p className="text-sm font-semibold text-[var(--text-primary)]">
                  {finding.title}
                </p>
              </div>
              {finding.description && (
                <p className="text-xs text-[var(--text-secondary)] mb-1.5 leading-relaxed">
                  {finding.description}
                </p>
              )}
              {finding.action && (
                <div className="flex items-start gap-1.5">
                  <AlertTriangle size={11} className="text-[var(--text-tertiary)] mt-0.5 shrink-0" />
                  <p className="text-[11px] text-[var(--text-tertiary)] leading-relaxed">
                    {finding.action}
                  </p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MonitoringPage() {
  const queryClient = useQueryClient();
  const [integrityRefreshing, setIntegrityRefreshing] = useState(false);

  // Current health — auto-refresh every 30 s
  const { data: health, isLoading: healthLoading } = useQuery<HealthResult>({
    queryKey: ["monitoring-health"],
    queryFn: () => apiFetch<HealthResult>("/health"),
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  // Health history
  const { data: history } = useQuery<HistoryResult>({
    queryKey: ["monitoring-history"],
    queryFn: () => apiFetch<HistoryResult>("/history"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // Latest integrity result (on-demand only — populated after a run)
  const { data: integrity, refetch: refetchIntegrity } = useQuery<IntegrityResult>({
    queryKey: ["monitoring-integrity"],
    queryFn: () => apiFetch<IntegrityResult>("/integrity"),
    enabled: false,   // only fetch when explicitly triggered
    staleTime: Infinity,
  });

  // Latest sentinel result
  const { data: sentinel } = useQuery<SentinelResult>({
    queryKey: ["monitoring-sentinel-latest"],
    queryFn: () => apiFetch<SentinelResult>("/sentinel/latest"),
    staleTime: 60_000,
  });

  // Trigger sentinel mutation
  const sentinelMutation = useMutation({
    mutationFn: () =>
      apiFetch<SentinelResult>("/sentinel", { method: "POST" }),
    onSuccess: (data) => {
      queryClient.setQueryData(["monitoring-sentinel-latest"], data);
      toast.success("AI Sentinel run complete");
    },
    onError: () => {
      toast.error("Sentinel run failed — check server logs");
    },
  });

  async function handleIntegrityRefresh() {
    setIntegrityRefreshing(true);
    try {
      await refetchIntegrity();
      toast.success("Integrity check complete");
    } catch {
      toast.error("Integrity check failed");
    } finally {
      setIntegrityRefreshing(false);
    }
  }

  return (
    <div className="space-y-5 pb-10">
      {/* Page header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] flex items-center gap-2">
            <Activity size={20} className="text-[var(--accent-positive)]" />
            System Monitoring
          </h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">
            Health checks, financial integrity, and AI sentinel for BMG Capital
          </p>
        </div>
        <button
          onClick={() => {
            queryClient.invalidateQueries({ queryKey: ["monitoring-health"] });
            queryClient.invalidateQueries({ queryKey: ["monitoring-history"] });
            queryClient.invalidateQueries({ queryKey: ["monitoring-sentinel-latest"] });
          }}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
        >
          <RefreshCw size={12} />
          Refresh all
        </button>
      </div>

      {/* System status cards */}
      <SystemStatusSection
        health={health}
        integrity={integrity}
        sentinel={sentinel}
        healthLoading={healthLoading}
      />

      {/* Health timeline */}
      <HealthTimelineSection data={history} />

      {/* Bottom two sections */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <FinancialIntegritySection
          data={integrity}
          onRefresh={handleIntegrityRefresh}
          isRefreshing={integrityRefreshing}
        />

        <AISentinelSection
          data={sentinel}
          onRun={() => sentinelMutation.mutate()}
          isRunning={sentinelMutation.isPending}
        />
      </div>
    </div>
  );
}

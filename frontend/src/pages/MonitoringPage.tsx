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
  Server,
  Lock,
  Package,
  BarChart2,
  ChevronDown,
  ChevronUp,
  Filter,
  Bot,
} from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import {
  getHealth,
  getHistory,
  getIntegrity,
  triggerSentinel,
  getSentinelLatest,
  getChecks,
  getResults,
  getStatus,
  type HealthResult,
  type HistoryResult,
  type IntegrityResult,
  type SentinelResult,
  type CheckRegistryResult,
  type MonitoringResultsResponse,
  type StatusResponse,
  type CategoryStatus,
  type MonitoringResultRow,
} from "@/api/monitoring";

// ── Format helpers ────────────────────────────────────────────────────────────

function fmtTimestamp(iso: string | null | undefined): string {
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

function fmtTimeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  } catch {
    return iso ?? "—";
  }
}

// ── Shared Components ─────────────────────────────────────────────────────────

function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn("animate-pulse rounded-xl bg-[var(--bg-elevated)]", className)} />
  );
}

function SectionCard({
  title,
  icon: Icon,
  children,
  className,
  actions,
}: {
  title: string;
  icon: React.ElementType;
  children: React.ReactNode;
  className?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5",
        className
      )}
    >
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
          <Icon size={15} className="text-[var(--accent-positive)]" />
          {title}
        </h2>
        {actions}
      </div>
      {children}
    </div>
  );
}

function SeverityPill({ severity }: { severity: string }) {
  if (severity === "ok" || severity === "OK") {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-emerald-950 text-emerald-400 border border-emerald-800">
        OK
      </span>
    );
  }
  const colors: Record<string, string> = {
    P1: "bg-red-950 text-red-400 border-red-800",
    P2: "bg-amber-950 text-amber-400 border-amber-800",
    P3: "bg-blue-950 text-blue-400 border-blue-800",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-bold border",
        colors[severity] ?? "bg-slate-900 text-slate-400 border-slate-700"
      )}
    >
      {severity}
    </span>
  );
}

// ── Section 1: Status Grid ────────────────────────────────────────────────────

const CATEGORY_ICONS: Record<string, React.ElementType> = {
  infrastructure: Server,
  financial: BarChart2,
  security: Lock,
  vendors: Package,
  ai: Brain,
  compliance: ShieldCheck,
};

const CATEGORY_LABELS: Record<string, string> = {
  infrastructure: "Infrastructure",
  financial: "Financial",
  security: "Security",
  vendors: "Vendors",
  ai: "AI",
  compliance: "Compliance",
};

function StatusColorClasses(status: string) {
  switch (status) {
    case "green":
      return {
        bg: "bg-green-500/10",
        border: "border-green-500/20",
        text: "text-green-400",
        badge: "bg-green-500/20 text-green-400",
        dot: "bg-green-400",
      };
    case "red":
      return {
        bg: "bg-red-500/10",
        border: "border-red-500/20",
        text: "text-red-400",
        badge: "bg-red-500/20 text-red-400",
        dot: "bg-red-400",
      };
    case "yellow":
      return {
        bg: "bg-amber-500/10",
        border: "border-amber-500/20",
        text: "text-amber-400",
        badge: "bg-amber-500/20 text-amber-400",
        dot: "bg-amber-400",
      };
    default:
      return {
        bg: "bg-slate-500/10",
        border: "border-slate-500/20",
        text: "text-slate-400",
        badge: "bg-slate-500/20 text-slate-400",
        dot: "bg-slate-400",
      };
  }
}

function StatusGrid({ data, loading }: { data: StatusResponse | undefined; loading: boolean }) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {["infrastructure", "financial", "security", "vendors", "ai", "compliance"].map((cat) => {
          const Icon = CATEGORY_ICONS[cat] ?? Activity;
          const colors = StatusColorClasses("gray");
          return (
            <div
              key={cat}
              className={cn(
                "rounded-xl border p-4 flex flex-col gap-2",
                colors.bg,
                colors.border
              )}
            >
              <div className="flex items-center justify-between">
                <Icon size={16} className={colors.text} />
                <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded", colors.badge)}>
                  —
                </span>
              </div>
              <p className="text-xs font-semibold text-[var(--text-primary)] capitalize">{cat}</p>
              <p className="text-[10px] text-[var(--text-tertiary)]">No data yet</p>
            </div>
          );
        })}
      </div>
    );
  }

  const orderedCats = ["infrastructure", "financial", "security", "vendors", "ai", "compliance"];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      {orderedCats.map((cat) => {
        const info: CategoryStatus = data.categories[cat] ?? {
          status: "gray",
          total_checks: 0,
          checks_with_data: 0,
          failures_p1_p2: 0,
          failures_p3: 0,
          last_run: null,
        };
        const Icon = CATEGORY_ICONS[cat] ?? Activity;
        const colors = StatusColorClasses(info.status);
        const label = CATEGORY_LABELS[cat] ?? cat;

        return (
          <div
            key={cat}
            className={cn(
              "rounded-xl border p-4 flex flex-col gap-2",
              colors.bg,
              colors.border
            )}
          >
            <div className="flex items-center justify-between">
              <Icon size={16} className={colors.text} />
              <span
                className={cn(
                  "text-[10px] font-bold px-1.5 py-0.5 rounded uppercase",
                  colors.badge
                )}
              >
                {info.status}
              </span>
            </div>
            <p className="text-xs font-semibold text-[var(--text-primary)]">{label}</p>
            <div className="text-[10px] text-[var(--text-tertiary)] space-y-0.5">
              {info.failures_p1_p2 > 0 && (
                <p className="text-red-400">{info.failures_p1_p2} P1/P2 fail{info.failures_p1_p2 !== 1 ? "s" : ""}</p>
              )}
              {info.failures_p3 > 0 && (
                <p className="text-amber-400">{info.failures_p3} P3 fail{info.failures_p3 !== 1 ? "s" : ""}</p>
              )}
              {info.failures_p1_p2 === 0 && info.failures_p3 === 0 && info.checks_with_data > 0 && (
                <p className="text-green-400">All clear</p>
              )}
              <p>Last: {fmtTimeAgo(info.last_run)}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Section 2: Recent Failures ────────────────────────────────────────────────

function RecentFailuresTable({ data, loading }: { data: MonitoringResultsResponse | undefined; loading: boolean }) {
  const [expandedId, setExpandedId] = useState<number | null>(null);

  if (loading) return <Skeleton className="h-40" />;

  const rows = data?.results ?? [];

  if (rows.length === 0) {
    return (
      <div className="flex items-center gap-3 p-4 rounded-lg bg-emerald-950/30 border border-emerald-900/50">
        <CheckCircle2 size={16} className="text-emerald-400 shrink-0" />
        <p className="text-sm text-emerald-300">No failures in last 24 hours.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[var(--text-tertiary)] uppercase tracking-wider text-[10px] border-b border-[var(--border-subtle)]">
            <th className="text-left pb-2 font-medium pr-3">Time</th>
            <th className="text-left pb-2 font-medium pr-3">Check</th>
            <th className="text-left pb-2 font-medium pr-3">Severity</th>
            <th className="text-left pb-2 font-medium">Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <>
              <tr
                key={row.id}
                className="hover:bg-[var(--bg-elevated-2)]/40 cursor-pointer transition-colors"
                onClick={() => setExpandedId(expandedId === row.id ? null : row.id)}
              >
                <td className="py-2 pr-3 text-[var(--text-tertiary)] font-mono whitespace-nowrap">
                  {fmtTimeAgo(row.timestamp)}
                </td>
                <td className="py-2 pr-3 font-mono text-[var(--text-secondary)]">
                  {row.check_id}
                </td>
                <td className="py-2 pr-3">
                  <SeverityPill severity={row.severity} />
                </td>
                <td className="py-2 text-[var(--text-secondary)] max-w-xs truncate">
                  <div className="flex items-center gap-1">
                    <span className="truncate">{row.detail}</span>
                    {row.runbook && (
                      expandedId === row.id
                        ? <ChevronUp size={12} className="text-[var(--text-tertiary)] shrink-0" />
                        : <ChevronDown size={12} className="text-[var(--text-tertiary)] shrink-0" />
                    )}
                  </div>
                </td>
              </tr>
              {expandedId === row.id && row.runbook && (
                <tr key={`${row.id}-expand`} className="bg-[var(--bg-elevated-2)]/30">
                  <td colSpan={4} className="pb-3 pt-1 px-2">
                    <div className="bg-[var(--bg-elevated-2)] rounded-lg p-3 border border-[var(--border-subtle)]">
                      <p className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wide mb-1">
                        Runbook
                      </p>
                      <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                        {row.runbook}
                      </p>
                    </div>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Section 3: Check Registry ─────────────────────────────────────────────────

const FREQUENCY_ORDER = ["minute", "5min", "15min", "hourly", "daily"];

function CheckRegistryTable({ data, loading }: { data: CheckRegistryResult | undefined; loading: boolean }) {
  const [categoryFilter, setCategoryFilter] = useState<string>("all");

  if (loading) return <Skeleton className="h-64" />;

  const checks = data?.checks ?? [];
  const categories = ["all", ...Array.from(new Set(checks.map((c) => c.category))).sort()];
  const filtered = categoryFilter === "all" ? checks : checks.filter((c) => c.category === categoryFilter);

  return (
    <div>
      {/* Category filter */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <Filter size={12} className="text-[var(--text-tertiary)]" />
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setCategoryFilter(cat)}
            className={cn(
              "px-2.5 py-1 rounded-lg text-[10px] font-semibold capitalize transition-colors",
              categoryFilter === cat
                ? "bg-[var(--accent-positive)] text-white"
                : "bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            )}
          >
            {cat === "all" ? `All (${checks.length})` : cat}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[var(--text-tertiary)] uppercase tracking-wider text-[10px] border-b border-[var(--border-subtle)]">
              <th className="text-left pb-2 font-medium pr-3">Check ID</th>
              <th className="text-left pb-2 font-medium pr-3">Category</th>
              <th className="text-left pb-2 font-medium pr-3">Frequency</th>
              <th className="text-left pb-2 font-medium pr-3">Severity</th>
              <th className="text-center pb-2 font-medium">Enabled</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((check) => (
              <tr
                key={check.id}
                className="hover:bg-[var(--bg-elevated-2)]/40 transition-colors border-b border-[var(--border-subtle)]/30"
                title={check.runbook}
              >
                <td className="py-2 pr-3 font-mono text-[var(--text-secondary)]">
                  {check.id}
                </td>
                <td className="py-2 pr-3 capitalize text-[var(--text-tertiary)]">
                  {check.category}
                </td>
                <td className="py-2 pr-3 text-[var(--text-tertiary)]">
                  {check.frequency}
                </td>
                <td className="py-2 pr-3">
                  <SeverityPill severity={check.severity_on_fail} />
                </td>
                <td className="py-2 text-center">
                  {check.enabled ? (
                    <CheckCircle2 size={13} className="text-emerald-400 mx-auto" />
                  ) : (
                    <XCircle size={13} className="text-[var(--text-tertiary)] mx-auto" />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Section 4: Sentinel Panel ─────────────────────────────────────────────────

function SentinelPanel({
  data,
  onRun,
  isRunning,
}: {
  data: SentinelResult | undefined;
  onRun: () => void;
  isRunning: boolean;
}) {
  const priorityColors: Record<string, string> = {
    P1: "bg-red-950/40 border-red-900/60",
    P2: "bg-amber-950/40 border-amber-900/60",
    P3: "bg-blue-950/40 border-blue-900/60",
  };

  return (
    <div>
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
                <SeverityPill severity={finding.priority} />
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
    </div>
  );
}

// ── Legacy Health Timeline ────────────────────────────────────────────────────

function HealthTimeline({ data }: { data: HistoryResult | undefined }) {
  const rows = [...(data?.history ?? [])].reverse().slice(0, 20);

  if (!data) return <Skeleton className="h-32" />;
  if (rows.length === 0) {
    return (
      <p className="text-[var(--text-tertiary)] text-sm">
        No snapshots yet — checks run every 60 s.
      </p>
    );
  }

  return (
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
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function MonitoringPage() {
  const queryClient = useQueryClient();

  // Health (auto-refresh 30s)
  const { data: health, isLoading: healthLoading } = useQuery<HealthResult>({
    queryKey: ["monitoring-health"],
    queryFn: getHealth,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  // History (auto-refresh 60s)
  const { data: history } = useQuery<HistoryResult>({
    queryKey: ["monitoring-history"],
    queryFn: getHistory,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // Category status (auto-refresh 60s)
  const { data: statusData, isLoading: statusLoading } = useQuery<StatusResponse>({
    queryKey: ["monitoring-status"],
    queryFn: getStatus,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // Recent failures (last 24h)
  const { data: failures, isLoading: failuresLoading } = useQuery<MonitoringResultsResponse>({
    queryKey: ["monitoring-failures"],
    queryFn: () => getResults({ passed: false, hours: 24 }),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // Check registry
  const { data: registry, isLoading: registryLoading } = useQuery<CheckRegistryResult>({
    queryKey: ["monitoring-checks"],
    queryFn: getChecks,
    staleTime: 300_000,  // rarely changes
  });

  // Sentinel latest
  const { data: sentinel } = useQuery<SentinelResult>({
    queryKey: ["monitoring-sentinel-latest"],
    queryFn: getSentinelLatest,
    staleTime: 60_000,
  });

  // Sentinel mutation
  const sentinelMutation = useMutation({
    mutationFn: triggerSentinel,
    onSuccess: (data) => {
      queryClient.setQueryData(["monitoring-sentinel-latest"], data);
      toast.success("AI Sentinel run complete");
    },
    onError: () => {
      toast.error("Sentinel run failed — check server logs");
    },
  });

  const [aiOpen, setAiOpen] = useState(false);

  // Last updated timestamp
  const lastUpdated = health?.timestamp ?? statusData?.as_of;

  function refreshAll() {
    queryClient.invalidateQueries({ queryKey: ["monitoring-health"] });
    queryClient.invalidateQueries({ queryKey: ["monitoring-history"] });
    queryClient.invalidateQueries({ queryKey: ["monitoring-status"] });
    queryClient.invalidateQueries({ queryKey: ["monitoring-failures"] });
    queryClient.invalidateQueries({ queryKey: ["monitoring-sentinel-latest"] });
    toast.success("Refreshing all checks…");
  }

  return (
    <div className="space-y-5 pb-10">
      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] flex items-center gap-2">
            <Activity size={20} className="text-[var(--accent-positive)]" />
            System Monitoring
          </h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">
            Health checks, financial integrity, and AI sentinel for BMG Capital
            {lastUpdated && (
              <span className="ml-2 text-[var(--text-tertiary)]/70">
                · Updated {fmtTimeAgo(lastUpdated)}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setAiOpen(true)} className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors">
            <Bot size={12} /> Ask AI
          </button>
          <button
            onClick={refreshAll}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            <RefreshCw size={12} />
            Refresh All
          </button>
        </div>
      </div>

      {/* ── Status Grid ── */}
      <StatusGrid data={statusData} loading={statusLoading && !statusData} />

      {/* ── Recent Failures ── */}
      <SectionCard
        title={`Recent Failures (last 24h)${failures && failures.count > 0 ? ` — ${failures.count}` : ""}`}
        icon={AlertTriangle}
      >
        <RecentFailuresTable data={failures} loading={failuresLoading && !failures} />
      </SectionCard>

      {/* ── Check Registry + Sentinel in 2-col grid ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SectionCard
          title={`Check Registry${registry ? ` (${registry.total})` : ""}`}
          icon={ShieldCheck}
        >
          <CheckRegistryTable data={registry} loading={registryLoading && !registry} />
        </SectionCard>

        <SectionCard title="AI Sentinel Digest" icon={Brain}>
          <SentinelPanel
            data={sentinel}
            onRun={() => sentinelMutation.mutate()}
            isRunning={sentinelMutation.isPending}
          />
        </SectionCard>
      </div>

      {/* ── Legacy Health Timeline ── */}
      <SectionCard title="Health Timeline (last 20 checks)" icon={Clock}>
        <HealthTimeline data={history} />
      </SectionCard>

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        context="BMG Capital Monitoring — trade alerts, position monitoring, risk management"
        suggestions={[
          "What thresholds should I set for position alerts?",
          "How do I monitor for a breakout setup?",
          "What's the difference between a price alert and a technical alert?",
          "How do I set up stop-loss monitoring?",
          "What signals indicate I should exit a position?",
        ]}
      />
    </div>
  );
}

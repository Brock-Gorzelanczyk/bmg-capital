import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock,
  DollarSign,
  GitPullRequest,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Zap,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/authStore";
import { Navigate } from "react-router-dom";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SentinelHealth {
  status: string;
  sentinel_enabled: boolean;
  agents: Record<string, { running: boolean; last_run: string | null }>;
}

interface AgentEvent {
  id: number;
  agent_id: string;
  severity: string;
  category: string;
  title: string;
  affected_file: string | null;
  status: string;
  created_at: string;
  resolved_at: string | null;
}

interface AgentFix {
  id: number;
  event_id: number;
  agent_id: string;
  category: string;
  file_path: string;
  pr_url: string | null;
  pr_number: number | null;
  outcome: string;
  llm_cost_usd: number;
  created_at: string;
}

interface CircuitBreaker {
  id: number;
  file_path: string;
  pr_count_today: number;
  tripped: boolean;
  tripped_at: string | null;
  cooldown_until: string | null;
}

interface Escalation {
  id: number;
  event_id: number;
  channel_id: string;
  message_preview: string;
  resolved: boolean;
  created_at: string;
}

interface SentinelStats {
  today_cost_usd: number;
  daily_cap_usd: number;
  today_pr_count: number;
  daily_pr_cap: number;
  open_events: number;
  resolution_rate_7d: number;
}

// ── Fetch helpers ─────────────────────────────────────────────────────────────

const SENTINEL_BASE = import.meta.env.VITE_SENTINEL_URL ?? "http://localhost:8001";

async function fetchSentinel<T>(path: string): Promise<T> {
  const res = await fetch(`${SENTINEL_BASE}${path}`);
  if (!res.ok) throw new Error(`Sentinel API error: ${res.status}`);
  return res.json() as Promise<T>;
}

// ── Format helpers ────────────────────────────────────────────────────────────

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-lg bg-white/5", className)} />;
}

function Badge({ label, variant }: { label: string; variant: "green" | "red" | "amber" | "blue" | "gray" }) {
  const cls = {
    green: "bg-green-500/15 text-green-400 border-green-500/20",
    red: "bg-red-500/15 text-red-400 border-red-500/20",
    amber: "bg-amber-500/15 text-amber-400 border-amber-500/20",
    blue: "bg-blue-500/15 text-blue-400 border-blue-500/20",
    gray: "bg-white/5 text-white/50 border-white/10",
  }[variant];
  return (
    <span className={cn("inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold border", cls)}>
      {label}
    </span>
  );
}

function severityVariant(s: string): "red" | "amber" | "blue" | "gray" {
  if (s === "critical") return "red";
  if (s === "warning") return "amber";
  if (s === "info") return "blue";
  return "gray";
}

function statusVariant(s: string): "green" | "amber" | "red" | "gray" {
  if (s === "resolved") return "green";
  if (s === "open") return "amber";
  if (s === "escalated") return "red";
  return "gray";
}

function outcomeVariant(o: string): "green" | "amber" | "red" | "gray" {
  if (o === "merged" || o === "pr_opened") return "green";
  if (o === "pending") return "amber";
  if (o === "failed") return "red";
  return "gray";
}

function KpiCard({
  icon: Icon,
  label,
  value,
  sub,
  variant = "default",
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  sub?: string;
  variant?: "default" | "warn" | "danger" | "ok";
}) {
  const iconColor = {
    default: "text-blue-400",
    ok: "text-green-400",
    warn: "text-amber-400",
    danger: "text-red-400",
  }[variant];
  return (
    <div className="rounded-xl bg-[var(--bg-elevated)] border border-white/5 p-4 flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Icon className={cn("w-4 h-4", iconColor)} />
        <span className="text-xs text-white/50 font-medium">{label}</span>
      </div>
      <div className="text-2xl font-bold text-white">{value}</div>
      {sub && <div className="text-xs text-white/40">{sub}</div>}
    </div>
  );
}

function SectionHeader({ title, icon: Icon }: { title: string; icon: React.ElementType }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="w-4 h-4 text-blue-400" />
      <h2 className="text-sm font-semibold text-white/80 uppercase tracking-wider">{title}</h2>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function SentinelDashboardPage() {
  const { user } = useAuthStore();
  const [tab, setTab] = useState<"events" | "fixes" | "breakers" | "escalations">("events");

  // Gate to 32bgorzelanczyk@gmail.com only (is_admin check as backup)
  const isOwner = (user as any)?.email === "32bgorzelanczyk@gmail.com" || (user as any)?.is_admin === true;
  if (!isOwner) return <Navigate to="/dashboard" replace />;

  const { data: health, isLoading: healthLoading, refetch: refetchHealth } = useQuery<SentinelHealth>({
    queryKey: ["sentinel-health"],
    queryFn: () => fetchSentinel("/health"),
    refetchInterval: 30_000,
    retry: false,
  });

  const { data: stats, isLoading: statsLoading } = useQuery<SentinelStats>({
    queryKey: ["sentinel-stats"],
    queryFn: () => fetchSentinel("/api/sentinel/stats"),
    refetchInterval: 30_000,
    retry: false,
  });

  const { data: events, isLoading: eventsLoading } = useQuery<AgentEvent[]>({
    queryKey: ["sentinel-events"],
    queryFn: () => fetchSentinel("/api/sentinel/events?limit=50"),
    refetchInterval: 30_000,
    retry: false,
    enabled: tab === "events",
  });

  const { data: fixes, isLoading: fixesLoading } = useQuery<AgentFix[]>({
    queryKey: ["sentinel-fixes"],
    queryFn: () => fetchSentinel("/api/sentinel/fixes?limit=50"),
    refetchInterval: 60_000,
    retry: false,
    enabled: tab === "fixes",
  });

  const { data: breakers, isLoading: breakersLoading } = useQuery<CircuitBreaker[]>({
    queryKey: ["sentinel-breakers"],
    queryFn: () => fetchSentinel("/api/sentinel/circuit-breakers"),
    refetchInterval: 60_000,
    retry: false,
    enabled: tab === "breakers",
  });

  const { data: escalations, isLoading: escalationsLoading } = useQuery<Escalation[]>({
    queryKey: ["sentinel-escalations"],
    queryFn: () => fetchSentinel("/api/sentinel/escalations?limit=50"),
    refetchInterval: 60_000,
    retry: false,
    enabled: tab === "escalations",
  });

  const costPct = stats ? (stats.today_cost_usd / stats.daily_cap_usd) * 100 : 0;
  const prPct = stats ? (stats.today_pr_count / stats.daily_pr_cap) * 100 : 0;

  const tabs = [
    { id: "events" as const, label: "Open Events", icon: AlertTriangle },
    { id: "fixes" as const, label: "PRs / Fixes", icon: GitPullRequest },
    { id: "breakers" as const, label: "Circuit Breakers", icon: ShieldAlert },
    { id: "escalations" as const, label: "Escalations", icon: Zap },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
            <Bot className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white">BMG Sentinel</h1>
            <p className="text-xs text-white/40">Multi-agent DevOps Monitor</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {health && (
            <Badge
              label={health.sentinel_enabled ? "ENABLED" : "DISABLED"}
              variant={health.sentinel_enabled ? "green" : "gray"}
            />
          )}
          <button
            onClick={() => refetchHealth()}
            className="p-2 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
          >
            <RefreshCw className="w-4 h-4 text-white/60" />
          </button>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {statsLoading ? (
          Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-24" />)
        ) : stats ? (
          <>
            <KpiCard
              icon={DollarSign}
              label="Today's Cost"
              value={`$${stats.today_cost_usd.toFixed(3)}`}
              sub={`/ $${stats.daily_cap_usd} cap`}
              variant={costPct > 80 ? "danger" : costPct > 50 ? "warn" : "ok"}
            />
            <KpiCard
              icon={GitPullRequest}
              label="PRs Today"
              value={`${stats.today_pr_count} / ${stats.daily_pr_cap}`}
              sub="daily limit"
              variant={prPct > 80 ? "danger" : prPct > 50 ? "warn" : "default"}
            />
            <KpiCard
              icon={AlertTriangle}
              label="Open Events"
              value={stats.open_events}
              variant={stats.open_events > 5 ? "danger" : stats.open_events > 0 ? "warn" : "ok"}
            />
            <KpiCard
              icon={CheckCircle2}
              label="Resolution Rate"
              value={`${(stats.resolution_rate_7d * 100).toFixed(0)}%`}
              sub="last 7 days"
              variant={stats.resolution_rate_7d > 0.8 ? "ok" : stats.resolution_rate_7d > 0.5 ? "warn" : "danger"}
            />
            <KpiCard
              icon={Activity}
              label="Agents Running"
              value={health ? Object.values(health.agents).filter((a) => a.running).length : "—"}
              sub={health ? `/ ${Object.keys(health.agents).length} total` : undefined}
              variant="default"
            />
            <KpiCard
              icon={ShieldCheck}
              label="Circuit Breakers"
              value={breakers ? breakers.filter((b) => b.tripped).length : "—"}
              sub="tripped today"
              variant={breakers && breakers.filter((b) => b.tripped).length > 0 ? "warn" : "ok"}
            />
          </>
        ) : (
          <div className="col-span-6 text-center py-8 text-white/30 text-sm">
            Sentinel service unreachable — is it running?
          </div>
        )}
      </div>

      {/* Cost / PR progress bars */}
      {stats && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="rounded-xl bg-[var(--bg-elevated)] border border-white/5 p-4 space-y-2">
            <div className="flex justify-between text-xs text-white/50">
              <span>LLM Cost Today</span>
              <span className={costPct > 80 ? "text-red-400" : "text-white/70"}>
                ${stats.today_cost_usd.toFixed(4)} / ${stats.daily_cap_usd}
              </span>
            </div>
            <div className="h-2 bg-white/5 rounded-full overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all", costPct > 80 ? "bg-red-500" : costPct > 50 ? "bg-amber-500" : "bg-green-500")}
                style={{ width: `${Math.min(costPct, 100)}%` }}
              />
            </div>
          </div>
          <div className="rounded-xl bg-[var(--bg-elevated)] border border-white/5 p-4 space-y-2">
            <div className="flex justify-between text-xs text-white/50">
              <span>PRs Today</span>
              <span className={prPct > 80 ? "text-red-400" : "text-white/70"}>
                {stats.today_pr_count} / {stats.daily_pr_cap}
              </span>
            </div>
            <div className="h-2 bg-white/5 rounded-full overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all", prPct > 80 ? "bg-red-500" : prPct > 50 ? "bg-amber-500" : "bg-blue-500")}
                style={{ width: `${Math.min(prPct, 100)}%` }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Agent health grid */}
      {health && (
        <div>
          <SectionHeader title="Agent Status" icon={Bot} />
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
            {Object.entries(health.agents).map(([name, a]) => (
              <div
                key={name}
                className="rounded-lg bg-[var(--bg-elevated)] border border-white/5 p-3 space-y-1"
              >
                <div className="flex items-center gap-1.5">
                  <span className={cn("w-2 h-2 rounded-full", a.running ? "bg-green-400" : "bg-white/20")} />
                  <span className="text-[11px] font-medium text-white/80 truncate">{name.replace(/_/g, " ")}</span>
                </div>
                <div className="text-[10px] text-white/30">{timeAgo(a.last_run)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div>
        <div className="flex gap-1 border-b border-white/5 mb-4">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors border-b-2 -mb-px",
                tab === id
                  ? "border-blue-500 text-blue-400"
                  : "border-transparent text-white/40 hover:text-white/70"
              )}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}
        </div>

        {/* Events tab */}
        {tab === "events" && (
          <div className="space-y-2">
            {eventsLoading
              ? Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-16" />)
              : !events?.length
              ? <EmptyState label="No events" />
              : events.map((ev) => (
                <div key={ev.id} className="rounded-xl bg-[var(--bg-elevated)] border border-white/5 p-4 flex flex-wrap items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge label={ev.severity.toUpperCase()} variant={severityVariant(ev.severity)} />
                      <Badge label={ev.status.toUpperCase()} variant={statusVariant(ev.status)} />
                      <span className="text-xs text-white/30 font-mono">{ev.agent_id}</span>
                    </div>
                    <p className="text-sm font-medium text-white mt-1">{ev.title}</p>
                    {ev.affected_file && (
                      <p className="text-xs text-white/40 font-mono mt-0.5 truncate">{ev.affected_file}</p>
                    )}
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-xs text-white/30">{timeAgo(ev.created_at)}</div>
                    {ev.resolved_at && (
                      <div className="text-[10px] text-green-400 mt-0.5">resolved {timeAgo(ev.resolved_at)}</div>
                    )}
                  </div>
                </div>
              ))
            }
          </div>
        )}

        {/* Fixes tab */}
        {tab === "fixes" && (
          <div className="space-y-2">
            {fixesLoading
              ? Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-16" />)
              : !fixes?.length
              ? <EmptyState label="No fixes yet" />
              : fixes.map((fix) => (
                <div key={fix.id} className="rounded-xl bg-[var(--bg-elevated)] border border-white/5 p-4 flex flex-wrap items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge label={fix.outcome.toUpperCase().replace("_", " ")} variant={outcomeVariant(fix.outcome)} />
                      <span className="text-xs text-white/30 font-mono">{fix.agent_id}</span>
                      <span className="text-xs text-white/20">{fix.category}</span>
                    </div>
                    <p className="text-xs text-white/60 font-mono mt-1 truncate">{fix.file_path}</p>
                    {fix.pr_url && (
                      <a
                        href={fix.pr_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-blue-400 hover:underline mt-0.5 inline-flex items-center gap-1"
                      >
                        <GitPullRequest className="w-3 h-3" />
                        PR #{fix.pr_number}
                      </a>
                    )}
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-xs text-white/30">{timeAgo(fix.created_at)}</div>
                    <div className="text-[10px] text-white/20 mt-0.5">${fix.llm_cost_usd.toFixed(4)}</div>
                  </div>
                </div>
              ))
            }
          </div>
        )}

        {/* Circuit Breakers tab */}
        {tab === "breakers" && (
          <div className="space-y-2">
            {breakersLoading
              ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-16" />)
              : !breakers?.length
              ? <EmptyState label="No circuit breakers" />
              : breakers.map((b) => (
                <div key={b.id} className={cn(
                  "rounded-xl border p-4 flex flex-wrap items-start gap-3",
                  b.tripped
                    ? "bg-amber-500/5 border-amber-500/20"
                    : "bg-[var(--bg-elevated)] border-white/5"
                )}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      {b.tripped
                        ? <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
                        : <ShieldCheck className="w-3.5 h-3.5 text-green-400" />
                      }
                      <Badge label={b.tripped ? "TRIPPED" : "OK"} variant={b.tripped ? "amber" : "green"} />
                      <span className="text-xs text-white/30 font-mono">{b.pr_count_today} PRs today</span>
                    </div>
                    <p className="text-xs text-white/60 font-mono mt-1 truncate">{b.file_path}</p>
                    {b.cooldown_until && (
                      <p className="text-[10px] text-amber-400 mt-0.5">
                        Cooldown until {fmtDateTime(b.cooldown_until)}
                      </p>
                    )}
                  </div>
                  {b.tripped_at && (
                    <div className="text-right text-xs text-white/30 shrink-0">
                      tripped {timeAgo(b.tripped_at)}
                    </div>
                  )}
                </div>
              ))
            }
          </div>
        )}

        {/* Escalations tab */}
        {tab === "escalations" && (
          <div className="space-y-2">
            {escalationsLoading
              ? Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-16" />)
              : !escalations?.length
              ? <EmptyState label="No escalations" />
              : escalations.map((esc) => (
                <div key={esc.id} className={cn(
                  "rounded-xl border p-4",
                  esc.resolved ? "bg-[var(--bg-elevated)] border-white/5" : "bg-red-500/5 border-red-500/20"
                )}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge label={esc.resolved ? "RESOLVED" : "OPEN"} variant={esc.resolved ? "green" : "red"} />
                      <span className="text-xs text-white/30 font-mono">#{esc.channel_id}</span>
                    </div>
                    <div className="text-xs text-white/30 shrink-0">{timeAgo(esc.created_at)}</div>
                  </div>
                  <p className="text-sm text-white/70 mt-2 line-clamp-2">{esc.message_preview}</p>
                </div>
              ))
            }
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="rounded-xl bg-[var(--bg-elevated)] border border-white/5 py-12 flex flex-col items-center gap-2">
      <CheckCircle2 className="w-8 h-8 text-white/10" />
      <p className="text-sm text-white/30">{label}</p>
    </div>
  );
}

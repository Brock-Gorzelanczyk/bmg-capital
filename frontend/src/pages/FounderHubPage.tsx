import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Users,
  FileText,
  Mail,
  AlertTriangle,
  CheckCircle2,
  ArrowRight,
  Target,
  Clock,
  TrendingUp,
  Calendar,
} from "lucide-react";
import { toast } from "sonner";
import { useAuthStore } from "@/store/authStore";
import { getDailySummary } from "@/api/founder";
import { patchPlaybookTask } from "@/api/playbook";

const ADMIN_EMAIL = "demo@bmgcapital.com";

function priorityBadge(priority: string) {
  if (priority === "P0")
    return (
      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/30">
        P0
      </span>
    );
  if (priority === "P1")
    return (
      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30">
        P1
      </span>
    );
  return (
    <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-[var(--border-subtle)]/30 text-[var(--text-secondary)] border border-[var(--border-subtle)]">
      P2
    </span>
  );
}

export default function FounderHubPage() {
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const isAdmin =
    user?.email === ADMIN_EMAIL || user?.email?.endsWith("@bmgcapital.com");

  const { data: summary, isLoading } = useQuery({
    queryKey: ["founder-daily-summary"],
    queryFn: getDailySummary,
    staleTime: 60_000,
    enabled: isAdmin,
  });

  const completeMutation = useMutation({
    mutationFn: (taskId: number) =>
      patchPlaybookTask(taskId, { status: "complete" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["founder-daily-summary"] });
      toast.success("Task marked complete!");
    },
    onError: () => toast.error("Failed to update task"),
  });

  if (!isAdmin) {
    return (
      <div className="min-h-screen bg-[var(--bg-base)] flex items-center justify-center">
        <div className="text-center p-8">
          <h1 className="text-2xl font-bold text-[var(--text-primary)] mb-2">
            404
          </h1>
          <p className="text-[var(--text-secondary)]">Page not found.</p>
        </div>
      </div>
    );
  }

  const dayNumber = summary?.day_number ?? 1;
  const pct = Math.round((dayNumber / 90) * 100);

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
        {/* ── Hero Banner ── */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6 space-y-4">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-2xl font-black tracking-tight text-[var(--text-primary)]">
                FOUNDER OPERATING MODE
              </h1>
              <div className="flex items-center gap-3 mt-1 flex-wrap">
                <span className="text-sm font-mono text-[#84cc16]">
                  Day{" "}
                  <span className="text-2xl font-black">
                    {isLoading ? "…" : dayNumber}
                  </span>{" "}
                  of 90
                </span>
                <span className="text-sm text-[var(--text-secondary)]">·</span>
                <span className="text-sm text-[var(--text-secondary)]">
                  Phase 2: Differentiate · Week 5
                </span>
              </div>
            </div>
            <div className="text-right shrink-0">
              <div className="text-3xl font-black font-mono text-[#84cc16]">
                {pct}%
              </div>
              <div className="text-xs text-[var(--text-secondary)]">
                complete
              </div>
            </div>
          </div>

          {/* Progress bar */}
          <div className="w-full h-2.5 bg-[var(--border-subtle)] rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-700"
              style={{ width: `${pct}%`, background: "#84cc16" }}
            />
          </div>
        </div>

        {/* ── Today's Focus ── */}
        {summary?.playbook_task && (
          <div className="rounded-2xl border border-[#84cc16]/40 bg-[#84cc16]/5 p-5 space-y-3">
            <div className="flex items-center gap-2">
              <Target className="w-4 h-4 text-[#84cc16]" />
              <span className="text-xs font-bold text-[#84cc16] uppercase tracking-widest">
                Today's Focus
              </span>
              {priorityBadge(summary.playbook_task.priority)}
            </div>

            <div>
              <h3 className="text-base font-bold text-[var(--text-primary)]">
                {summary.playbook_task.title}
              </h3>
              <p className="text-xs text-[var(--text-secondary)] mt-1 leading-relaxed">
                {summary.playbook_task.description}
              </p>
              <div className="flex items-center gap-3 mt-2 text-xs text-[var(--text-secondary)]">
                <span className="flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  8h
                </span>
              </div>
            </div>

            <button
              onClick={() => {
                if (summary?.playbook_task) {
                  completeMutation.mutate((summary.playbook_task as unknown as { id: number }).id);
                }
              }}
              disabled={completeMutation.isPending}
              className="w-full py-2 rounded-lg bg-[#84cc16] text-black text-sm font-semibold hover:bg-[#a3e635] transition-colors disabled:opacity-50"
            >
              {completeMutation.isPending ? "Saving…" : "Mark Complete"}
            </button>
          </div>
        )}

        {/* ── 3-col Sub-Cards ── */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Investor Pipeline */}
          <button
            onClick={() => navigate("/settings/founder/investors")}
            className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-5 text-left hover:border-[#84cc16]/40 transition-all group space-y-3"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Users className="w-4 h-4 text-[#84cc16]" />
                <span className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-widest">
                  Investor Pipeline
                </span>
              </div>
              <ArrowRight className="w-4 h-4 text-[var(--text-secondary)] group-hover:text-[#84cc16] transition-colors" />
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-[var(--text-secondary)]">
                  Tracked
                </span>
                <span className="text-lg font-bold text-[var(--text-primary)] font-mono">
                  {summary?.investor_pipeline?.total ?? "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-[var(--text-secondary)]">
                  Meetings this week
                </span>
                <span className="text-sm font-semibold text-[var(--text-primary)] font-mono">
                  {summary?.investor_pipeline?.meetings_this_week ?? "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-[var(--text-secondary)] flex items-center gap-1">
                  Follow-ups due
                  {(summary?.investor_pipeline?.follow_ups_due ?? 0) > 0 && (
                    <AlertTriangle className="w-3 h-3 text-amber-400" />
                  )}
                </span>
                <span
                  className={`text-sm font-semibold font-mono ${
                    (summary?.investor_pipeline?.follow_ups_due ?? 0) > 0
                      ? "text-amber-400"
                      : "text-[var(--text-primary)]"
                  }`}
                >
                  {summary?.investor_pipeline?.follow_ups_due ?? "—"}
                </span>
              </div>
            </div>

            <div className="text-xs text-[#84cc16] font-semibold group-hover:underline">
              View pipeline →
            </div>
          </button>

          {/* Content */}
          <button
            onClick={() => navigate("/settings/founder/content")}
            className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-5 text-left hover:border-[#84cc16]/40 transition-all group space-y-3"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-[#84cc16]" />
                <span className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-widest">
                  Content
                </span>
              </div>
              <ArrowRight className="w-4 h-4 text-[var(--text-secondary)] group-hover:text-[#84cc16] transition-colors" />
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-[var(--text-secondary)]">
                  Unfilled slots today
                </span>
                <span
                  className={`text-lg font-bold font-mono ${
                    (summary?.content?.unfilled_slots_today ?? 0) > 0
                      ? "text-amber-400"
                      : "text-[var(--text-primary)]"
                  }`}
                >
                  {summary?.content?.unfilled_slots_today ?? "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-[var(--text-secondary)] flex items-center gap-1">
                  <Calendar className="w-3 h-3" />
                  Next post
                </span>
                <span className="text-sm font-semibold text-[var(--text-primary)] font-mono">
                  2h
                </span>
              </div>
            </div>

            <div className="text-xs text-[#84cc16] font-semibold group-hover:underline">
              View calendar →
            </div>
          </button>

          {/* Waitlist */}
          <button
            onClick={() => navigate("/settings/founder/waitlist")}
            className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-5 text-left hover:border-[#84cc16]/40 transition-all group space-y-3"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Mail className="w-4 h-4 text-[#84cc16]" />
                <span className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-widest">
                  Waitlist
                </span>
              </div>
              <ArrowRight className="w-4 h-4 text-[var(--text-secondary)] group-hover:text-[#84cc16] transition-colors" />
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-[var(--text-secondary)]">
                  Total signups
                </span>
                <span className="text-lg font-bold text-[#84cc16] font-mono">
                  {summary?.waitlist?.total ?? "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-[var(--text-secondary)]">
                  Today
                </span>
                <span className="text-sm font-semibold text-green-400 font-mono">
                  +{summary?.waitlist?.today_count ?? 0}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-[var(--text-secondary)] flex items-center gap-1">
                  <TrendingUp className="w-3 h-3" />
                  Viral coeff k
                </span>
                <span className="text-sm font-semibold text-[var(--text-primary)] font-mono">
                  0.3
                </span>
              </div>
            </div>

            <div className="text-xs text-[#84cc16] font-semibold group-hover:underline">
              View analytics →
            </div>
          </button>
        </div>

        {/* ── Compliance Status ── */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-5">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-[#84cc16]" />
              <span className="text-sm font-semibold text-[var(--text-primary)]">
                Compliance Status
              </span>
            </div>
            <span className="text-sm text-[var(--text-secondary)]">·</span>
            <span className="text-sm text-[#84cc16]">
              All recent posts compliant
            </span>
          </div>
          <p className="text-xs text-[var(--text-secondary)] mt-2 ml-7">
            Last checked: 2 minutes ago
          </p>
        </div>
      </div>
    </div>
  );
}

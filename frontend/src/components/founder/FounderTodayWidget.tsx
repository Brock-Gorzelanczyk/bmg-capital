import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Target, ChevronRight, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { useAuthStore } from "@/store/authStore";
import { getDailySummary } from "@/api/founder";
import { patchPlaybookTask } from "@/api/playbook";

const ADMIN_EMAILS = new Set(["demo@bmgcapital.com", "32bgorzelanczyk@gmail.com"]);

function priorityBadge(priority: string) {
  if (priority === "P0")
    return (
      <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/30">
        P0
      </span>
    );
  if (priority === "P1")
    return (
      <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30">
        P1
      </span>
    );
  return (
    <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-[var(--border-subtle)]/30 text-[var(--text-secondary)] border border-[var(--border-subtle)]">
      P2
    </span>
  );
}

export default function FounderTodayWidget() {
  const user = useAuthStore((s) => s.user);
  const qc = useQueryClient();

  const isAdmin =
    ADMIN_EMAILS.has(user?.email ?? "") || user?.email?.endsWith("@bmgcapital.com");

  const { data: summary } = useQuery({
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

  if (!isAdmin) return null;

  const dayNumber = summary?.day_number ?? 1;
  const pct = Math.round((dayNumber / 90) * 100);
  const task = summary?.playbook_task ?? null;
  const todaySignups = summary?.waitlist?.today_count ?? 0;

  return (
    <div className="rounded-2xl border border-[#84cc16]/30 bg-[#84cc16]/5 p-4 space-y-3">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Target className="w-4 h-4 text-[#84cc16]" />
          <span className="text-xs font-bold text-[#84cc16] uppercase tracking-widest">
            Founder Mode
          </span>
        </div>
        <Link
          to="/settings/founder"
          className="flex items-center gap-1 text-xs text-[var(--text-secondary)] hover:text-[#84cc16] transition-colors"
        >
          Hub
          <ChevronRight className="w-3 h-3" />
        </Link>
      </div>

      {/* Day + progress */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-xs text-[var(--text-secondary)]">
            Day{" "}
            <span className="font-bold text-[var(--text-primary)] font-mono">
              {dayNumber}
            </span>{" "}
            of 90
          </span>
          <span className="text-xs font-bold font-mono text-[#84cc16]">
            {pct}%
          </span>
        </div>
        <div className="w-full h-1.5 bg-[var(--border-subtle)] rounded-full overflow-hidden">
          <div
            className="h-full rounded-full bg-[#84cc16] transition-all duration-700"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Today's task */}
      {task ? (
        <div className="space-y-2">
          <div className="flex items-start gap-2">
            {priorityBadge(task.priority)}
            <span className="text-xs font-medium text-[var(--text-primary)] leading-snug">
              {task.title}
            </span>
          </div>
          <button
            onClick={() => {
              const taskWithId = task as unknown as { id: number };
              if (taskWithId.id) {
                completeMutation.mutate(taskWithId.id);
              }
            }}
            disabled={completeMutation.isPending}
            className="w-full py-1.5 rounded-lg bg-[#84cc16] text-black text-xs font-semibold hover:bg-[#a3e635] transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5"
          >
            <CheckCircle2 className="w-3.5 h-3.5" />
            {completeMutation.isPending ? "Saving…" : "Mark Complete"}
          </button>
        </div>
      ) : (
        <div className="text-xs text-[var(--text-secondary)] italic">
          No pending task
        </div>
      )}

      {/* Mini stat */}
      {todaySignups > 0 && (
        <div className="text-xs text-green-400 font-semibold">
          +{todaySignups} signup{todaySignups !== 1 ? "s" : ""} today
        </div>
      )}
    </div>
  );
}

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  CheckCircle2,
  Circle,
  ChevronDown,
  ChevronRight,
  Flag,
  Target,
  Clock,
  AlertCircle,
  XCircle,
  Loader2,
  GitBranch,
  Ban,
  ExternalLink,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  getPlaybookStatus,
  getPlaybookPhases,
  getDoNotDo,
  patchPlaybookTask,
  initPlaybook,
  type PlaybookPhase,
  type PlaybookTask,
} from "@/api/playbook";

// ─── Helpers ─────────────────────────────────────────────────────────────────

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

function statusIcon(status: string) {
  switch (status) {
    case "complete":
      return <CheckCircle2 className="w-4 h-4 text-[#4ade80] shrink-0" />;
    case "in_progress":
      return <Loader2 className="w-4 h-4 text-blue-400 shrink-0 animate-spin" />;
    case "skipped":
      return <XCircle className="w-4 h-4 text-[var(--text-secondary)] shrink-0" />;
    default:
      return <Circle className="w-4 h-4 text-[var(--border-subtle)] shrink-0" />;
  }
}

function weekCompletionPct(tasks: PlaybookTask[]) {
  if (!tasks.length) return 0;
  const done = tasks.filter((t) => t.status === "complete").length;
  return Math.round((done / tasks.length) * 100);
}

// ─── Task Row ─────────────────────────────────────────────────────────────────

interface TaskRowProps {
  task: PlaybookTask;
  onUpdate: (id: number, status: string, note?: string) => void;
  isLoading: boolean;
}

function TaskRow({ task, onUpdate, isLoading }: TaskRowProps) {
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState(task.completion_note ?? "");
  const isDone = task.status === "complete";

  function handleCheck() {
    if (isDone) {
      onUpdate(task.id, "pending");
    } else {
      setNoteOpen(true);
    }
  }

  function handleSave() {
    onUpdate(task.id, "complete", note);
    setNoteOpen(false);
  }

  return (
    <div
      className={cn(
        "group rounded-lg border border-[var(--border-subtle)] px-4 py-3 transition-all",
        isDone ? "opacity-60 bg-[var(--bg-elevated)]" : "bg-[var(--bg-elevated)] hover:border-[#4ade80]/30"
      )}
    >
      <div className="flex items-start gap-3">
        <button
          onClick={handleCheck}
          disabled={isLoading}
          className="mt-0.5 shrink-0"
        >
          {statusIcon(task.status)}
        </button>

        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <span
              className={cn(
                "text-sm font-medium",
                isDone
                  ? "line-through text-[var(--text-secondary)]"
                  : "text-[var(--text-primary)]"
              )}
            >
              {task.title}
            </span>
            {priorityBadge(task.priority)}
            <span className="text-[11px] text-[var(--text-secondary)] font-mono">
              {task.day_focus}
            </span>
            <span className="text-[11px] text-[var(--text-secondary)] flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {task.effort_hours}h
            </span>
          </div>

          {task.description && (
            <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
              {task.description}
            </p>
          )}

          {task.completion_note && isDone && (
            <p className="mt-1 text-xs text-[#4ade80]/80 italic">
              Note: {task.completion_note}
            </p>
          )}

          {noteOpen && (
            <div className="mt-3 flex gap-2">
              <input
                autoFocus
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Optional completion note…"
                className="flex-1 text-xs bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded px-3 py-1.5 text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none focus:border-[#4ade80]/50"
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSave();
                  if (e.key === "Escape") setNoteOpen(false);
                }}
              />
              <button
                onClick={handleSave}
                className="text-xs px-3 py-1.5 rounded bg-[#4ade80] text-black font-semibold hover:bg-[#a3e635] transition-colors"
              >
                Done
              </button>
              <button
                onClick={() => setNoteOpen(false)}
                className="text-xs px-3 py-1.5 rounded border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
              >
                Skip
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Week Accordion ───────────────────────────────────────────────────────────

interface WeekCardProps {
  week: PlaybookPhase["weeks"][number];
  isCurrentWeek: boolean;
  onUpdate: (id: number, status: string, note?: string) => void;
  isLoading: boolean;
}

function WeekCard({ week, isCurrentWeek, onUpdate, isLoading }: WeekCardProps) {
  const [open, setOpen] = useState(isCurrentWeek);
  const pct = weekCompletionPct(week.tasks);

  return (
    <div
      className={cn(
        "rounded-xl border overflow-hidden",
        isCurrentWeek
          ? "border-[#4ade80]/40 shadow-[0_0_20px_rgba(74,222,128,0.08)]"
          : "border-[var(--border-subtle)]"
      )}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-3 px-5 py-4 bg-[var(--bg-elevated)] hover:bg-[var(--bg-elevated-2)] transition-colors text-left"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-[var(--text-primary)]">
              Week {week.week_number} — {week.title}
            </span>
            {isCurrentWeek && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#4ade80]/20 text-[#4ade80] font-bold border border-[#4ade80]/30">
                CURRENT
              </span>
            )}
            <span className="text-[11px] text-[var(--text-secondary)] font-mono">
              Day {week.day_start}–{week.day_end}
            </span>
          </div>
          <p className="text-xs text-[var(--text-secondary)] mt-0.5 truncate">{week.outcome_target}</p>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <div className="text-right">
            <div className="text-xs font-semibold text-[#4ade80]">{pct}%</div>
            <div className="text-[10px] text-[var(--text-secondary)]">
              {week.tasks.filter((t) => t.status === "complete").length}/{week.tasks.length}
            </div>
          </div>
          {open ? (
            <ChevronDown className="w-4 h-4 text-[var(--text-secondary)]" />
          ) : (
            <ChevronRight className="w-4 h-4 text-[var(--text-secondary)]" />
          )}
        </div>
      </button>

      {open && (
        <div className="px-5 pb-5 pt-3 bg-[var(--bg-base)] space-y-2">
          {week.tasks.length === 0 ? (
            <p className="text-xs text-[var(--text-secondary)] italic">No tasks yet.</p>
          ) : (
            week.tasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                onUpdate={onUpdate}
                isLoading={isLoading}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ─── Phase Section ────────────────────────────────────────────────────────────

interface PhaseSectionProps {
  phase: PlaybookPhase;
  dayNumber: number;
  onUpdate: (id: number, status: string, note?: string) => void;
  isLoading: boolean;
}

function PhaseSection({ phase, dayNumber, onUpdate, isLoading }: PhaseSectionProps) {
  const isCurrent =
    phase.day_start <= dayNumber && phase.day_end >= dayNumber;
  const isComplete = dayNumber > phase.day_end;
  const allTasks = phase.weeks.flatMap((w) => w.tasks);
  const pct = weekCompletionPct(allTasks);

  return (
    <div
      id={`phase-${phase.phase_number}`}
      className={cn(
        "rounded-2xl border p-6 space-y-4",
        isCurrent
          ? "border-[#4ade80]/40"
          : isComplete
          ? "border-[var(--border-subtle)] opacity-80"
          : "border-[var(--border-subtle)]"
      )}
      style={{ borderLeftWidth: "3px", borderLeftColor: isCurrent ? "#4ade80" : "transparent" }}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-[#4ade80] uppercase tracking-widest">
              Phase {phase.phase_number}
            </span>
            {isComplete && (
              <CheckCircle2 className="w-4 h-4 text-[#4ade80]" />
            )}
            {isCurrent && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#4ade80] text-black font-bold">
                ACTIVE
              </span>
            )}
          </div>
          <h2 className="text-xl font-bold text-[var(--text-primary)] mt-0.5">{phase.name}</h2>
          <p className="text-sm text-[var(--text-secondary)] mt-1">{phase.outcome_target}</p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-2xl font-bold font-mono text-[#4ade80]">{pct}%</div>
          <div className="text-xs text-[var(--text-secondary)]">
            Day {phase.day_start}–{phase.day_end}
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {phase.weeks.map((week) => {
          const isCurrentWeek =
            week.day_start <= dayNumber && week.day_end >= dayNumber;
          return (
            <WeekCard
              key={week.id}
              week={week}
              isCurrentWeek={isCurrentWeek}
              onUpdate={onUpdate}
              isLoading={isLoading}
            />
          );
        })}
      </div>
    </div>
  );
}

// ─── Today's Focus Card ───────────────────────────────────────────────────────

interface TodayFocusProps {
  phases: PlaybookPhase[];
  dayNumber: number;
  onUpdate: (id: number, status: string, note?: string) => void;
  isLoading: boolean;
}

function TodayFocusCard({ phases, dayNumber, onUpdate, isLoading }: TodayFocusProps) {
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState("");

  // Find current week
  const currentWeek = phases
    .flatMap((p) => p.weeks)
    .find((w) => w.day_start <= dayNumber && w.day_end >= dayNumber);

  if (!currentWeek) return null;

  // Highest-priority incomplete task
  const priority = ["P0", "P1", "P2"];
  const focusTask = priority
    .flatMap((p) => currentWeek.tasks.filter((t) => t.priority === p && t.status !== "complete" && t.status !== "skipped"))
    .at(0);

  if (!focusTask) {
    return (
      <div className="rounded-2xl border border-[#4ade80]/40 bg-[#4ade80]/5 p-5">
        <div className="flex items-center gap-2 text-[#4ade80] font-semibold text-sm">
          <CheckCircle2 className="w-5 h-5" />
          All tasks complete for this week!
        </div>
      </div>
    );
  }

  function handleComplete() {
    setNoteOpen(true);
  }

  function handleSave() {
    onUpdate(focusTask!.id, "complete", note);
    setNoteOpen(false);
    setNote("");
  }

  return (
    <div className="rounded-2xl border border-[#4ade80]/40 bg-[#4ade80]/5 p-5 space-y-3">
      <div className="flex items-center gap-2">
        <Target className="w-4 h-4 text-[#4ade80]" />
        <span className="text-xs font-bold text-[#4ade80] uppercase tracking-widest">Today's Focus</span>
        {priorityBadge(focusTask.priority)}
      </div>

      <div>
        <h3 className="text-base font-bold text-[var(--text-primary)]">{focusTask.title}</h3>
        <p className="text-xs text-[var(--text-secondary)] mt-1 leading-relaxed">{focusTask.description}</p>
        <div className="flex items-center gap-3 mt-2 text-xs text-[var(--text-secondary)]">
          <span className="flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {focusTask.effort_hours}h
          </span>
          <span>{focusTask.day_focus}</span>
        </div>
      </div>

      {!noteOpen ? (
        <button
          onClick={handleComplete}
          disabled={isLoading}
          className="w-full py-2 rounded-lg bg-[#4ade80] text-black text-sm font-semibold hover:bg-[#a3e635] transition-colors disabled:opacity-50"
        >
          Mark Complete
        </button>
      ) : (
        <div className="space-y-2">
          <input
            autoFocus
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Completion note (optional)…"
            className="w-full text-sm bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none focus:border-[#4ade80]/50"
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
              if (e.key === "Escape") setNoteOpen(false);
            }}
          />
          <div className="flex gap-2">
            <button
              onClick={handleSave}
              className="flex-1 py-2 rounded-lg bg-[#4ade80] text-black text-sm font-semibold hover:bg-[#a3e635] transition-colors"
            >
              Confirm
            </button>
            <button
              onClick={() => setNoteOpen(false)}
              className="px-4 py-2 rounded-lg border border-[var(--border-subtle)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function PlaybookPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ["playbook-status"],
    queryFn: getPlaybookStatus,
  });

  const { data: phases, isLoading: phasesLoading } = useQuery({
    queryKey: ["playbook-phases"],
    queryFn: getPlaybookPhases,
  });

  const { data: doNotDoData } = useQuery({
    queryKey: ["playbook-do-not-do"],
    queryFn: getDoNotDo,
  });

  const initMutation = useMutation({
    mutationFn: initPlaybook,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["playbook-status"] });
      qc.invalidateQueries({ queryKey: ["playbook-phases"] });
      toast.success("Playbook initialized!");
    },
    onError: () => toast.error("Init failed"),
  });

  const patchMutation = useMutation({
    mutationFn: ({ id, status, note }: { id: number; status: string; note?: string }) =>
      patchPlaybookTask(id, { status, completion_note: note }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["playbook-phases"] });
      qc.invalidateQueries({ queryKey: ["playbook-status"] });
    },
    onError: () => toast.error("Failed to update task"),
  });

  function handleUpdate(id: number, taskStatus: string, note?: string) {
    patchMutation.mutate({ id, status: taskStatus, note });
  }

  const dayNumber = status?.day_number ?? 1;
  const pct = status?.completion_pct ?? 0;
  const today = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });

  const noData = !phasesLoading && (!phases || phases.length === 0);

  function scrollToPhase(phaseNumber: number) {
    document.getElementById(`phase-${phaseNumber}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">

        {/* ── Hero Row ── */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6 space-y-4">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div
                className="text-5xl font-black font-mono leading-none"
                style={{ color: "#4ade80", fontVariantNumeric: "tabular-nums" }}
              >
                Day {statusLoading ? "…" : dayNumber}
                <span className="text-2xl text-[var(--text-secondary)] font-medium"> of 90</span>
              </div>
              <div className="mt-2 text-sm text-[var(--text-secondary)]">{today}</div>
              {status?.current_phase && (
                <div className="mt-1 text-base font-semibold text-[var(--text-primary)]">
                  Phase: {status.current_phase}
                  {status.current_week ? ` — ${status.current_week}` : ""}
                </div>
              )}
            </div>

            <div className="text-right">
              <div className="text-3xl font-bold font-mono text-[#4ade80]">{pct}%</div>
              <div className="text-xs text-[var(--text-secondary)] mt-0.5">
                {status?.completed_tasks ?? 0} / {status?.total_tasks ?? 0} tasks done
              </div>
            </div>
          </div>

          {/* Progress bar */}
          <div className="w-full h-2 bg-[var(--border-subtle)] rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-700"
              style={{ width: `${pct}%`, background: "#4ade80" }}
            />
          </div>
        </div>

        {/* ── Phase Swimlane ── */}
        {phases && phases.length > 0 && (
          <div className="flex gap-3 overflow-x-auto pb-1 scrollbar-hide">
            {phases.map((phase) => {
              const isCurrent = phase.day_start <= dayNumber && phase.day_end >= dayNumber;
              const isComplete = dayNumber > phase.day_end;
              return (
                <button
                  key={phase.id}
                  onClick={() => scrollToPhase(phase.phase_number)}
                  className={cn(
                    "flex-1 min-w-[160px] rounded-xl border px-4 py-3 text-left transition-all shrink-0",
                    isCurrent
                      ? "bg-[#4ade80] border-[#4ade80] text-black"
                      : isComplete
                      ? "bg-[var(--bg-elevated)] border-[var(--border-subtle)] text-[var(--text-secondary)]"
                      : "bg-[var(--bg-elevated)] border-[var(--border-subtle)] text-[var(--text-primary)] hover:border-[#4ade80]/40"
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-bold uppercase tracking-wider opacity-70">
                      Phase {phase.phase_number}
                    </span>
                    {isComplete && <CheckCircle2 className="w-3 h-3" />}
                  </div>
                  <div className="text-sm font-bold mt-0.5">{phase.name}</div>
                  <div className="text-[11px] opacity-70 mt-0.5 font-mono">
                    Day {phase.day_start}–{phase.day_end}
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {/* ── No data / init ── */}
        {noData && (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-8 text-center space-y-4">
            <Flag className="w-10 h-10 text-[#4ade80] mx-auto" />
            <div>
              <h2 className="text-lg font-bold">Playbook not initialized</h2>
              <p className="text-sm text-[var(--text-secondary)] mt-1">
                Seed all 90-day phases, weeks, and tasks to get started.
              </p>
            </div>
            <button
              onClick={() => initMutation.mutate()}
              disabled={initMutation.isPending}
              className="px-6 py-2 rounded-lg bg-[#4ade80] text-black font-semibold hover:bg-[#a3e635] transition-colors disabled:opacity-50"
            >
              {initMutation.isPending ? "Initializing…" : "Initialize Playbook"}
            </button>
          </div>
        )}

        {/* ── Today's Focus ── */}
        {phases && phases.length > 0 && (
          <TodayFocusCard
            phases={phases}
            dayNumber={dayNumber}
            onUpdate={handleUpdate}
            isLoading={patchMutation.isPending}
          />
        )}

        {/* ── Phase/Week Accordion ── */}
        {phases && phases.length > 0 && (
          <div className="space-y-6">
            {phases.map((phase) => (
              <PhaseSection
                key={phase.id}
                phase={phase}
                dayNumber={dayNumber}
                onUpdate={handleUpdate}
                isLoading={patchMutation.isPending}
              />
            ))}
          </div>
        )}

        {/* ── Do-Not-Do List ── */}
        {doNotDoData && doNotDoData.items.length > 0 && (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6 space-y-4">
            <div className="flex items-center gap-2">
              <Ban className="w-5 h-5 text-red-400" />
              <h2 className="text-base font-bold text-[var(--text-primary)]">Do-Not-Do List</h2>
              <span className="text-xs text-[var(--text-secondary)]">
                Resisting {doNotDoData.items.length} features post-raise
              </span>
            </div>
            <ul className="space-y-2">
              {doNotDoData.items.map((item, i) => (
                <li key={i} className="flex items-center gap-3 text-sm">
                  <XCircle className="w-4 h-4 text-red-400 shrink-0" />
                  <span className="line-through text-[var(--text-secondary)]">{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ── Decision Tree Link ── */}
        <button
          onClick={() => navigate("/settings/pitch/playbook/decisions")}
          className="w-full rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-5 flex items-center justify-between gap-3 hover:border-[#4ade80]/40 transition-all group"
        >
          <div className="flex items-center gap-3">
            <GitBranch className="w-5 h-5 text-[#4ade80]" />
            <div className="text-left">
              <div className="text-sm font-semibold text-[var(--text-primary)]">Decision Tree</div>
              <div className="text-xs text-[var(--text-secondary)]">8 critical decisions with clear rules</div>
            </div>
          </div>
          <ExternalLink className="w-4 h-4 text-[var(--text-secondary)] group-hover:text-[#4ade80] transition-colors" />
        </button>

      </div>
    </div>
  );
}

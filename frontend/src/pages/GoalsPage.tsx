import { useState, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/utils";
import { Target, Plus, X, ChevronRight, TrendingUp } from "lucide-react";
import {
  getGoals,
  createGoal,
  updateGoal,
  deleteGoal,
  getGoalProjection,
  type RoboGoal,
} from "@/api/robo";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function goalIcon(type: string): string {
  const map: Record<string, string> = {
    retirement: "🏖️",
    house: "🏠",
    education: "🎓",
    emergency: "🛡️",
    wealth: "📈",
    income: "💰",
  };
  return map[type] ?? "🎯";
}

// ── Glide Path Mini Chart ─────────────────────────────────────────────────────

function GlideMiniChart({
  glide_path,
}: {
  glide_path: Array<{ date: string; equity: number; bonds: number; cash: number }>;
}) {
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);

  if (!glide_path || glide_path.length < 2) return null;

  const points = glide_path.map((p, i) => ({ x: i, y: p.equity, date: p.date }));
  const maxX = points.length - 1;
  const maxY = Math.max(...points.map((p) => p.y), 100);

  const toSvg = (p: { x: number; y: number }) => ({
    sx: (p.x / maxX) * 100,
    sy: 40 - (p.y / maxY) * 38,
  });

  const pathD = points
    .map((p, i) => {
      const { sx, sy } = toSvg(p);
      return `${i === 0 ? "M" : "L"} ${sx} ${sy}`;
    })
    .join(" ");

  function handleMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = ((e.clientX - rect.left) / rect.width) * maxX;
    const idx = Math.round(Math.max(0, Math.min(relX, maxX)));
    const p = points[idx];
    if (p) {
      setTooltip({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top - 30,
        text: `${Math.round(p.y)}% equity · ${fmtDate(p.date)}`,
      });
    }
  }

  return (
    <div className="relative">
      <svg
        viewBox="0 0 100 40"
        preserveAspectRatio="none"
        className="w-full h-10 cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setTooltip(null)}
      >
        <path d={pathD} fill="none" stroke="#3B82F6" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      {tooltip && (
        <div
          ref={tooltipRef}
          className="absolute pointer-events-none bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-2 py-1 text-[10px] text-[var(--text-secondary)] whitespace-nowrap z-10"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          {tooltip.text}
        </div>
      )}
    </div>
  );
}

// ── Monte Carlo Badge ─────────────────────────────────────────────────────────

function MonteCarloBadge({
  pct,
  onClick,
}: {
  pct: number;
  onClick: () => void;
}) {
  const cls =
    pct >= 80
      ? "bg-green-500/10 text-green-400 border-green-500/20"
      : pct >= 60
      ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
      : "bg-red-500/10 text-red-400 border-red-500/20";

  return (
    <button
      onClick={onClick}
      className={cn(
        "text-xs font-semibold px-2.5 py-1 rounded-full border transition-all hover:opacity-80",
        cls
      )}
    >
      {pct}% on track
    </button>
  );
}

// ── Projection Drawer ─────────────────────────────────────────────────────────

function ProjectionDrawer({
  goalId,
  goalName,
  onClose,
}: {
  goalId: number;
  goalName: string;
  onClose: () => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["goal-projection", goalId],
    queryFn: () => getGoalProjection(goalId),
    enabled: !!goalId,
    staleTime: 60_000,
  });

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm">
      <div
        className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-t-2xl sm:rounded-2xl w-full sm:max-w-md p-5 space-y-4"
        style={{
          animation: "slideUp 300ms ease",
        }}
      >
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-semibold text-[var(--text-primary)]">Monte Carlo Projection</h3>
            <p className="text-xs text-[var(--text-tertiary)]">{goalName}</p>
          </div>
          <button
            onClick={onClose}
            className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-8">
            <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : data ? (
          <div className="space-y-4">
            {/* Scenario bars */}
            {[
              { label: "Pessimistic (P10)", val: data.percentile_10, color: "#EF4444" },
              { label: "Expected (P50)", val: data.percentile_50, color: "#3B82F6" },
              { label: "Optimistic (P90)", val: data.percentile_90, color: "#22C55E" },
            ].map(({ label, val, color }) => {
              const maxVal = data.percentile_90 || 1;
              const pct = (val / maxVal) * 100;
              return (
                <div key={label} className="space-y-1">
                  <div className="flex justify-between text-sm">
                    <span className="text-[var(--text-secondary)]">{label}</span>
                    <span className="font-semibold text-[var(--text-primary)]">
                      {formatCurrency(val, 0)}
                    </span>
                  </div>
                  <div className="h-2 bg-[var(--border-subtle)] rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-700"
                      style={{ width: `${pct}%`, background: color }}
                    />
                  </div>
                </div>
              );
            })}

            <div className="border-t border-[var(--border-subtle)] pt-3 space-y-1">
              <div className="flex justify-between text-sm">
                <span className="text-[var(--text-tertiary)]">Expected outcome</span>
                <span className="font-semibold text-[var(--text-primary)]">
                  {formatCurrency(data.expected_value, 0)}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-[var(--text-tertiary)]">Monthly needed (90% confidence)</span>
                <span className="font-semibold text-blue-400">
                  {formatCurrency(data.monthly_needed_for_90pct, 0)}/mo
                </span>
              </div>
            </div>
          </div>
        ) : (
          <p className="text-sm text-[var(--text-tertiary)] text-center py-6">
            Projection data unavailable.
          </p>
        )}
      </div>
      <style>{`@keyframes slideUp { from { transform: translateY(40px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }`}</style>
    </div>
  );
}

// ── Goal Card ─────────────────────────────────────────────────────────────────

function GoalCard({
  goal,
  onSelectProjection,
}: {
  goal: RoboGoal;
  onSelectProjection: (id: number) => void;
}) {
  const qc = useQueryClient();

  const acceptMutation = useMutation({
    mutationFn: (newContrib: number) => updateGoal(goal.id, { monthly_contribution: newContrib }),
    onSuccess: () => {
      toast.success("Monthly contribution updated");
      qc.invalidateQueries({ queryKey: ["robo-goals"] });
    },
    onError: () => toast.error("Failed to update goal"),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteGoal(goal.id),
    onSuccess: () => {
      toast.success("Goal deleted");
      qc.invalidateQueries({ queryKey: ["robo-goals"] });
    },
    onError: () => toast.error("Failed to delete goal"),
  });

  const progress = Math.min((goal.current_balance / goal.target_amount) * 100, 100);

  // Rough AI coaching: suggest enough to push probability toward 90%
  const suggestedIncrease = goal.status === "behind" ? Math.ceil(goal.monthly_contribution * 0.36) : 0;

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xl">{goalIcon(goal.goal_type)}</span>
          <div>
            <h3 className="font-semibold text-[var(--text-primary)]">{goal.name}</h3>
            <p className="text-xs text-[var(--text-tertiary)]">
              Target: {formatCurrency(goal.target_amount, 0)}
              {goal.target_date && ` by ${fmtDate(goal.target_date)}`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <MonteCarloBadge
            pct={goal.probability_pct}
            onClick={() => onSelectProjection(goal.id)}
          />
          <button
            onClick={() => {
              if (confirm(`Delete "${goal.name}"?`)) deleteMutation.mutate();
            }}
            className="text-[var(--text-tertiary)] hover:text-red-400 transition-colors"
          >
            <X size={15} />
          </button>
        </div>
      </div>

      {/* Balance & contribution */}
      <div className="flex items-center gap-4 text-sm">
        <div>
          <p className="text-xs text-[var(--text-tertiary)]">Current</p>
          <p className="font-semibold text-[var(--text-primary)]">
            {formatCurrency(goal.current_balance, 0)}
          </p>
        </div>
        <div className="text-[var(--border-subtle)]">·</div>
        <div>
          <p className="text-xs text-[var(--text-tertiary)]">Monthly</p>
          <p className="font-semibold text-[var(--text-primary)]">
            +{formatCurrency(goal.monthly_contribution, 0)}/mo
          </p>
        </div>
      </div>

      {/* Progress bar */}
      <div className="space-y-1">
        <div className="h-1.5 bg-[var(--border-subtle)] rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all duration-700"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="flex justify-between text-[10px] text-[var(--text-tertiary)]">
          <span>{progress.toFixed(1)}% funded</span>
          <span>{formatCurrency(goal.target_amount - goal.current_balance, 0)} remaining</span>
        </div>
      </div>

      {/* AI coaching */}
      {goal.status === "behind" && suggestedIncrease > 0 && (
        <div className="flex items-center justify-between bg-amber-500/5 border border-amber-500/20 rounded-lg px-3 py-2">
          <p className="text-xs text-amber-400">
            Increase by{" "}
            <span className="font-bold">{formatCurrency(suggestedIncrease, 0)}/mo</span> → 90%
            confidence
          </p>
          <button
            onClick={() =>
              acceptMutation.mutate(goal.monthly_contribution + suggestedIncrease)
            }
            disabled={acceptMutation.isPending}
            className="text-xs font-semibold text-white bg-amber-500 hover:bg-amber-400 px-2.5 py-1 rounded-lg transition-colors disabled:opacity-50"
          >
            {acceptMutation.isPending ? "…" : "Accept"}
          </button>
        </div>
      )}

      {/* Glide path */}
      {goal.glide_path && goal.glide_path.length >= 2 && (
        <div className="space-y-1">
          <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">
            Equity glide path
          </p>
          <GlideMiniChart glide_path={goal.glide_path} />
        </div>
      )}
    </div>
  );
}

// ── Add Goal Modal ────────────────────────────────────────────────────────────

const GOAL_TYPES = [
  { icon: "🏖️", label: "Retirement", value: "retirement" },
  { icon: "🏠", label: "House", value: "house" },
  { icon: "🎓", label: "Education", value: "education" },
  { icon: "🛡️", label: "Emergency", value: "emergency" },
  { icon: "📈", label: "Wealth", value: "wealth" },
  { icon: "💰", label: "Income", value: "income" },
];

const DEFAULT_NAMES: Record<string, string> = {
  retirement: "Retirement Fund",
  house: "House Down Payment",
  education: "Education Fund",
  emergency: "Emergency Fund",
  wealth: "Wealth Building",
  income: "Income Portfolio",
};

function AddGoalModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [goalType, setGoalType] = useState("retirement");
  const [name, setName] = useState(DEFAULT_NAMES["retirement"]);
  const [targetAmount, setTargetAmount] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [monthlyContrib, setMonthlyContrib] = useState("");

  const handleTypeChange = useCallback((type: string) => {
    setGoalType(type);
    setName(DEFAULT_NAMES[type] ?? "");
  }, []);

  const mutation = useMutation({
    mutationFn: () =>
      createGoal({
        name,
        goal_type: goalType,
        target_amount: Number(targetAmount.replace(/[^0-9.]/g, "")),
        target_date: targetDate || null,
        monthly_contribution: Number(monthlyContrib.replace(/[^0-9.]/g, "")),
      }),
    onSuccess: () => {
      toast.success("Goal created!");
      qc.invalidateQueries({ queryKey: ["robo-goals"] });
      onClose();
    },
    onError: () => toast.error("Failed to create goal"),
  });

  const valid = name && targetAmount && monthlyContrib;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl w-full max-w-md p-5 space-y-5">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-[var(--text-primary)]">Add Financial Goal</h3>
          <button
            onClick={onClose}
            className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Goal type */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wider">
            Goal type
          </label>
          <div className="grid grid-cols-3 gap-2">
            {GOAL_TYPES.map((g) => (
              <button
                key={g.value}
                onClick={() => handleTypeChange(g.value)}
                className={cn(
                  "flex flex-col items-center gap-1 py-3 rounded-xl border text-xs font-medium transition-all",
                  goalType === g.value
                    ? "bg-blue-600/20 border-blue-500 text-blue-400"
                    : "bg-[var(--bg-base,#0f172a)] border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:border-blue-500/40"
                )}
              >
                <span className="text-lg">{g.icon}</span>
                {g.label}
              </button>
            ))}
          </div>
        </div>

        {/* Name */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wider">
            Goal name
          </label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Retirement Fund"
            className="w-full bg-[var(--bg-base,#0f172a)] border border-[var(--border-subtle)] text-[var(--text-primary)] rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-blue-500 transition-colors placeholder:text-[var(--text-tertiary)]"
          />
        </div>

        {/* Target amount */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wider">
              Target amount
            </label>
            <input
              value={targetAmount}
              onChange={(e) => setTargetAmount(e.target.value)}
              placeholder="$500,000"
              className="w-full bg-[var(--bg-base,#0f172a)] border border-[var(--border-subtle)] text-[var(--text-primary)] rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-blue-500 transition-colors placeholder:text-[var(--text-tertiary)]"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wider">
              Monthly contribution
            </label>
            <input
              value={monthlyContrib}
              onChange={(e) => setMonthlyContrib(e.target.value)}
              placeholder="$500"
              className="w-full bg-[var(--bg-base,#0f172a)] border border-[var(--border-subtle)] text-[var(--text-primary)] rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-blue-500 transition-colors placeholder:text-[var(--text-tertiary)]"
            />
          </div>
        </div>

        {/* Target date */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wider">
            Target date <span className="normal-case font-normal">(optional)</span>
          </label>
          <input
            type="date"
            value={targetDate}
            onChange={(e) => setTargetDate(e.target.value)}
            className="w-full bg-[var(--bg-base,#0f172a)] border border-[var(--border-subtle)] text-[var(--text-primary)] rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        <button
          onClick={() => mutation.mutate()}
          disabled={!valid || mutation.isPending}
          className={cn(
            "w-full py-2.5 rounded-xl text-sm font-semibold transition-colors",
            valid
              ? "bg-blue-600 hover:bg-blue-500 text-white"
              : "bg-[var(--border-subtle)] text-[var(--text-tertiary)] cursor-not-allowed"
          )}
        >
          {mutation.isPending ? "Creating…" : "Create Goal"}
        </button>
      </div>
    </div>
  );
}

// ── Empty State ───────────────────────────────────────────────────────────────

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 px-4 text-center space-y-5">
      <div className="w-16 h-16 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
        <Target size={32} className="text-blue-400" />
      </div>
      <div className="space-y-1">
        <h2 className="text-xl font-bold text-[var(--text-primary)]">Set your first financial goal</h2>
        <p className="text-sm text-[var(--text-tertiary)] max-w-xs">
          Track your progress toward retirement, a house, education, or any other milestone.
        </p>
      </div>
      <button
        onClick={onAdd}
        className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-semibold transition-colors"
      >
        <Plus size={16} />
        Add Goal
      </button>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function GoalsPage() {
  const [addOpen, setAddOpen] = useState(false);
  const [projectionGoalId, setProjectionGoalId] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["robo-goals"],
    queryFn: getGoals,
    staleTime: 30_000,
    retry: 1,
  });

  const goals = data?.goals ?? [];

  const projectionGoal = goals.find((g) => g.id === projectionGoalId);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Target size={20} className="text-blue-400" />
          <h1 className="text-xl font-bold text-[var(--text-primary)]">Financial Goals</h1>
        </div>
        {goals.length > 0 && (
          <button
            onClick={() => setAddOpen(true)}
            className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-xl transition-colors"
          >
            <Plus size={15} />
            Add Goal
          </button>
        )}
      </div>

      {/* Goals list or empty state */}
      {goals.length === 0 ? (
        <EmptyState onAdd={() => setAddOpen(true)} />
      ) : (
        <div className="space-y-4">
          {goals.map((goal) => (
            <GoalCard
              key={goal.id}
              goal={goal}
              onSelectProjection={(id) => setProjectionGoalId(id)}
            />
          ))}

          <button
            onClick={() => setAddOpen(true)}
            className="w-full py-3 border-2 border-dashed border-[var(--border-subtle)] hover:border-blue-500/50 text-[var(--text-tertiary)] hover:text-blue-400 rounded-xl text-sm font-medium flex items-center justify-center gap-2 transition-colors"
          >
            <Plus size={16} />
            Add New Goal
          </button>
        </div>
      )}

      {/* Modals / drawers */}
      {addOpen && <AddGoalModal onClose={() => setAddOpen(false)} />}

      {projectionGoalId !== null && projectionGoal && (
        <ProjectionDrawer
          goalId={projectionGoalId}
          goalName={projectionGoal.name}
          onClose={() => setProjectionGoalId(null)}
        />
      )}
    </div>
  );
}

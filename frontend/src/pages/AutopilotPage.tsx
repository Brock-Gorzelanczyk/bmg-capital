import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Zap,
  BarChart2,
  PieChart,
  Banknote,
  Search,
  BookOpen,
  FileText,
  Receipt,
  Bell,
  Settings,
  Shield,
  ChevronDown,
  ChevronUp,
  X,
  Download,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  CheckCircle,
  SkipForward,
  XCircle,
  Pencil,
  Clock,
} from "lucide-react";
import { toast } from "sonner";
import {
  getAutopilotStatus,
  getAutopilotActivity,
  getAutopilotPolicies,
  updatePolicy,
  getGuardrails,
  updateGuardrails,
  pauseAll,
  resumeAll,
  getTodaySummary,
  type AutopilotAction,
  type AutopilotPolicy,
  type AutopilotGuardrail,
} from "@/api/autopilot";
import { getRecentSignals } from "@/api/bots";
import { cn } from "@/lib/utils";

// ─── Category metadata ─────────────────────────────────────────────────────────

const CATEGORY_META: Record<
  string,
  { label: string; Icon: React.ComponentType<{ size?: number; className?: string }> }
> = {
  trading:   { label: "Trading & Strategies",       Icon: BarChart2 },
  portfolio: { label: "Portfolio Management",        Icon: PieChart  },
  money:     { label: "Money Movement",              Icon: Banknote  },
  research:  { label: "Research & Watchlists",       Icon: Search    },
  learning:  { label: "Learning & Growth",           Icon: BookOpen  },
  journal:   { label: "Journal & Reflection",        Icon: FileText  },
  tax:       { label: "Tax & Compliance",            Icon: Receipt   },
  alerts:    { label: "Alerts & Notifications",      Icon: Bell      },
  account:   { label: "Account & Settings",          Icon: Settings  },
};

const ALL_CATEGORIES = Object.keys(CATEGORY_META);

// ─── Result pill ───────────────────────────────────────────────────────────────

function ResultPill({ result }: { result: AutopilotAction["result"] }) {
  if (result === "success") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-[#84cc16]/15 text-[#84cc16]">
        <CheckCircle size={10} /> success
      </span>
    );
  }
  if (result === "skipped") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-yellow-500/15 text-yellow-400">
        <SkipForward size={10} /> skipped
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-red-500/15 text-red-400">
      <XCircle size={10} /> failed
    </span>
  );
}

// ─── Category badge ────────────────────────────────────────────────────────────

const CAT_COLORS: Record<string, string> = {
  trading:   "bg-blue-500/15 text-blue-400",
  portfolio: "bg-purple-500/15 text-purple-400",
  money:     "bg-emerald-500/15 text-emerald-400",
  research:  "bg-cyan-500/15 text-cyan-400",
  learning:  "bg-amber-500/15 text-amber-400",
  journal:   "bg-pink-500/15 text-pink-400",
  tax:       "bg-orange-500/15 text-orange-400",
  alerts:    "bg-yellow-500/15 text-yellow-400",
  account:   "bg-slate-500/15 text-slate-400",
};

function CategoryBadge({ category }: { category: string }) {
  const label = CATEGORY_META[category]?.label ?? category;
  const color = CAT_COLORS[category] ?? "bg-zinc-500/15 text-zinc-400";
  return (
    <span className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-full", color)}>
      {label}
    </span>
  );
}

// ─── Inline config panel ───────────────────────────────────────────────────────

function ConfigPanel({
  policy,
  onClose,
}: {
  policy: AutopilotPolicy;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { category, config } = policy;

  const [rebalanceThreshold, setRebalanceThreshold] = useState<number>(
    typeof config.rebalance_threshold_pct === "number" ? config.rebalance_threshold_pct : 5
  );
  const [dividendReinvest, setDividendReinvest] = useState<boolean>(
    config.dividend_reinvest === true
  );
  const [roundUps, setRoundUps] = useState<boolean>(config.round_ups === true);
  const [cashSweep, setCashSweep] = useState<number>(
    typeof config.cash_sweep_threshold === "number" ? config.cash_sweep_threshold : 500
  );
  const [autoCurate, setAutoCurate] = useState<boolean>(config.auto_curate_watchlist === true);
  const [earningsPrep, setEarningsPrep] = useState<boolean>(config.earnings_prep === true);
  const [smartBatch, setSmartBatch] = useState<boolean>(config.smart_batch === true);
  const [maxPush, setMaxPush] = useState<string>(
    typeof config.max_push_per_day === "string"
      ? config.max_push_per_day
      : String(config.max_push_per_day ?? "unlimited")
  );

  const mut = useMutation({
    mutationFn: (newConfig: Record<string, unknown>) =>
      updatePolicy(category, { config: newConfig }),
    onSuccess: () => {
      toast.success("Settings saved");
      qc.invalidateQueries({ queryKey: ["autopilot-policies"] });
      onClose();
    },
    onError: () => toast.error("Failed to save settings"),
  });

  function buildConfig(): Record<string, unknown> {
    switch (category) {
      case "portfolio":
        return { rebalance_threshold_pct: rebalanceThreshold, dividend_reinvest: dividendReinvest };
      case "money":
        return { round_ups: roundUps, cash_sweep_threshold: cashSweep };
      case "research":
        return { auto_curate_watchlist: autoCurate, earnings_prep: earningsPrep };
      case "alerts":
        return { smart_batch: smartBatch, max_push_per_day: maxPush };
      default:
        return config;
    }
  }

  function Toggle({ value, onChange, label }: { value: boolean; onChange: (v: boolean) => void; label: string }) {
    return (
      <label className="flex items-center justify-between gap-3 cursor-pointer">
        <span className="text-sm text-[var(--text-secondary)]">{label}</span>
        <button
          type="button"
          onClick={() => onChange(!value)}
          className={cn(
            "relative w-9 h-5 rounded-full transition-colors duration-200",
            value ? "bg-[#84cc16]" : "bg-[var(--bg-elevated-2)]"
          )}
        >
          <span
            className={cn(
              "absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200",
              value ? "translate-x-[18px]" : "translate-x-0.5"
            )}
          />
        </button>
      </label>
    );
  }

  function renderFields() {
    if (category === "portfolio") {
      return (
        <>
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm text-[var(--text-secondary)]">Rebalance threshold</span>
              <span className="text-sm font-semibold text-[#84cc16]">{rebalanceThreshold}%</span>
            </div>
            <input
              type="range"
              min={1}
              max={20}
              value={rebalanceThreshold}
              onChange={e => setRebalanceThreshold(Number(e.target.value))}
              className="w-full accent-[#84cc16] cursor-pointer"
            />
            <div className="flex justify-between text-[10px] text-[var(--text-tertiary)] mt-0.5">
              <span>1%</span><span>20%</span>
            </div>
          </div>
          <Toggle value={dividendReinvest} onChange={setDividendReinvest} label="Dividend reinvestment" />
        </>
      );
    }
    if (category === "money") {
      return (
        <>
          <Toggle value={roundUps} onChange={setRoundUps} label="Round-ups" />
          <div>
            <label className="text-sm text-[var(--text-secondary)] block mb-1">Cash sweep threshold ($)</label>
            <input
              type="number"
              min={0}
              value={cashSweep}
              onChange={e => setCashSweep(Number(e.target.value))}
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#84cc16]"
            />
          </div>
        </>
      );
    }
    if (category === "research") {
      return (
        <>
          <Toggle value={autoCurate} onChange={setAutoCurate} label="Auto-curate watchlist" />
          <Toggle value={earningsPrep} onChange={setEarningsPrep} label="Earnings prep" />
        </>
      );
    }
    if (category === "alerts") {
      return (
        <>
          <Toggle value={smartBatch} onChange={setSmartBatch} label="Smart batch notifications" />
          <div>
            <label className="text-sm text-[var(--text-secondary)] block mb-2">Max push per day</label>
            <div className="flex gap-2">
              {["1", "4", "unlimited"].map(v => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setMaxPush(v)}
                  className={cn(
                    "flex-1 py-1.5 rounded-lg text-sm font-medium border transition-colors",
                    maxPush === v
                      ? "border-[#84cc16] bg-[#84cc16]/15 text-[#84cc16]"
                      : "border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:border-[var(--border-emphasis)]"
                  )}
                >
                  {v}
                </button>
              ))}
            </div>
          </div>
        </>
      );
    }
    return (
      <p className="text-sm text-[var(--text-tertiary)] italic">Advanced settings coming soon</p>
    );
  }

  return (
    <div className="mt-2 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-[var(--text-primary)]">Configure</span>
        <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] cursor-pointer">
          <X size={14} />
        </button>
      </div>
      <div className="space-y-4">{renderFields()}</div>
      {category !== "trading" && category !== "learning" && category !== "journal" && category !== "tax" && category !== "account" && (
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            onClick={() => mut.mutate(buildConfig())}
            disabled={mut.isPending}
            className="px-4 py-1.5 bg-[#84cc16] text-black text-sm font-semibold rounded-lg hover:bg-[#84cc16]/90 disabled:opacity-50 transition-colors cursor-pointer"
          >
            {mut.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Inline log panel ──────────────────────────────────────────────────────────

function InlineLog({ category, onClose }: { category: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["autopilot-activity", category, 1],
    queryFn: () => getAutopilotActivity({ category, page: 1 }),
    staleTime: 30_000,
  });

  const items = data?.slice(0, 5) ?? [];

  return (
    <div className="mt-2 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-[var(--text-primary)]">Recent activity</span>
        <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] cursor-pointer">
          <X size={14} />
        </button>
      </div>
      {isLoading ? (
        <p className="text-xs text-[var(--text-tertiary)]">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-xs text-[var(--text-tertiary)]">No recent actions</p>
      ) : (
        <div className="space-y-2">
          {items.map(action => (
            <div key={action.id} className="flex items-start gap-2">
              <ResultPill result={action.result} />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-[var(--text-primary)] truncate">{action.ai_rationale}</p>
                <p className="text-[10px] text-[var(--text-tertiary)]">
                  {new Date(action.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  {action.asset ? ` · ${action.asset}` : ""}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Category card ─────────────────────────────────────────────────────────────

function CategoryCard({
  policy,
  statusEntry,
  globalPaused,
}: {
  policy: AutopilotPolicy;
  statusEntry: { name: string; enabled: boolean; last_action: string | null; actions_today: number } | undefined;
  globalPaused: boolean;
}) {
  const qc = useQueryClient();
  const [panel, setPanel] = useState<"none" | "config" | "log">("none");
  const { category } = policy;
  const meta = CATEGORY_META[category];
  const Icon = meta?.Icon ?? Settings;
  const label = meta?.label ?? category;

  const actionsToday = statusEntry?.actions_today ?? 0;
  const lastAction = statusEntry?.last_action;
  const enabled = policy.enabled;

  const toggleMut = useMutation({
    mutationFn: (val: boolean) => updatePolicy(category, { enabled: val }),
    onSuccess: (updated) => {
      toast.success(updated.enabled ? `${label} enabled` : `${label} disabled`);
      qc.invalidateQueries({ queryKey: ["autopilot-policies"] });
      qc.invalidateQueries({ queryKey: ["autopilot-status"] });
    },
    onError: () => toast.error("Failed to update policy"),
  });

  return (
    <div>
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 relative overflow-hidden">
        {/* Paused overlay */}
        {globalPaused && (
          <div className="absolute inset-0 bg-black/40 flex items-center justify-center rounded-xl z-10">
            <span className="text-xs font-bold text-red-400 tracking-wider">PAUSED</span>
          </div>
        )}

        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <Icon size={16} className="text-[var(--text-tertiary)] shrink-0" />
            <span className="text-sm font-semibold text-[var(--text-primary)] truncate">{label}</span>
          </div>
          {/* Toggle */}
          <button
            type="button"
            onClick={() => toggleMut.mutate(!enabled)}
            disabled={toggleMut.isPending}
            className={cn(
              "flex items-center gap-1.5 text-[10px] font-bold px-2.5 py-1 rounded-full border transition-colors cursor-pointer shrink-0",
              enabled
                ? "border-[#84cc16] text-[#84cc16] bg-[#84cc16]/10 hover:bg-[#84cc16]/20"
                : "border-[var(--border-emphasis)] text-[var(--text-tertiary)] hover:border-[var(--border-subtle)]"
            )}
          >
            <span className={cn("w-1.5 h-1.5 rounded-full", enabled ? "bg-[#84cc16]" : "bg-[var(--text-tertiary)]")} />
            {enabled ? "ON" : "OFF"}
          </button>
        </div>

        <div className="mt-2 space-y-0.5">
          <p className="text-xs text-[var(--text-tertiary)]">
            {enabled ? "Active" : "Disabled"} · {actionsToday} action{actionsToday !== 1 ? "s" : ""} today
          </p>
          {lastAction && (
            <p className="text-xs text-[var(--text-secondary)] line-clamp-1">
              Last: &ldquo;{lastAction}&rdquo;
            </p>
          )}
        </div>

        <div className="mt-3 flex items-center gap-2">
          <button
            onClick={() => setPanel(p => p === "config" ? "none" : "config")}
            className="text-[10px] font-semibold px-2.5 py-1 rounded-lg bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)]/80 transition-colors cursor-pointer"
          >
            Configure
          </button>
          <button
            onClick={() => setPanel(p => p === "log" ? "none" : "log")}
            className="text-[10px] font-semibold px-2.5 py-1 rounded-lg bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)]/80 transition-colors cursor-pointer"
          >
            Log
          </button>
        </div>
      </div>

      {panel === "config" && (
        <ConfigPanel policy={policy} onClose={() => setPanel("none")} />
      )}
      {panel === "log" && (
        <InlineLog category={category} onClose={() => setPanel("none")} />
      )}
    </div>
  );
}

// ─── Guardrails panel ──────────────────────────────────────────────────────────

function GuardrailsPanel() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);

  const { data: guardrails } = useQuery({
    queryKey: ["autopilot-guardrails"],
    queryFn: getGuardrails,
    staleTime: 60_000,
  });

  const [form, setForm] = useState<Partial<AutopilotGuardrail>>({});

  function startEdit() {
    if (guardrails) setForm({ ...guardrails });
    setEditing(true);
  }

  const saveMut = useMutation({
    mutationFn: (data: Partial<AutopilotGuardrail>) => updateGuardrails(data),
    onSuccess: () => {
      toast.success("Guardrails updated");
      qc.invalidateQueries({ queryKey: ["autopilot-guardrails"] });
      setEditing(false);
    },
    onError: () => toast.error("Failed to update guardrails"),
  });

  function Field({
    label,
    field,
    suffix,
    min,
    max,
  }: {
    label: string;
    field: keyof AutopilotGuardrail;
    suffix?: string;
    min?: number;
    max?: number;
  }) {
    const current = guardrails?.[field];
    const val = form[field];
    return (
      <div className="flex items-center justify-between gap-4">
        <span className="text-sm text-[var(--text-secondary)]">{label}</span>
        {editing ? (
          <div className="flex items-center gap-1">
            <input
              type="number"
              min={min}
              max={max}
              value={typeof val === "number" ? val : typeof val === "boolean" ? (val ? 1 : 0) : ""}
              onChange={e =>
                setForm(f => ({
                  ...f,
                  [field]: field === "global_paused" ? e.target.value === "1" : Number(e.target.value),
                }))
              }
              className="w-20 bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded px-2 py-1 text-xs text-[var(--text-primary)] text-right focus:outline-none focus:border-[#84cc16]"
            />
            {suffix && <span className="text-xs text-[var(--text-tertiary)]">{suffix}</span>}
          </div>
        ) : (
          <span className="text-sm font-semibold text-[var(--text-primary)]">
            {typeof current === "number" ? current : current === true ? "Yes" : current === false ? "No" : "—"}
            {suffix && typeof current === "number" ? suffix : ""}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between cursor-pointer"
      >
        <div className="flex items-center gap-2">
          <Shield size={16} className="text-[#84cc16]" />
          <span className="text-sm font-semibold text-[var(--text-primary)]">Hard Guardrails</span>
        </div>
        <div className="flex items-center gap-2">
          {guardrails && !open && (
            <span className="text-xs text-[var(--text-tertiary)]">
              Daily {guardrails.daily_loss_limit_pct}% · Weekly {guardrails.weekly_loss_limit_pct}% · Max {guardrails.max_open_positions} pos
            </span>
          )}
          {open ? <ChevronUp size={14} className="text-[var(--text-tertiary)]" /> : <ChevronDown size={14} className="text-[var(--text-tertiary)]" />}
        </div>
      </button>

      {open && (
        <div className="mt-4 space-y-3">
          {!editing && (
            <div className="flex justify-end">
              <button
                onClick={startEdit}
                className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
              >
                <Pencil size={12} /> Edit
              </button>
            </div>
          )}

          <Field label="Daily loss limit" field="daily_loss_limit_pct" suffix="%" min={0} max={100} />
          <Field label="Weekly loss limit" field="weekly_loss_limit_pct" suffix="%" min={0} max={100} />
          <Field label="Max open positions" field="max_open_positions" min={1} max={100} />
          <Field label="Cash drain per week" field="cash_drain_per_week" suffix=" $/wk" min={0} />
          <Field label="Max position concentration" field="max_position_concentration_pct" suffix="%" min={0} max={100} />
          <Field label="Max subscriptions cancel / wk" field="max_subscriptions_cancel_per_week" min={0} />

          <p className="text-xs text-[var(--text-tertiary)] italic border-t border-[var(--border-subtle)] pt-3">
            Note: These guardrails can only be tightened — loosening requires a 24-hour review period.
          </p>

          {editing && (
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={() => setEditing(false)}
                className="px-3 py-1.5 text-sm text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={() => saveMut.mutate(form)}
                disabled={saveMut.isPending}
                className="px-4 py-1.5 bg-[#84cc16] text-black text-sm font-semibold rounded-lg hover:bg-[#84cc16]/90 disabled:opacity-50 transition-colors cursor-pointer"
              >
                {saveMut.isPending ? "Saving…" : "Save"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Pause confirmation modal ──────────────────────────────────────────────────

function PauseModal({
  open,
  onConfirm,
  onCancel,
  isPending,
}: {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  isPending: boolean;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-2xl p-6 max-w-sm w-full shadow-2xl shadow-black/50">
        <div className="flex items-center gap-3 mb-4">
          <AlertTriangle size={20} className="text-red-400 shrink-0" />
          <h2 className="text-base font-bold text-[var(--text-primary)]">Pause all automation?</h2>
        </div>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          All Autopilot categories will be paused immediately. No actions will execute until you resume. Open positions will not be affected.
        </p>
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 py-2 rounded-xl border border-[var(--border-subtle)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
          >
            Keep running
          </button>
          <button
            onClick={onConfirm}
            disabled={isPending}
            className="flex-1 py-2 rounded-xl bg-red-500 hover:bg-red-600 text-white text-sm font-semibold disabled:opacity-50 transition-colors cursor-pointer"
          >
            {isPending ? "Pausing…" : "Pause all"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Activity log table ────────────────────────────────────────────────────────

function ActivityLog({ initialCategory }: { initialCategory?: string }) {
  const [activeCategory, setActiveCategory] = useState<string>(initialCategory ?? "all");
  const [page, setPage] = useState(1);

  const { data: actions, isLoading } = useQuery({
    queryKey: ["autopilot-activity", activeCategory, page],
    queryFn: () =>
      getAutopilotActivity({
        category: activeCategory === "all" ? undefined : activeCategory,
        page,
      }),
    staleTime: 30_000,
  });

  const tabs = ["all", ...ALL_CATEGORIES];

  function handleExport() {
    window.open(
      `/api/autopilot/activity/export${activeCategory !== "all" ? `?category=${activeCategory}` : ""}`,
      "_blank"
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">Activity Log</h3>
        <button
          onClick={handleExport}
          className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
        >
          <Download size={13} /> Export
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex items-center gap-1 overflow-x-auto pb-2 mb-3 scrollbar-none">
        {tabs.map(tab => (
          <button
            key={tab}
            onClick={() => { setActiveCategory(tab); setPage(1); }}
            className={cn(
              "shrink-0 px-3 py-1 rounded-full text-xs font-medium transition-colors cursor-pointer",
              activeCategory === tab
                ? "bg-[#84cc16] text-black"
                : "bg-[var(--bg-elevated)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            )}
          >
            {tab === "all" ? "All" : CATEGORY_META[tab]?.label.split(" ")[0] ?? tab}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-sm text-[var(--text-tertiary)]">Loading…</div>
        ) : !Array.isArray(actions) || actions.length === 0 ? (
          <div className="p-8 text-center text-sm text-[var(--text-tertiary)] flex flex-col items-center gap-2">
            <Clock size={18} className="text-[var(--text-tertiary)]" />
            <span>Awaiting first signal — runs next at market open.</span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--border-subtle)]">
                  <th className="text-left px-4 py-2.5 text-[var(--text-tertiary)] font-semibold">Time</th>
                  <th className="text-left px-4 py-2.5 text-[var(--text-tertiary)] font-semibold">Category</th>
                  <th className="text-left px-4 py-2.5 text-[var(--text-tertiary)] font-semibold">Action</th>
                  <th className="text-left px-4 py-2.5 text-[var(--text-tertiary)] font-semibold">Asset</th>
                  <th className="text-left px-4 py-2.5 text-[var(--text-tertiary)] font-semibold">Rationale</th>
                  <th className="text-left px-4 py-2.5 text-[var(--text-tertiary)] font-semibold">Result</th>
                </tr>
              </thead>
              <tbody>
                {actions.map((action, idx) => (
                  <tr
                    key={action.id}
                    className={cn(
                      "border-b border-[var(--border-subtle)] last:border-0",
                      idx % 2 === 0 ? "bg-transparent" : "bg-[var(--bg-elevated-2)]/30"
                    )}
                  >
                    <td className="px-4 py-2.5 text-[var(--text-tertiary)] whitespace-nowrap">
                      {new Date(action.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </td>
                    <td className="px-4 py-2.5">
                      <CategoryBadge category={action.category} />
                    </td>
                    <td className="px-4 py-2.5 text-[var(--text-secondary)] whitespace-nowrap">{action.action_type}</td>
                    <td className="px-4 py-2.5 text-[var(--text-secondary)] font-mono">{action.asset ?? "—"}</td>
                    <td className="px-4 py-2.5 text-[var(--text-secondary)] max-w-[260px] truncate">{action.ai_rationale}</td>
                    <td className="px-4 py-2.5">
                      <ResultPill result={action.result} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between mt-3">
        <span className="text-xs text-[var(--text-tertiary)]">Page {page}</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] disabled:opacity-40 transition-colors cursor-pointer"
          >
            <ChevronLeft size={14} className="text-[var(--text-secondary)]" />
          </button>
          <button
            onClick={() => setPage(p => p + 1)}
            disabled={!actions || actions.length < 50}
            className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] disabled:opacity-40 transition-colors cursor-pointer"
          >
            <ChevronRight size={14} className="text-[var(--text-secondary)]" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export default function AutopilotPage() {
  const qc = useQueryClient();
  const [pauseModalOpen, setPauseModalOpen] = useState(false);

  const { data: status } = useQuery({
    queryKey: ["autopilot-status"],
    queryFn: getAutopilotStatus,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const { data: policies } = useQuery({
    queryKey: ["autopilot-policies"],
    queryFn: getAutopilotPolicies,
    staleTime: 30_000,
  });

  const { data: summary } = useQuery({
    queryKey: ["autopilot-summary-today"],
    queryFn: getTodaySummary,
    staleTime: 60_000,
  });

  // Pull bot signals so the "today" count aligns with Mission Control.
  // The autopilot status endpoint only counts autopilot actions; bots fire
  // signals via a separate pipeline that Mission Control shows.
  const { data: recentSignalsData } = useQuery({
    queryKey: ["bots-signals-recent", 500],
    queryFn: () => getRecentSignals(500),
    staleTime: 60_000,
  });

  const pauseMut = useMutation({
    mutationFn: pauseAll,
    onSuccess: () => {
      toast.success("Autopilot paused");
      setPauseModalOpen(false);
      qc.invalidateQueries({ queryKey: ["autopilot-status"] });
    },
    onError: () => toast.error("Failed to pause autopilot"),
  });

  const resumeMut = useMutation({
    mutationFn: resumeAll,
    onSuccess: () => {
      toast.success("Autopilot resumed");
      qc.invalidateQueries({ queryKey: ["autopilot-status"] });
    },
    onError: () => toast.error("Failed to resume autopilot"),
  });

  const globalPaused = status?.global_paused ?? false;

  // Count today's bot signals (same data source as Mission Control's "signals fired").
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const todaySignalsCount = (recentSignalsData?.signals ?? []).filter(
    (s) => new Date(s.ts).getTime() >= todayStart.getTime()
  ).length;

  // Use whichever source gives the highest count — all are additive views of
  // the same activity. Prefer the combined view so Autopilot matches Mission Control.
  const totalActions =
    Math.max(
      status?.total_actions_today ?? 0,
      summary?.total_actions ?? 0,
      todaySignalsCount
    ) || 0;

  const healthScore = status?.health_score ?? 0;

  // Build policy map keyed by category
  const policyMap: Record<string, AutopilotPolicy> = {};
  (Array.isArray(policies) ? policies : []).forEach(p => { policyMap[p.category] = p; });

  // Build status entry map keyed by category name
  const statusMap: Record<string, NonNullable<typeof status>["categories"][0]> = {};
  (Array.isArray(status?.categories) ? status!.categories : []).forEach(c => { statusMap[c.name] = c; });

  // Summary line items
  const highlights = summary?.highlights ?? [];

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-8">

      {/* Global paused banner */}
      {globalPaused && (
        <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
          <AlertTriangle size={18} className="text-red-400 shrink-0" />
          <p className="text-sm font-semibold text-red-400 flex-1">AUTOPILOT PAUSED — No actions are executing</p>
          <button
            onClick={() => resumeMut.mutate()}
            disabled={resumeMut.isPending}
            className="px-4 py-1.5 bg-red-500 hover:bg-red-600 text-white text-sm font-semibold rounded-lg disabled:opacity-50 transition-colors cursor-pointer"
          >
            {resumeMut.isPending ? "Resuming…" : "Resume"}
          </button>
        </div>
      )}

      {/* Hero */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <Zap size={20} className="text-[#84cc16]" />
            <span className="text-xs font-bold tracking-[0.15em] uppercase text-[var(--text-tertiary)]">Autopilot</span>
          </div>
          <div className="flex items-center gap-2">
            {/* Health score chip */}
            {healthScore === 0 ? (
              <div className="flex items-center gap-1.5 bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-full px-3 py-1">
                <span className="text-xs text-[var(--text-tertiary)]">System ready. First signals appear after the next market open.</span>
              </div>
            ) : (
              <div className="flex items-center gap-1.5 bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-full px-3 py-1">
                <span className="text-xs text-[var(--text-tertiary)]">Health</span>
                <span className={cn(
                  "text-xs font-bold",
                  healthScore >= 80 ? "text-[#84cc16]" : healthScore >= 50 ? "text-yellow-400" : "text-red-400"
                )}>{healthScore}</span>
              </div>
            )}
            {/* Pause / Resume */}
            {globalPaused ? (
              <button
                onClick={() => resumeMut.mutate()}
                disabled={resumeMut.isPending}
                className="px-4 py-1.5 bg-[#84cc16] hover:bg-[#84cc16]/90 text-black text-sm font-semibold rounded-xl disabled:opacity-50 transition-colors cursor-pointer"
              >
                {resumeMut.isPending ? "Resuming…" : "Resume All"}
              </button>
            ) : (
              <button
                onClick={() => setPauseModalOpen(true)}
                className="px-4 py-1.5 bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-secondary)] text-sm font-semibold rounded-xl hover:border-red-500/50 hover:text-red-400 transition-colors cursor-pointer"
              >
                Pause All
              </button>
            )}
          </div>
        </div>

        <div className="mt-5">
          {totalActions === 0 ? (
            <p className="text-base text-[var(--text-secondary)]">
              No automations ran today. Bots execute at market open (9:30am ET) on weekdays.
            </p>
          ) : (
            <p className="text-2xl font-bold text-[var(--text-primary)]">
              Today, BMG did{" "}
              <span
                className="text-[#84cc16] animate-pulse"
                style={{ animationDuration: "3s" }}
              >
                {totalActions}
              </span>{" "}
              things for you
            </p>
          )}
        </div>

        {highlights.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
            {highlights.map((h, i) => (
              <span key={i} className="text-sm text-[var(--text-secondary)]">{h}</span>
            ))}
          </div>
        )}

        {summary && summary.by_category && Object.keys(summary.by_category).length > 0 && (
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
            {Object.entries(summary.by_category).map(([cat, count]) => (
              <span key={cat} className="text-xs text-[var(--text-tertiary)]">
                {CATEGORY_META[cat]?.label.split(" ")[0] ?? cat}: <strong className="text-[var(--text-secondary)]">{count}</strong>
              </span>
            ))}
          </div>
        )}

        <button
          onClick={() => document.getElementById("autopilot-activity-log")?.scrollIntoView({ behavior: "smooth" })}
          className="mt-4 text-xs text-[#84cc16] hover:underline cursor-pointer"
        >
          View full activity log &darr;
        </button>
      </div>

      {/* Category grid */}
      <div>
        <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Automation Categories</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {ALL_CATEGORIES.map(cat => {
            const policy = policyMap[cat] ?? {
              id: 0,
              category: cat,
              enabled: false,
              config: {},
            };
            return (
              <CategoryCard
                key={cat}
                policy={policy}
                statusEntry={statusMap[cat]}
                globalPaused={globalPaused}
              />
            );
          })}
        </div>
      </div>

      {/* Guardrails */}
      <GuardrailsPanel />

      {/* Activity log */}
      <div id="autopilot-activity-log">
        <ActivityLog />
      </div>

      {/* Pause modal */}
      <PauseModal
        open={pauseModalOpen}
        onConfirm={() => pauseMut.mutate()}
        onCancel={() => setPauseModalOpen(false)}
        isPending={pauseMut.isPending}
      />
    </div>
  );
}

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  SlidersHorizontal,
  Plus,
  Trash2,
  ToggleLeft,
  ToggleRight,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  BarChart2,
  Globe,
  Play,
  X,
  ChevronRight,
  ChevronLeft,
  CheckCircle2,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getRules,
  createRule,
  updateRule,
  deleteRule,
  testRule,
  type UserRule,
  type RuleCreate,
} from "@/api/rules";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TriggerType =
  | "price_above"
  | "price_below"
  | "vix_above"
  | "rsi_below"
  | "rsi_above"
  | "regime_is";

type ActionType = "buy" | "sell" | "reduce_position" | "notify";

interface RuleForm {
  trigger_type: TriggerType | "";
  trigger_symbol: string;
  trigger_value: string;
  trigger_regime: string;
  action_type: ActionType | "";
  action_symbol: string;
  action_amount: string;
  action_unit: "dollars" | "shares" | "pct_of_account";
  name: string;
  description: string;
}

const REGIME_OPTIONS = ["Trend-Up", "Trend-Down", "Range", "Crisis"];

const TRIGGER_OPTIONS: {
  type: TriggerType;
  label: string;
  sub: string;
  Icon: React.ComponentType<{ size?: number; className?: string }>;
  needsSymbol: boolean;
  needsValue: boolean;
  needsRegime: boolean;
}[] = [
  {
    type: "price_above",
    label: "Price crosses above",
    sub: "e.g. SPY > $480",
    Icon: TrendingUp,
    needsSymbol: true,
    needsValue: true,
    needsRegime: false,
  },
  {
    type: "price_below",
    label: "Price drops below",
    sub: "e.g. SPY < $450",
    Icon: TrendingDown,
    needsSymbol: true,
    needsValue: true,
    needsRegime: false,
  },
  {
    type: "vix_above",
    label: "VIX spikes above",
    sub: "e.g. VIX > 30",
    Icon: AlertTriangle,
    needsSymbol: false,
    needsValue: true,
    needsRegime: false,
  },
  {
    type: "rsi_below",
    label: "RSI oversold (below value)",
    sub: "e.g. RSI < 30",
    Icon: BarChart2,
    needsSymbol: true,
    needsValue: true,
    needsRegime: false,
  },
  {
    type: "rsi_above",
    label: "RSI overbought (above value)",
    sub: "e.g. RSI > 70",
    Icon: BarChart2,
    needsSymbol: true,
    needsValue: true,
    needsRegime: false,
  },
  {
    type: "regime_is",
    label: "Market regime is",
    sub: "e.g. regime = Crisis",
    Icon: Globe,
    needsSymbol: false,
    needsValue: false,
    needsRegime: true,
  },
];

const ACTION_OPTIONS: { type: ActionType; label: string; sub: string }[] = [
  { type: "buy", label: "Buy", sub: "Open a paper long position" },
  { type: "sell", label: "Sell", sub: "Close / reduce a position" },
  { type: "reduce_position", label: "Reduce 50%", sub: "Trim existing position by half" },
  { type: "notify", label: "Notify only", sub: "Alert me, no trade executed" },
];

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function triggerLabel(rule: UserRule): string {
  const t = rule.trigger_type;
  if (!t) return "—";
  if (t === "price_above") return `${rule.trigger_symbol} price > $${rule.trigger_value}`;
  if (t === "price_below") return `${rule.trigger_symbol} price < $${rule.trigger_value}`;
  if (t === "vix_above") return `VIX > ${rule.trigger_value}`;
  if (t === "rsi_below") return `${rule.trigger_symbol} RSI < ${rule.trigger_value}`;
  if (t === "rsi_above") return `${rule.trigger_symbol} RSI > ${rule.trigger_value}`;
  if (t === "regime_is") return `Regime = ${rule.trigger_regime}`;
  return t;
}

function actionLabel(rule: UserRule): string {
  const a = rule.action_type;
  if (!a) return "—";
  if (a === "notify") return "Notify me";
  if (a === "reduce_position") return `Reduce ${rule.action_symbol || ""} by 50%`;
  const unit = rule.action_unit === "dollars" ? `$${rule.action_amount}` :
    rule.action_unit === "shares" ? `${rule.action_amount} shares` :
    `${rule.action_amount}% of account`;
  return `${a === "buy" ? "Buy" : "Sell"} ${unit} of ${rule.action_symbol || ""}`;
}

const EMPTY_FORM: RuleForm = {
  trigger_type: "",
  trigger_symbol: "",
  trigger_value: "",
  trigger_regime: REGIME_OPTIONS[0],
  action_type: "",
  action_symbol: "",
  action_amount: "",
  action_unit: "dollars",
  name: "",
  description: "",
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function RulesPage() {
  const qc = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<RuleForm>(EMPTY_FORM);

  const { data: _rulesData, isLoading } = useQuery({
    queryKey: ["rules"],
    queryFn: getRules,
    staleTime: 30_000,
  });
  const rules: UserRule[] = Array.isArray(_rulesData) ? _rulesData : [];

  const createMut = useMutation({
    mutationFn: createRule,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rules"] });
      toast.success("Rule created");
      setShowModal(false);
      setStep(1);
      setForm(EMPTY_FORM);
    },
    onError: () => toast.error("Failed to create rule"),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<RuleCreate> }) =>
      updateRule(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rules"] });
    },
    onError: () => toast.error("Failed to update rule"),
  });

  const deleteMut = useMutation({
    mutationFn: deleteRule,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rules"] });
      toast.success("Rule deleted");
    },
    onError: () => toast.error("Failed to delete rule"),
  });

  const testMut = useMutation({
    mutationFn: testRule,
    onSuccess: (result) => {
      if (result.would_trigger) {
        toast.success(`Would trigger: ${result.reason}`, { duration: 5000 });
      } else {
        toast.info(`Would NOT trigger: ${result.reason}`, { duration: 5000 });
      }
    },
    onError: () => toast.error("Test failed"),
  });

  const activeCount = rules.filter((r) => r.is_active).length;

  // Current trigger config
  const triggerConfig = TRIGGER_OPTIONS.find((t) => t.type === form.trigger_type);

  function handleSubmit() {
    const payload: RuleCreate = {
      name: form.name || `Rule ${Date.now()}`,
      description: form.description || undefined,
      is_active: true,
      trigger_type: form.trigger_type || undefined,
      trigger_symbol: triggerConfig?.needsSymbol ? form.trigger_symbol.toUpperCase() : undefined,
      trigger_value: (triggerConfig?.needsValue && form.trigger_value) ? parseFloat(form.trigger_value) : undefined,
      trigger_regime: triggerConfig?.needsRegime ? form.trigger_regime : undefined,
      action_type: form.action_type || undefined,
      action_symbol: (form.action_type !== "notify" && form.action_type !== "reduce_position")
        ? form.action_symbol.toUpperCase()
        : form.action_type === "reduce_position" ? form.action_symbol.toUpperCase() : undefined,
      action_amount: (form.action_type !== "notify") ? parseFloat(form.action_amount) : undefined,
      action_unit: form.action_unit,
    };
    createMut.mutate(payload);
  }

  function canAdvance(): boolean {
    if (step === 1) return !!form.trigger_type;
    if (step === 2) {
      if (!triggerConfig) return false;
      if (triggerConfig.needsSymbol && !form.trigger_symbol) return false;
      if (triggerConfig.needsValue && !form.trigger_value) return false;
      if (triggerConfig.needsRegime && !form.trigger_regime) return false;
      return true;
    }
    if (step === 3) return !!form.action_type;
    if (step === 4) {
      if (form.action_type === "notify") return true;
      if (!form.action_amount) return false;
      if (form.action_type !== "reduce_position" && !form.action_symbol) return false;
      return true;
    }
    if (step === 5) return !!form.name;
    return false;
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
            <SlidersHorizontal size={18} className="text-blue-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[var(--text-primary)]">If-Then Rules</h1>
            <p className="text-sm text-[var(--text-tertiary)]">{activeCount} active rule{activeCount !== 1 ? "s" : ""}</p>
          </div>
        </div>
        <button
          onClick={() => { setShowModal(true); setStep(1); setForm(EMPTY_FORM); }}
          className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-400 text-white text-sm font-semibold rounded-lg transition-colors"
        >
          <Plus size={16} />
          New Rule
        </button>
      </div>

      {/* Empty state */}
      {!isLoading && rules.length === 0 && (
        <div className="border border-[var(--border-subtle)] rounded-xl p-8 text-center space-y-4">
          <SlidersHorizontal size={32} className="mx-auto text-[var(--text-tertiary)]" />
          <div>
            <p className="font-semibold text-[var(--text-primary)]">No rules yet</p>
            <p className="text-sm text-[var(--text-tertiary)] mt-1">
              Rules watch market conditions and trigger actions automatically.
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-xl mx-auto mt-4">
            {[
              { if: "VIX > 30", then: "Buy $500 GLD" },
              { if: "BTC-USD RSI < 30", then: "Buy $200 BTC-USD" },
              { if: "SPY price < $450", then: "Notify me" },
            ].map((ex) => (
              <div
                key={ex.if}
                className="text-left bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg p-3 text-xs"
              >
                <div className="text-[var(--text-tertiary)] mb-1">IF</div>
                <div className="font-mono text-blue-400 mb-2">{ex.if}</div>
                <div className="text-[var(--text-tertiary)] mb-1">THEN</div>
                <div className="font-mono text-emerald-400">{ex.then}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Rules list */}
      <div className="space-y-3">
        {rules.map((rule) => (
          <RuleCard
            key={rule.id}
            rule={rule}
            onToggle={(active) => updateMut.mutate({ id: rule.id, data: { is_active: active } })}
            onDelete={() => deleteMut.mutate(rule.id)}
            onTest={() => testMut.mutate(rule.id)}
            testing={testMut.isPending}
          />
        ))}
      </div>

      {/* New rule modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative w-full max-w-lg bg-[#111] border border-[var(--border-emphasis)] rounded-2xl shadow-2xl overflow-hidden">
            {/* Modal header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-subtle)]">
              <h2 className="font-bold text-[var(--text-primary)]">New If-Then Rule</h2>
              <div className="flex items-center gap-3">
                <span className="text-xs text-[var(--text-tertiary)]">Step {step} of 5</span>
                <button onClick={() => setShowModal(false)} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)]">
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Progress bar */}
            <div className="h-1 bg-[var(--bg-elevated-2)]">
              <div
                className="h-1 bg-blue-500 transition-all duration-300"
                style={{ width: `${(step / 5) * 100}%` }}
              />
            </div>

            <div className="px-6 py-6 space-y-4 min-h-[280px]">
              {/* Step 1: Choose trigger */}
              {step === 1 && (
                <div className="space-y-3">
                  <p className="text-sm font-semibold text-[var(--text-primary)]">IF… (choose a trigger)</p>
                  <div className="grid grid-cols-2 gap-2">
                    {TRIGGER_OPTIONS.map((opt) => (
                      <button
                        key={opt.type}
                        onClick={() => setForm((f) => ({ ...f, trigger_type: opt.type }))}
                        className={cn(
                          "flex items-start gap-3 p-3 rounded-xl border text-left transition-colors",
                          form.trigger_type === opt.type
                            ? "border-blue-500 bg-blue-500/10 text-blue-300"
                            : "border-[var(--border-subtle)] hover:border-[var(--border-emphasis)] text-[var(--text-secondary)]"
                        )}
                      >
                        <opt.Icon size={16} className="mt-0.5 shrink-0" />
                        <div>
                          <div className="text-xs font-semibold leading-tight">{opt.label}</div>
                          <div className="text-[10px] text-[var(--text-tertiary)] mt-0.5">{opt.sub}</div>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Step 2: Trigger details */}
              {step === 2 && triggerConfig && (
                <div className="space-y-4">
                  <p className="text-sm font-semibold text-[var(--text-primary)]">
                    <span className="text-blue-400">{triggerConfig.label}</span> — set the details
                  </p>
                  {triggerConfig.needsSymbol && (
                    <div>
                      <label className="block text-xs text-[var(--text-tertiary)] mb-1">Symbol</label>
                      <input
                        value={form.trigger_symbol}
                        onChange={(e) => setForm((f) => ({ ...f, trigger_symbol: e.target.value.toUpperCase() }))}
                        placeholder="e.g. SPY, AAPL, BTC-USD"
                        className="w-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-blue-500"
                      />
                    </div>
                  )}
                  {triggerConfig.needsValue && (
                    <div>
                      <label className="block text-xs text-[var(--text-tertiary)] mb-1">
                        {triggerConfig.type.includes("price") ? "Price ($)" :
                          triggerConfig.type === "vix_above" ? "VIX level" : "RSI value (0–100)"}
                      </label>
                      <input
                        type="number"
                        value={form.trigger_value}
                        onChange={(e) => setForm((f) => ({ ...f, trigger_value: e.target.value }))}
                        placeholder="e.g. 30"
                        className="w-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-blue-500"
                      />
                    </div>
                  )}
                  {triggerConfig.needsRegime && (
                    <div>
                      <label className="block text-xs text-[var(--text-tertiary)] mb-1">Regime</label>
                      <select
                        value={form.trigger_regime}
                        onChange={(e) => setForm((f) => ({ ...f, trigger_regime: e.target.value }))}
                        className="w-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-blue-500"
                      >
                        {REGIME_OPTIONS.map((r) => (
                          <option key={r} value={r}>{r}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              )}

              {/* Step 3: Choose action */}
              {step === 3 && (
                <div className="space-y-3">
                  <p className="text-sm font-semibold text-[var(--text-primary)]">THEN… (choose an action)</p>
                  <div className="space-y-2">
                    {ACTION_OPTIONS.map((opt) => (
                      <button
                        key={opt.type}
                        onClick={() => setForm((f) => ({ ...f, action_type: opt.type }))}
                        className={cn(
                          "w-full flex items-center gap-3 p-3 rounded-xl border text-left transition-colors",
                          form.action_type === opt.type
                            ? "border-emerald-500 bg-emerald-500/10 text-emerald-300"
                            : "border-[var(--border-subtle)] hover:border-[var(--border-emphasis)] text-[var(--text-secondary)]"
                        )}
                      >
                        <div className="flex-1">
                          <div className="text-sm font-semibold">{opt.label}</div>
                          <div className="text-xs text-[var(--text-tertiary)]">{opt.sub}</div>
                        </div>
                        {form.action_type === opt.type && <CheckCircle2 size={16} className="text-emerald-400 shrink-0" />}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Step 4: Action details */}
              {step === 4 && (
                <div className="space-y-4">
                  <p className="text-sm font-semibold text-[var(--text-primary)]">
                    Action details
                  </p>
                  {form.action_type === "notify" ? (
                    <p className="text-sm text-[var(--text-tertiary)]">
                      You'll receive a notification when this rule triggers. No trade will be executed.
                    </p>
                  ) : (
                    <>
                      <div>
                        <label className="block text-xs text-[var(--text-tertiary)] mb-1">Symbol</label>
                        <input
                          value={form.action_symbol}
                          onChange={(e) => setForm((f) => ({ ...f, action_symbol: e.target.value.toUpperCase() }))}
                          placeholder="e.g. GLD, BTC-USD, AAPL"
                          className="w-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-blue-500"
                        />
                      </div>
                      {form.action_type !== "reduce_position" && (
                        <>
                          <div>
                            <label className="block text-xs text-[var(--text-tertiary)] mb-1">Amount</label>
                            <input
                              type="number"
                              value={form.action_amount}
                              onChange={(e) => setForm((f) => ({ ...f, action_amount: e.target.value }))}
                              placeholder="e.g. 500"
                              className="w-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-blue-500"
                            />
                          </div>
                          <div>
                            <label className="block text-xs text-[var(--text-tertiary)] mb-1">Unit</label>
                            <select
                              value={form.action_unit}
                              onChange={(e) => setForm((f) => ({ ...f, action_unit: e.target.value as RuleForm["action_unit"] }))}
                              className="w-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-blue-500"
                            >
                              <option value="dollars">Dollars ($)</option>
                              <option value="shares">Shares</option>
                              <option value="pct_of_account">% of account</option>
                            </select>
                          </div>
                        </>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* Step 5: Name the rule */}
              {step === 5 && (
                <div className="space-y-4">
                  <p className="text-sm font-semibold text-[var(--text-primary)]">Name your rule</p>
                  <div>
                    <label className="block text-xs text-[var(--text-tertiary)] mb-1">Rule name (required)</label>
                    <input
                      value={form.name}
                      onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                      placeholder='e.g. "VIX hedge trigger"'
                      className="w-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-[var(--text-tertiary)] mb-1">Description (optional)</label>
                    <textarea
                      value={form.description}
                      onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                      placeholder="Notes about this rule..."
                      rows={2}
                      className="w-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-blue-500 resize-none"
                    />
                  </div>
                  {/* Summary */}
                  <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-2">
                    <div className="flex gap-2 text-xs">
                      <span className="text-[var(--text-tertiary)] w-10 shrink-0">IF</span>
                      <span className="text-blue-300 font-mono">
                        {triggerConfig?.label} {form.trigger_symbol && `${form.trigger_symbol} `}
                        {form.trigger_value && `${form.trigger_value}`}
                        {form.trigger_regime && form.trigger_regime}
                      </span>
                    </div>
                    <div className="flex gap-2 text-xs">
                      <span className="text-[var(--text-tertiary)] w-10 shrink-0">THEN</span>
                      <span className="text-emerald-300 font-mono">
                        {form.action_type === "notify" ? "Notify me" :
                          form.action_type === "reduce_position" ? `Reduce ${form.action_symbol} by 50%` :
                          `${form.action_type} ${form.action_amount} ${form.action_unit === "dollars" ? "$" : form.action_unit} ${form.action_symbol}`}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Footer navigation */}
            <div className="flex items-center justify-between px-6 py-4 border-t border-[var(--border-subtle)]">
              <button
                onClick={() => setStep((s) => Math.max(1, s - 1))}
                disabled={step === 1}
                className="flex items-center gap-1 text-sm text-[var(--text-tertiary)] hover:text-[var(--text-primary)] disabled:opacity-40 disabled:pointer-events-none"
              >
                <ChevronLeft size={16} />
                Back
              </button>
              {step < 5 ? (
                <button
                  onClick={() => setStep((s) => s + 1)}
                  disabled={!canAdvance()}
                  className="flex items-center gap-1 px-5 py-2 bg-blue-500 hover:bg-blue-400 disabled:opacity-40 disabled:pointer-events-none text-white text-sm font-semibold rounded-lg transition-colors"
                >
                  Next
                  <ChevronRight size={16} />
                </button>
              ) : (
                <button
                  onClick={handleSubmit}
                  disabled={!canAdvance() || createMut.isPending}
                  className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:pointer-events-none text-white text-sm font-semibold rounded-lg transition-colors"
                >
                  {createMut.isPending ? "Saving…" : "Create Rule"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rule card
// ---------------------------------------------------------------------------

function RuleCard({
  rule,
  onToggle,
  onDelete,
  onTest,
  testing,
}: {
  rule: UserRule;
  onToggle: (active: boolean) => void;
  onDelete: () => void;
  onTest: () => void;
  testing: boolean;
}) {
  return (
    <div className={cn(
      "border rounded-xl p-4 transition-colors",
      rule.is_active
        ? "border-[var(--border-emphasis)] bg-[var(--bg-elevated)]"
        : "border-[var(--border-subtle)] bg-[var(--bg-elevated)] opacity-60"
    )}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0 space-y-2">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm text-[var(--text-primary)] truncate">{rule.name}</span>
            {rule.is_active ? (
              <span className="text-[10px] bg-emerald-500/15 text-emerald-400 border border-emerald-500/20 px-1.5 py-0.5 rounded-full font-medium">Active</span>
            ) : (
              <span className="text-[10px] bg-zinc-500/15 text-zinc-400 border border-zinc-500/20 px-1.5 py-0.5 rounded-full font-medium">Inactive</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-[var(--text-tertiary)]">IF</span>
            <span className="font-mono text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded">{triggerLabel(rule)}</span>
            <span className="text-[var(--text-tertiary)]">THEN</span>
            <span className="font-mono text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">{actionLabel(rule)}</span>
          </div>
          <div className="flex items-center gap-3 text-[10px] text-[var(--text-tertiary)]">
            <span className="flex items-center gap-1">
              <CheckCircle2 size={10} />
              {rule.trigger_count} triggers
            </span>
            {rule.last_triggered && (
              <span className="flex items-center gap-1">
                <Clock size={10} />
                Last: {new Date(rule.last_triggered).toLocaleDateString()}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={onTest}
            disabled={testing}
            title="Test now"
            className="p-1.5 text-[var(--text-tertiary)] hover:text-blue-400 hover:bg-blue-500/10 rounded-lg transition-colors"
          >
            <Play size={14} />
          </button>
          <button
            onClick={() => onToggle(!rule.is_active)}
            title={rule.is_active ? "Disable" : "Enable"}
            className="p-1.5 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] rounded-lg transition-colors"
          >
            {rule.is_active
              ? <ToggleRight size={18} className="text-emerald-400" />
              : <ToggleLeft size={18} />}
          </button>
          <button
            onClick={onDelete}
            title="Delete"
            className="p-1.5 text-[var(--text-tertiary)] hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}

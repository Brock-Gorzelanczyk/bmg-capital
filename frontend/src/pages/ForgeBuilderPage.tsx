import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { BracketFrame, SectionLabel } from "@/components/design";
import SignalExplainButton from "@/components/explain/SignalExplainButton";
import { cn } from "@/lib/utils";
import { getCatalog, type ScoutCatalogEntry } from "@/api/scout";
import {
  getForgeBots,
  createForgeBot,
  updateForgeBotStatus,
  deleteForgeBot,
  getForgeSignals,
  type ForgeBot,
  type ForgeSignal,
} from "@/api/forge";

// ── Helpers ────────────────────────────────────────────────────────────────────

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function sideColor(side: string) {
  if (side === "buy" || side === "long" || side === "cover") return "text-emerald-400";
  if (side === "sell" || side === "short") return "text-red-400";
  return "text-zinc-400";
}

const STEP_LABELS = ["Name", "Strategies", "Watchlist", "Capital", "Risk & Mode", "Review"];

// ── Wizard ─────────────────────────────────────────────────────────────────────

interface WizardState {
  name: string;
  description: string;
  selectedStrategies: string[];
  tickerInput: string;
  watchlist: string[];
  capitalPct: number;
  stopLossPct: number;
  takeProfitPct: number;
  maxPosSizePct: number;
  schedule: "intraday" | "daily" | "weekly";
  mode: "shadow" | "sandbox";
}

const INIT_WIZARD: WizardState = {
  name: "",
  description: "",
  selectedStrategies: [],
  tickerInput: "",
  watchlist: [],
  capitalPct: 5,
  stopLossPct: 5,
  takeProfitPct: 15,
  maxPosSizePct: 10,
  schedule: "daily",
  mode: "shadow",
};

interface ForgeWizardProps {
  catalog: ScoutCatalogEntry[];
  onClose: () => void;
  onCreated: () => void;
}

function ForgeWizard({ catalog, onClose, onCreated }: ForgeWizardProps) {
  const qc = useQueryClient();
  const [step, setStep] = useState(1);
  const [state, setState] = useState<WizardState>(INIT_WIZARD);
  const [stratFilter, setStratFilter] = useState("");

  const update = useCallback((patch: Partial<WizardState>) => {
    setState((prev) => ({ ...prev, ...patch }));
  }, []);

  const forgeName = state.name.trim().startsWith("forge_")
    ? state.name.trim()
    : `forge_${state.name.trim()}`;

  const createMut = useMutation({
    mutationFn: () =>
      createForgeBot({
        name: forgeName,
        description: [
          state.description.trim(),
          `stop:${state.stopLossPct}% tp:${state.takeProfitPct}% maxpos:${state.maxPosSizePct}%`,
          `schedule:${state.schedule} mode:${state.mode}`,
        ].filter(Boolean).join(" | "),
        strategies: state.selectedStrategies,
        watchlist: state.watchlist,
        capital_pct: state.capitalPct,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["forge-bots"] });
      toast.success(`${forgeName} submitted for review!`);
      onCreated();
    },
    onError: () => toast.error("Failed to create bot"),
  });

  // Grouped catalog for step 2
  const grouped: Record<string, ScoutCatalogEntry[]> = {};
  for (const entry of catalog) {
    const cat = entry.category || "Other";
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(entry);
  }
  const filteredGroups: Record<string, ScoutCatalogEntry[]> = {};
  const q = stratFilter.toLowerCase();
  for (const [cat, entries] of Object.entries(grouped)) {
    const matches = entries.filter(
      (e) =>
        !q ||
        e.display_name.toLowerCase().includes(q) ||
        e.category.toLowerCase().includes(q)
    );
    if (matches.length) filteredGroups[cat] = matches;
  }

  const addTicker = () => {
    const t = state.tickerInput.trim().toUpperCase();
    if (!t) return;
    if (state.watchlist.includes(t)) {
      update({ tickerInput: "" });
      return;
    }
    update({ watchlist: [...state.watchlist, t], tickerInput: "" });
  };

  const canNext =
    (step === 1 && state.name.trim().length >= 2) ||
    (step === 2 && state.selectedStrategies.length >= 1) ||
    (step === 3 && state.watchlist.length >= 1) ||
    step === 4 ||
    step === 5 ||
    step === 6;

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
      <div className="bg-zinc-950 border border-zinc-800 rounded-2xl w-full max-w-xl shadow-2xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-3 border-b border-zinc-800 flex-shrink-0">
          <div>
            <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest mb-0.5">
              // THE FORGE
            </p>
            <p className="text-white font-bold text-lg">Build a Custom Bot</p>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-white text-xl transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Step progress */}
        <div className="px-6 pt-4 flex-shrink-0">
          <div className="flex items-center gap-1.5 mb-1">
            {STEP_LABELS.map((label, i) => (
              <div key={i} className="flex items-center gap-1.5 flex-1">
                <div
                  className={cn(
                    "h-1.5 flex-1 rounded-full transition-colors",
                    i < step ? "bg-orange-500" : "bg-zinc-800"
                  )}
                />
              </div>
            ))}
          </div>
          <p className="text-xs text-zinc-500">
            Step {step} of 5 — <span className="text-zinc-300">{STEP_LABELS[step - 1]}</span>
          </p>
        </div>

        {/* Step content */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {/* Step 1: Name */}
          {step === 1 && (
            <>
              <div>
                <label className="block text-xs font-semibold text-zinc-400 mb-1.5 uppercase tracking-wide">
                  Bot Name *
                </label>
                <input
                  autoFocus
                  value={state.name}
                  onChange={(e) => update({ name: e.target.value })}
                  placeholder="e.g. Crypto Trend Catcher"
                  maxLength={60}
                  className="w-full bg-zinc-900 border border-zinc-700 rounded-xl px-4 py-3 text-white text-sm placeholder-zinc-600 focus:outline-none focus:border-orange-500 transition-colors"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-zinc-400 mb-1.5 uppercase tracking-wide">
                  Description <span className="text-zinc-600 normal-case font-normal">(optional)</span>
                </label>
                <textarea
                  value={state.description}
                  onChange={(e) => update({ description: e.target.value })}
                  placeholder="What is this bot watching for?"
                  rows={3}
                  maxLength={280}
                  className="w-full bg-zinc-900 border border-zinc-700 rounded-xl px-4 py-3 text-white text-sm placeholder-zinc-600 focus:outline-none focus:border-orange-500 transition-colors resize-none"
                />
              </div>
            </>
          )}

          {/* Step 2: Strategies */}
          {step === 2 && (
            <>
              <div className="flex items-center justify-between">
                <p className="text-xs text-zinc-500">
                  Select one or more strategies to stack on your watchlist.
                </p>
                {state.selectedStrategies.length > 0 && (
                  <span className="text-xs font-semibold text-orange-400 bg-orange-500/10 border border-orange-500/20 px-2 py-0.5 rounded-full">
                    {state.selectedStrategies.length} selected
                  </span>
                )}
              </div>
              <input
                value={stratFilter}
                onChange={(e) => setStratFilter(e.target.value)}
                placeholder="Filter strategies…"
                className="w-full bg-zinc-900 border border-zinc-700 rounded-xl px-4 py-2.5 text-white text-sm placeholder-zinc-600 focus:outline-none focus:border-orange-500 transition-colors"
              />
              <div className="space-y-3">
                {Object.entries(filteredGroups).map(([cat, entries]) => (
                  <div key={cat}>
                    <p className="text-[10px] font-semibold text-zinc-600 uppercase tracking-widest mb-1.5">
                      {cat}
                    </p>
                    <div className="space-y-1">
                      {entries.map((entry) => {
                        const checked = state.selectedStrategies.includes(entry.strategy_id);
                        return (
                          <label
                            key={entry.strategy_id}
                            className={cn(
                              "flex items-start gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-colors",
                              checked
                                ? "bg-orange-500/10 border border-orange-500/30"
                                : "bg-zinc-900 border border-zinc-800 hover:border-zinc-700"
                            )}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  update({
                                    selectedStrategies: [
                                      ...state.selectedStrategies,
                                      entry.strategy_id,
                                    ],
                                  });
                                } else {
                                  update({
                                    selectedStrategies: state.selectedStrategies.filter(
                                      (s) => s !== entry.strategy_id
                                    ),
                                  });
                                }
                              }}
                              className="mt-0.5 accent-orange-500"
                            />
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-semibold text-white leading-tight">
                                {entry.display_name}
                              </p>
                              <p className="text-xs text-zinc-500 mt-0.5 leading-snug line-clamp-2">
                                {entry.description}
                              </p>
                            </div>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ))}
                {Object.keys(filteredGroups).length === 0 && (
                  <p className="text-sm text-zinc-600 py-4 text-center">No strategies match</p>
                )}
              </div>
            </>
          )}

          {/* Step 3: Watchlist */}
          {step === 3 && (
            <>
              <p className="text-xs text-zinc-500">
                Add tickers to scan. Your strategies will run against all of them.
              </p>
              <div className="flex gap-2">
                <input
                  value={state.tickerInput}
                  onChange={(e) => update({ tickerInput: e.target.value.toUpperCase() })}
                  onKeyDown={(e) => e.key === "Enter" && addTicker()}
                  placeholder="e.g. BTC/USD, NVDA, ETH/USD"
                  className="flex-1 bg-zinc-900 border border-zinc-700 rounded-xl px-4 py-2.5 text-white text-sm placeholder-zinc-600 focus:outline-none focus:border-orange-500 transition-colors"
                />
                <button
                  onClick={addTicker}
                  className="px-4 py-2.5 rounded-xl bg-orange-500/15 border border-orange-500/30 text-orange-400 text-sm font-semibold hover:bg-orange-500/25 transition-colors whitespace-nowrap"
                >
                  Add
                </button>
              </div>
              {state.watchlist.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {state.watchlist.map((ticker) => (
                    <span
                      key={ticker}
                      className="flex items-center gap-1.5 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm font-mono text-white"
                    >
                      {ticker}
                      <button
                        onClick={() =>
                          update({ watchlist: state.watchlist.filter((t) => t !== ticker) })
                        }
                        className="text-zinc-500 hover:text-red-400 transition-colors text-xs leading-none"
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-zinc-600 py-2">No tickers added yet.</p>
              )}
            </>
          )}

          {/* Step 4: Capital */}
          {step === 4 && (
            <>
              <p className="text-xs text-zinc-500">
                What percentage of your account should this bot represent?
              </p>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-zinc-400 text-sm">Capital allocation</span>
                  <span className="text-2xl font-bold text-orange-400">{state.capitalPct}%</span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={50}
                  step={1}
                  value={state.capitalPct}
                  onChange={(e) => update({ capitalPct: Number(e.target.value) })}
                  className="w-full accent-orange-500"
                />
                <div className="flex justify-between text-xs text-zinc-600">
                  <span>1%</span>
                  <span>25%</span>
                  <span>50%</span>
                </div>
                <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 space-y-1.5">
                  <p className="text-xs text-zinc-500">Scanning</p>
                  <p className="text-sm text-white">
                    <span className="font-semibold text-orange-400">{state.watchlist.length}</span>{" "}
                    tickers ×{" "}
                    <span className="font-semibold text-orange-400">
                      {state.selectedStrategies.length}
                    </span>{" "}
                    strategies ={" "}
                    <span className="font-semibold text-white">
                      {state.watchlist.length * state.selectedStrategies.length}
                    </span>{" "}
                    combinations per scan
                  </p>
                </div>
              </div>
            </>
          )}

          {/* Step 5: Risk & Mode */}
          {step === 5 && (
            <div className="space-y-5">
              <p className="text-xs text-zinc-500">Set risk parameters and operating mode for this bot.</p>

              {/* Max position size */}
              <div>
                <label className="block text-xs font-semibold text-zinc-400 mb-2 uppercase tracking-wide">Max Position Size</label>
                <div className="flex gap-2">
                  {[5, 10, 20].map((v) => (
                    <button key={v} onClick={() => update({ maxPosSizePct: v })}
                      className={cn("flex-1 py-2 rounded-lg text-sm font-semibold border transition-colors",
                        state.maxPosSizePct === v ? "bg-orange-500/15 border-orange-500/40 text-orange-400" : "bg-zinc-900 border-zinc-700 text-zinc-400 hover:border-zinc-600"
                      )}>
                      {v}%
                    </button>
                  ))}
                </div>
              </div>

              {/* Stop loss */}
              <div>
                <div className="flex justify-between mb-1.5">
                  <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wide">Stop Loss</label>
                  <span className="text-sm font-bold text-red-400">{state.stopLossPct}%</span>
                </div>
                <input type="range" min={1} max={20} step={1} value={state.stopLossPct}
                  onChange={(e) => update({ stopLossPct: Number(e.target.value) })}
                  className="w-full accent-red-500" />
                <div className="flex justify-between text-xs text-zinc-600 mt-0.5"><span>1%</span><span>20%</span></div>
              </div>

              {/* Take profit */}
              <div>
                <div className="flex justify-between mb-1.5">
                  <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wide">Take Profit</label>
                  <span className="text-sm font-bold text-emerald-400">{state.takeProfitPct}%</span>
                </div>
                <input type="range" min={5} max={50} step={5} value={state.takeProfitPct}
                  onChange={(e) => update({ takeProfitPct: Number(e.target.value) })}
                  className="w-full accent-emerald-500" />
                <div className="flex justify-between text-xs text-zinc-600 mt-0.5"><span>5%</span><span>50%</span></div>
              </div>

              {/* Schedule */}
              <div>
                <label className="block text-xs font-semibold text-zinc-400 mb-2 uppercase tracking-wide">Scan Schedule</label>
                <div className="flex gap-2">
                  {(["intraday", "daily", "weekly"] as const).map((v) => (
                    <button key={v} onClick={() => update({ schedule: v })}
                      className={cn("flex-1 py-2 rounded-lg text-xs font-semibold border capitalize transition-colors",
                        state.schedule === v ? "bg-orange-500/15 border-orange-500/40 text-orange-400" : "bg-zinc-900 border-zinc-700 text-zinc-400 hover:border-zinc-600"
                      )}>
                      {v === "intraday" ? "Intraday (5m)" : v === "daily" ? "Daily (EOD)" : "Weekly"}
                    </button>
                  ))}
                </div>
              </div>

              {/* Mode */}
              <div>
                <label className="block text-xs font-semibold text-zinc-400 mb-2 uppercase tracking-wide">Mode</label>
                <div className="flex gap-2">
                  <button onClick={() => update({ mode: "shadow" })}
                    className={cn("flex-1 py-3 rounded-lg text-sm font-semibold border transition-colors",
                      state.mode === "shadow" ? "bg-violet-500/15 border-violet-500/40 text-violet-400" : "bg-zinc-900 border-zinc-700 text-zinc-400"
                    )}>
                    Shadow Paper
                    <p className="text-[10px] font-normal text-zinc-600 mt-0.5">signals only · no fills</p>
                  </button>
                  <button onClick={() => update({ mode: "sandbox" })}
                    className={cn("flex-1 py-3 rounded-lg text-sm font-semibold border transition-colors",
                      state.mode === "sandbox" ? "bg-orange-500/15 border-orange-500/40 text-orange-400" : "bg-zinc-900 border-zinc-700 text-zinc-400"
                    )}>
                    Sandbox Trade
                    <p className="text-[10px] font-normal text-zinc-600 mt-0.5">simulated fills · paper capital</p>
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Step 6: Review */}
          {step === 6 && (
            <div className="space-y-4">
              {/* forge_ name badge */}
              <div className="bg-orange-500/10 border border-orange-500/30 rounded-xl px-4 py-3">
                <p className="text-[10px] text-zinc-500 mb-0.5 uppercase tracking-widest">Bot ID (auto-prefixed)</p>
                <p className="text-orange-400 font-mono font-semibold text-sm">{forgeName}</p>
                <p className="text-[10px] text-zinc-600 mt-0.5">forge_ prefix ensures this bot never conflicts with curated bots</p>
              </div>

              <div className="bg-zinc-900 border border-zinc-800 rounded-xl divide-y divide-zinc-800">
                <div className="px-4 py-3">
                  <p className="text-xs text-zinc-500 mb-0.5">Bot Name</p>
                  <p className="text-white font-semibold">{state.name}</p>
                  {state.description && <p className="text-zinc-400 text-xs mt-0.5">{state.description}</p>}
                </div>
                <div className="px-4 py-3">
                  <p className="text-xs text-zinc-500 mb-1.5">Strategies ({state.selectedStrategies.length})</p>
                  <div className="flex flex-wrap gap-1.5">
                    {state.selectedStrategies.map((sid) => {
                      const entry = catalog.find((c) => c.strategy_id === sid);
                      return (
                        <span key={sid} className="text-xs bg-orange-500/10 border border-orange-500/20 text-orange-300 px-2 py-0.5 rounded-md">
                          {entry?.display_name || sid}
                        </span>
                      );
                    })}
                  </div>
                </div>
                <div className="px-4 py-3">
                  <p className="text-xs text-zinc-500 mb-1.5">Watchlist ({state.watchlist.length} tickers)</p>
                  <div className="flex flex-wrap gap-1.5">
                    {state.watchlist.map((t) => (
                      <span key={t} className="text-xs font-mono bg-zinc-800 border border-zinc-700 text-white px-2 py-0.5 rounded-md">{t}</span>
                    ))}
                  </div>
                </div>
                <div className="grid grid-cols-2 divide-x divide-zinc-800">
                  <div className="px-4 py-3">
                    <p className="text-xs text-zinc-500 mb-0.5">Capital · Stop · TP</p>
                    <p className="text-white font-semibold text-sm">{state.capitalPct}% · {state.stopLossPct}%SL · {state.takeProfitPct}%TP</p>
                  </div>
                  <div className="px-4 py-3">
                    <p className="text-xs text-zinc-500 mb-0.5">Schedule · Mode</p>
                    <p className="text-white font-semibold text-sm capitalize">{state.schedule} · {state.mode}</p>
                  </div>
                </div>
              </div>

              {/* Guardrail: Brock approval required */}
              <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3">
                <p className="text-[10px] font-semibold text-amber-400 uppercase tracking-widest mb-1">⚠ Pending Review</p>
                <p className="text-xs text-zinc-400">
                  This bot starts in <strong className="text-amber-400">PENDING_REVIEW</strong> state.
                  It will scan and fire signals but Brock must approve before any capital is allocated.
                  Bots must demonstrate Sharpe &gt; 0.3 before shadow paper allocation is enabled.
                </p>
              </div>

              <p className="text-xs text-zinc-600">
                The scanner runs every 5 minutes and fires signals to your #my-signals Discord channel.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-zinc-800 flex-shrink-0">
          <button
            onClick={() => (step === 1 ? onClose() : setStep((s) => Math.max(1, s - 1) as typeof step))}
            className="text-sm text-zinc-400 hover:text-white transition-colors"
          >
            {step === 1 ? "Cancel" : "← Back"}
          </button>
          {step < 6 ? (
            <button
              disabled={!canNext}
              onClick={() => setStep((s) => Math.min(6, s + 1) as typeof step)}
              className="px-6 py-2.5 rounded-xl bg-orange-500 text-black text-sm font-bold hover:bg-orange-400 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Next →
            </button>
          ) : (
            <button
              disabled={createMut.isPending}
              onClick={() => createMut.mutate()}
              className="px-6 py-2.5 rounded-xl bg-orange-500 text-black text-sm font-bold hover:bg-orange-400 disabled:opacity-50 transition-colors"
            >
              {createMut.isPending ? "Launching…" : "Launch Bot"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Bot Card ───────────────────────────────────────────────────────────────────

interface BotCardProps {
  bot: ForgeBot;
  onDelete: (id: number) => void;
  onToggle: (id: number, status: "active" | "paused") => void;
}

function ForgeBotCard({ bot, onDelete, onToggle }: BotCardProps) {
  const isActive = bot.status === "active";
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span
              className={cn(
                "inline-block w-1.5 h-1.5 rounded-full flex-shrink-0",
                isActive ? "bg-emerald-400" : "bg-zinc-500"
              )}
            />
            <p className="text-white font-semibold text-sm truncate">{bot.name}</p>
          </div>
          {bot.description && (
            <p className="text-xs text-zinc-500 line-clamp-1">{bot.description}</p>
          )}
        </div>
        <span
          className={cn(
            "text-[10px] font-semibold px-2 py-0.5 rounded-full border flex-shrink-0",
            isActive
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
              : "bg-zinc-800 border-zinc-700 text-zinc-400"
          )}
        >
          {bot.status}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="bg-zinc-800/60 rounded-lg px-2 py-1.5">
          <p className="text-white font-bold text-sm">{bot.strategies.length}</p>
          <p className="text-zinc-500 text-[10px]">strategies</p>
        </div>
        <div className="bg-zinc-800/60 rounded-lg px-2 py-1.5">
          <p className="text-white font-bold text-sm">{bot.watchlist.length}</p>
          <p className="text-zinc-500 text-[10px]">tickers</p>
        </div>
        <div className="bg-zinc-800/60 rounded-lg px-2 py-1.5">
          <p className="text-white font-bold text-sm">{bot.signal_count}</p>
          <p className="text-zinc-500 text-[10px]">signals</p>
        </div>
      </div>

      <div className="flex items-center justify-between text-xs text-zinc-600">
        <span>Last signal: {relativeTime(bot.last_fired_at)}</span>
        <span>{bot.capital_pct}% capital</span>
      </div>

      <div className="flex gap-2 pt-1">
        <button
          onClick={() => onToggle(bot.id, isActive ? "paused" : "active")}
          className="flex-1 text-xs font-semibold py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-300 hover:border-zinc-600 transition-colors"
        >
          {isActive ? "Pause" : "Resume"}
        </button>
        <button
          onClick={() => {
            if (confirm(`Delete "${bot.name}"? This cannot be undone.`)) {
              onDelete(bot.id);
            }
          }}
          className="flex-1 text-xs font-semibold py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 text-red-400 hover:bg-red-500/10 hover:border-red-500/30 transition-colors"
        >
          Delete
        </button>
      </div>
    </div>
  );
}

// ── Signal Row ─────────────────────────────────────────────────────────────────

function SignalRow({ sig }: { sig: ForgeSignal }) {
  return (
    <div className="flex items-center gap-3 py-2.5 px-4 hover:bg-zinc-800/40 transition-colors">
      <span className={cn("text-xs font-bold w-10 flex-shrink-0 uppercase", sideColor(sig.side))}>
        {sig.side}
      </span>
      <span className="text-xs font-mono text-white w-20 flex-shrink-0">{sig.ticker}</span>
      <span className="text-xs text-zinc-400 flex-1 truncate">{sig.display_name}</span>
      <span className="text-xs text-zinc-500 flex-shrink-0">{sig.bot_name}</span>
      <span className="text-xs font-semibold text-white w-10 text-right flex-shrink-0">
        {Math.round(sig.confidence * 100)}%
      </span>
      <span className="text-xs text-zinc-600 w-14 text-right flex-shrink-0">
        {relativeTime(sig.created_at)}
      </span>
      <SignalExplainButton signalId={sig.id} source="forge" />
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function ForgeBuilderPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [showWizard, setShowWizard] = useState(false);

  const { data: botsData, isLoading: botsLoading } = useQuery({
    queryKey: ["forge-bots"],
    queryFn: getForgeBots,
    retry: 0,
    staleTime: 30_000,
  });

  const { data: signalsData } = useQuery({
    queryKey: ["forge-signals"],
    queryFn: getForgeSignals,
    retry: 0,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const { data: catalogData, isLoading: catalogLoading } = useQuery({
    queryKey: ["scout-catalog"],
    queryFn: getCatalog,
    retry: 0,
    staleTime: 300_000,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, status }: { id: number; status: "active" | "paused" }) =>
      updateForgeBotStatus(id, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["forge-bots"] }),
    onError: () => toast.error("Failed to update bot"),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteForgeBot(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["forge-bots"] });
      toast.success("Bot deleted");
    },
    onError: () => toast.error("Failed to delete bot"),
  });

  const bots = botsData?.bots ?? [];
  const signals = signalsData?.signals ?? [];
  const catalog = catalogData?.strategies ?? [];
  const isEnabled = !botsLoading && botsData !== undefined;

  return (
    <>
      {showWizard && catalog.length > 0 && (
        <ForgeWizard
          catalog={catalog}
          onClose={() => setShowWizard(false)}
          onCreated={() => setShowWizard(false)}
        />
      )}

      <div className="max-w-5xl mx-auto px-4 py-6 pb-24 md:pb-6 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <button
              onClick={() => navigate("/strategy")}
              className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors mb-2 flex items-center gap-1"
            >
              ← Strategy Lab
            </button>
            <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest mb-0.5">
              // THE FORGE
            </p>
            <h1 className="text-2xl font-bold text-white">Custom Bot Builder</h1>
            <p className="text-zinc-400 text-sm mt-1">
              Combine strategies, define your watchlist, allocate capital — your bot, your rules.
            </p>
          </div>
          <button
            onClick={() => {
              if (!isEnabled) return;
              if (catalog.length === 0 && !catalogLoading) {
                toast.error("Strategy catalog unavailable — is ENABLE_STRATEGY_FORGE set?");
                return;
              }
              setShowWizard(true);
            }}
            className="px-5 py-2.5 rounded-xl bg-orange-500 text-black text-sm font-bold hover:bg-orange-400 transition-colors shadow-lg shadow-orange-500/20 disabled:opacity-50"
          >
            + New Bot
          </button>
        </div>

        {/* Feature-not-enabled notice */}
        {!botsLoading && botsData === undefined && (
          <div className="bg-orange-500/10 border border-orange-500/30 rounded-2xl px-5 py-6 text-center">
            <p className="text-orange-300 font-semibold mb-1">The Forge is not enabled</p>
            <p className="text-zinc-400 text-sm">
              Set <code className="bg-zinc-800 px-1 py-0.5 rounded text-xs">ENABLE_STRATEGY_FORGE=true</code> in
              Railway environment variables to activate.
            </p>
          </div>
        )}

        {/* Loading */}
        {botsLoading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-44 rounded-2xl bg-zinc-900 border border-zinc-800 animate-pulse" />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!botsLoading && isEnabled && bots.length === 0 && (
          <BracketFrame className="py-16 text-center">
            <p className="text-zinc-400 font-semibold mb-2">No forge bots yet</p>
            <p className="text-zinc-600 text-sm mb-6">
              Build your first custom bot — stack strategies, watch any tickers, fire personal signals.
            </p>
            <button
              onClick={() => catalog.length > 0 && setShowWizard(true)}
              className="px-6 py-3 rounded-xl bg-orange-500 text-black font-bold text-sm hover:bg-orange-400 transition-colors"
            >
              Build Your First Bot
            </button>
          </BracketFrame>
        )}

        {/* Bot grid */}
        {!botsLoading && bots.length > 0 && (
          <>
            <div>
              <SectionLabel className="mb-3">Your Forge Bots ({bots.length})</SectionLabel>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {bots.map((bot) => (
                  <ForgeBotCard
                    key={bot.id}
                    bot={bot}
                    onDelete={(id) => deleteMut.mutate(id)}
                    onToggle={(id, status) => toggleMut.mutate({ id, status })}
                  />
                ))}
              </div>
            </div>
          </>
        )}

        {/* Signals feed */}
        {signals.length > 0 && (
          <div>
            <SectionLabel className="mb-3">Recent Forge Signals</SectionLabel>
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
              <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800">
                <span className="text-[10px] font-semibold text-zinc-600 uppercase w-10">Side</span>
                <span className="text-[10px] font-semibold text-zinc-600 uppercase w-20">Ticker</span>
                <span className="text-[10px] font-semibold text-zinc-600 uppercase flex-1">Strategy</span>
                <span className="text-[10px] font-semibold text-zinc-600 uppercase">Bot</span>
                <span className="text-[10px] font-semibold text-zinc-600 uppercase w-10 text-right">Conf</span>
                <span className="text-[10px] font-semibold text-zinc-600 uppercase w-14 text-right">When</span>
              </div>
              {signals.slice(0, 20).map((sig) => (
                <SignalRow key={sig.id} sig={sig} />
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  );
}

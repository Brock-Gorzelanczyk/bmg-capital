import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ChevronLeft, ChevronRight, X, Plus, Check, Search,
  AlertTriangle, Zap, TrendingUp, Clock, BarChart2,
  Rocket, Info, Settings,
} from "lucide-react";
import client from "@/api/client";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

interface BotTemplate {
  id: number;
  name: string;
  emoji: string;
  tagline: string;
  strategies: string[];
  default_config: {
    capital_dollars: number;
    risk_profile: string;
    schedule: string;
  };
}

interface LibraryStrategy {
  id: number;
  module_name: string;
  display_name: string;
  tagline: string;
  category: string;
  asset_class: string;
  time_horizon: string;
  difficulty: string;
  risk_profile: string;
  published_sharpe: number | null;
  win_rate_pub: number | null;
  description_md: string | null;
  mechanics_md: string | null;
  suggested_bot: string | null;
}

type RiskProfile = "conservative" | "standard" | "aggressive";
type Schedule = "auto" | "daily_4pm" | "every_4h" | "monthly";
type Step = "templates" | "basket" | "configure" | "confirm" | "deploying";

interface Draft {
  templateId: number | null;
  strategies: LibraryStrategy[];
  name: string;
  capitalDollars: number;
  riskProfile: RiskProfile;
  schedule: Schedule;
}

// ─── API helpers ──────────────────────────────────────────────────────────────

const api = {
  getTemplates: (): Promise<{ templates: BotTemplate[] }> =>
    client.get("/custom-bot/templates").then((r) => r.data).catch(() => ({ templates: [] })),

  getLibrary: (search: string): Promise<{ strategies: LibraryStrategy[] }> =>
    client.get(`/strategy-library?search=${encodeURIComponent(search)}&sort=sharpe`)
      .then((r) => r.data).catch(() => ({ strategies: [] })),

  saveDraft: (payload: object): Promise<{ draft_id: number }> =>
    client.post("/custom-bot/draft", payload).then((r) => r.data),

  validate: (payload: object): Promise<{ valid: boolean; errors: string[]; warnings: string[] }> =>
    client.post("/custom-bot/validate", payload).then((r) => r.data).catch(() => ({ valid: false, errors: ["Validation failed"], warnings: [] })),

  deploy: (payload: object): Promise<{ bot_id: number; bot_name: string; allocation_id: number; first_run_ts: string }> =>
    client.post("/custom-bot/deploy", payload).then((r) => r.data),
};

// ─── Constants ────────────────────────────────────────────────────────────────

const RISK_DESCRIPTIONS: Record<RiskProfile, string> = {
  conservative: "Smaller position sizes, wider stops, lower drawdown tolerance",
  standard: "Balanced sizing — good for most portfolios",
  aggressive: "Larger positions, tighter stops, max return focus",
};

const SCHEDULE_LABELS: Record<Schedule, string> = {
  auto: "Auto (recommended)",
  daily_4pm: "Daily at 4:05 PM ET",
  every_4h: "Every 4 hours",
  monthly: "Monthly (first Tuesday)",
};

const DIFFICULTY_COLOR: Record<string, string> = {
  beginner: "bg-lime-500/15 text-lime-400 border-lime-500/30",
  intermediate: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  advanced: "bg-red-500/15 text-red-400 border-red-500/30",
};

// ─── Log scale slider ─────────────────────────────────────────────────────────

function toLog(value: number): number {
  const minLog = Math.log(1000);
  const maxLog = Math.log(100000);
  return ((Math.log(value) - minLog) / (maxLog - minLog)) * 100;
}

function fromLog(pct: number): number {
  const minLog = Math.log(1000);
  const maxLog = Math.log(100000);
  return Math.round(Math.exp(minLog + (pct / 100) * (maxLog - minLog)) / 1000) * 1000;
}

function formatDollars(n: number): string {
  if (n >= 1000) return `$${(n / 1000).toFixed(0)}k`;
  return `$${n}`;
}

// ─── Auto-schedule detection ──────────────────────────────────────────────────

function detectSchedule(strategies: LibraryStrategy[]): Schedule {
  const names = strategies.map((s) => s.module_name);
  const hasDay = names.some((n) => n.includes("intraday") || n.includes("orb") || n.includes("gap_and_go") || n.includes("vwap"));
  const hasCrypto = names.some((n) => n.startsWith("crypto") || n.includes("btc") || n.includes("dca"));
  if (hasDay) return "daily_4pm";
  if (hasCrypto) return "every_4h";
  return "daily_4pm";
}

function detectAssetClasses(strategies: LibraryStrategy[]): string[] {
  const classes = new Set(strategies.map((s) => s.asset_class));
  return Array.from(classes);
}

// ─── Expected behavior text ───────────────────────────────────────────────────

function buildExpectedBehavior(draft: Draft): string {
  const n = draft.strategies.length;
  if (n === 0) return "";
  const avgWinRate = draft.strategies
    .filter((s) => s.win_rate_pub != null)
    .reduce((acc, s) => acc + (s.win_rate_pub ?? 0), 0) /
    Math.max(1, draft.strategies.filter((s) => s.win_rate_pub != null).length);
  const winPct = Math.round(avgWinRate * 100);
  const maxLoss = ((draft.capitalDollars * 0.1 * 0.05) / 100).toFixed(0);

  const scheduleDesc =
    draft.schedule === "auto" || draft.schedule === "daily_4pm"
      ? "once per trading day around 4:05 PM ET"
      : draft.schedule === "every_4h"
      ? "every 4 hours around the clock"
      : "once per month on the first Tuesday";

  return `Your bot will scan ${n} strateg${n === 1 ? "y" : "ies"} ${scheduleDesc}. ` +
    `When signals agree, it opens a paper position — no real money moves. ` +
    (winPct > 0 ? `The strategies in this basket have historically won roughly ${winPct}% of trades. ` : "") +
    `With ${formatDollars(draft.capitalDollars)} allocated and ${draft.riskProfile} sizing, ` +
    `the largest single-trade loss is capped near $${maxLoss}. ` +
    `Every decision is logged in Activity with plain-English reasoning.`;
}

// ─── Step indicator ───────────────────────────────────────────────────────────

const STEPS: { key: Step; label: string }[] = [
  { key: "templates", label: "Template" },
  { key: "basket", label: "Strategies" },
  { key: "configure", label: "Configure" },
  { key: "confirm", label: "Review" },
];

function StepBar({ current }: { current: Step }) {
  const idx = STEPS.findIndex((s) => s.key === current);
  return (
    <div className="flex items-center gap-0 mb-8">
      {STEPS.map((s, i) => (
        <div key={s.key} className="flex items-center">
          <div className={cn(
            "flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold border transition-colors",
            i < idx
              ? "bg-lime-500 border-lime-500 text-black"
              : i === idx
              ? "bg-lime-500/20 border-lime-500 text-lime-400"
              : "bg-zinc-900 border-zinc-700 text-zinc-600"
          )}>
            {i < idx ? <Check className="w-3 h-3" /> : i + 1}
          </div>
          <span className={cn(
            "text-xs ml-1.5 font-medium",
            i === idx ? "text-white" : "text-zinc-600"
          )}>
            {s.label}
          </span>
          {i < STEPS.length - 1 && (
            <div className={cn(
              "w-8 h-px mx-2",
              i < idx ? "bg-lime-500" : "bg-zinc-800"
            )} />
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Step 1: Template picker ──────────────────────────────────────────────────

const TEMPLATE_STRATEGY_COUNTS: Record<string, string> = {
  income: "5 strategies",
  growth: "6 strategies",
  safety: "4 strategies",
  day_trader: "7 strategies",
  crypto_pro: "9 strategies",
  build_from_scratch: "Start fresh",
};

const TEMPLATE_BEST_FOR: Record<string, string> = {
  income: "Steady cash flow from options premium",
  growth: "Long-term capital appreciation in bull markets",
  safety: "Capital preservation + slow steady growth",
  day_trader: "Active traders, high-frequency signals",
  crypto_pro: "Crypto exposure with BTC/ETH/SOL rotation",
  build_from_scratch: "Pick exactly what you want",
};

function TemplateStep({
  onSelect,
}: {
  onSelect: (template: BotTemplate | null) => void;
}) {
  const { data } = useQuery({
    queryKey: ["bot-templates"],
    queryFn: api.getTemplates,
    staleTime: 300_000,
  });

  const templates = Array.isArray(data?.templates) ? data.templates : [];

  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-1">Pick a template</h2>
      <p className="text-sm text-zinc-500 mb-6">
        Templates pre-fill your strategy basket. You can add or remove strategies in the next step.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {templates.length === 0
          ? [0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-44 bg-zinc-900 border border-zinc-800 rounded-2xl animate-pulse" />
            ))
          : templates.map((t) => (
              <button
                key={t.id}
                onClick={() => onSelect(t.name === "build_from_scratch" ? null : t)}
                className="group text-left bg-zinc-900 border border-zinc-800 rounded-2xl p-5 hover:border-lime-500/40 hover:bg-zinc-800/60 transition-all space-y-3 cursor-pointer"
              >
                <div className="text-3xl">{t.emoji}</div>
                <div>
                  <h3 className="text-sm font-bold text-white group-hover:text-lime-400 transition-colors capitalize">
                    {t.name === "build_from_scratch" ? "Build From Scratch" : t.name.replace(/_/g, " ")}
                  </h3>
                  <p className="text-xs text-zinc-500 mt-0.5 leading-relaxed">{t.tagline}</p>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-zinc-600">
                    {TEMPLATE_STRATEGY_COUNTS[t.name] ?? `${t.strategies.length} strategies`}
                  </span>
                  <span className="text-[10px] text-zinc-600 text-right max-w-[120px]">
                    {TEMPLATE_BEST_FOR[t.name]}
                  </span>
                </div>
              </button>
            ))}
      </div>
    </div>
  );
}

// ─── Strategy row card ────────────────────────────────────────────────────────

function StrategyRow({
  strategy,
  onRemove,
  removable,
}: {
  strategy: LibraryStrategy;
  onRemove: () => void;
  removable: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const HorizonIcon =
    strategy.time_horizon === "intraday" ? Zap
      : strategy.time_horizon === "swing" ? BarChart2
      : strategy.time_horizon === "position" ? TrendingUp
      : Clock;

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-zinc-800/40 transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-white truncate">{strategy.display_name}</span>
            <span className={cn(
              "text-[10px] font-semibold px-1.5 py-0.5 rounded-full border flex-shrink-0",
              DIFFICULTY_COLOR[strategy.difficulty] ?? "bg-zinc-800 text-zinc-400 border-zinc-700"
            )}>
              {strategy.difficulty}
            </span>
          </div>
          <p className="text-xs text-zinc-500 truncate mt-0.5">{strategy.tagline}</p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <HorizonIcon className="w-3.5 h-3.5 text-zinc-600" />
          {removable && (
            <button
              onClick={(e) => { e.stopPropagation(); onRemove(); }}
              className="p-1 rounded-lg text-zinc-600 hover:text-red-400 hover:bg-red-400/10 transition-colors"
              title="Remove"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
      {expanded && (
        <div className="px-4 pb-4 border-t border-zinc-800 pt-3 space-y-2">
          {strategy.description_md && (
            <p className="text-xs text-zinc-400 leading-relaxed">{strategy.description_md}</p>
          )}
          {strategy.mechanics_md && (
            <p className="text-xs text-zinc-500 leading-relaxed">{strategy.mechanics_md}</p>
          )}
          <div className="flex gap-4 pt-1">
            {strategy.published_sharpe != null && (
              <div>
                <p className="text-[9px] text-zinc-600 uppercase tracking-wide">Sharpe</p>
                <p className="text-xs font-bold text-lime-400">{strategy.published_sharpe.toFixed(2)}</p>
              </div>
            )}
            {strategy.win_rate_pub != null && (
              <div>
                <p className="text-[9px] text-zinc-600 uppercase tracking-wide">Win Rate</p>
                <p className="text-xs font-bold text-zinc-300">{(strategy.win_rate_pub * 100).toFixed(0)}%</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Library side panel ───────────────────────────────────────────────────────

function LibraryPanel({
  basket,
  onAdd,
  onClose,
}: {
  basket: LibraryStrategy[];
  onAdd: (s: LibraryStrategy) => void;
  onClose: () => void;
}) {
  const [search, setSearch] = useState("");

  const { data } = useQuery({
    queryKey: ["strategy-library-panel", search],
    queryFn: () => api.getLibrary(search),
    staleTime: 60_000,
  });

  const strategies = Array.isArray(data?.strategies) ? data.strategies : [];
  const basketIds = new Set(basket.map((s) => s.module_name));

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="w-full max-w-sm bg-zinc-950 border-l border-zinc-800 flex flex-col">
        <div className="flex items-center justify-between px-4 py-4 border-b border-zinc-800">
          <h3 className="text-sm font-bold text-white">Add Strategy</h3>
          <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-4 py-3 border-b border-zinc-800">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-600" />
            <input
              autoFocus
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search strategies…"
              className="w-full bg-zinc-900 border border-zinc-800 rounded-lg pl-8 pr-3 py-2 text-xs text-white placeholder-zinc-600 focus:outline-none focus:border-zinc-600"
            />
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
          {strategies.map((s) => {
            const inBasket = basketIds.has(s.module_name);
            return (
              <div
                key={s.id}
                className={cn(
                  "flex items-start gap-3 p-3 rounded-xl border transition-colors",
                  inBasket
                    ? "border-lime-500/30 bg-lime-500/5"
                    : "border-zinc-800 bg-zinc-900 hover:border-zinc-700 cursor-pointer"
                )}
                onClick={() => !inBasket && onAdd(s)}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold text-white truncate">{s.display_name}</p>
                  <p className="text-[10px] text-zinc-500 truncate mt-0.5">{s.tagline}</p>
                  <p className="text-[10px] text-zinc-600 mt-0.5 capitalize">{s.category} · {s.asset_class}</p>
                </div>
                <div className="flex-shrink-0 mt-0.5">
                  {inBasket ? (
                    <Check className="w-3.5 h-3.5 text-lime-400" />
                  ) : (
                    <Plus className="w-3.5 h-3.5 text-zinc-500" />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ─── Step 2: Strategy basket ──────────────────────────────────────────────────

function BasketStep({
  draft,
  onUpdate,
  onBack,
  onNext,
}: {
  draft: Draft;
  onUpdate: (strategies: LibraryStrategy[]) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const [panelOpen, setPanelOpen] = useState(false);
  const strategies = draft.strategies;

  const assetClasses = detectAssetClasses(strategies);
  const mixedAssets = assetClasses.length > 1;
  const categoryCount: Record<string, number> = {};
  strategies.forEach((s) => { categoryCount[s.category] = (categoryCount[s.category] ?? 0) + 1; });
  const concentratedCategory = Object.entries(categoryCount).find(([, v]) => v >= 4)?.[0];

  const canContinue = strategies.length >= 1;
  const atCap = strategies.length >= 10;

  function removeStrategy(idx: number) {
    onUpdate(strategies.filter((_, i) => i !== idx));
  }

  function addStrategy(s: LibraryStrategy) {
    if (atCap) { toast.warning("Max 10 strategies per bot"); return; }
    if (strategies.find((x) => x.module_name === s.module_name)) return;
    onUpdate([...strategies, s]);
  }

  return (
    <div>
      {panelOpen && (
        <LibraryPanel basket={strategies} onAdd={addStrategy} onClose={() => setPanelOpen(false)} />
      )}

      <div className="flex items-center justify-between mb-1">
        <h2 className="text-xl font-bold text-white">Your strategy basket</h2>
        <span className={cn(
          "text-xs font-semibold px-2 py-0.5 rounded-full border",
          atCap ? "bg-red-500/15 border-red-500/30 text-red-400" : "bg-zinc-800 border-zinc-700 text-zinc-400"
        )}>
          {strategies.length} / 10
        </span>
      </div>
      <p className="text-sm text-zinc-500 mb-5">
        Click any row to read what it does. Click the X to remove it.
      </p>

      {/* Warnings */}
      {mixedAssets && (
        <div className="flex items-start gap-2 bg-yellow-500/10 border border-yellow-500/20 rounded-xl px-4 py-3 mb-4">
          <AlertTriangle className="w-4 h-4 text-yellow-400 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-xs font-semibold text-yellow-400">Mixed asset classes detected</p>
            <p className="text-xs text-zinc-500 mt-0.5">
              This basket includes {assetClasses.join(" + ")} strategies. Consider creating 2 separate bots — one per asset class — for cleaner risk accounting.
            </p>
          </div>
        </div>
      )}
      {concentratedCategory && (
        <div className="flex items-start gap-2 bg-orange-500/10 border border-orange-500/20 rounded-xl px-4 py-3 mb-4">
          <AlertTriangle className="w-4 h-4 text-orange-400 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-xs font-semibold text-orange-400">Concentration risk</p>
            <p className="text-xs text-zinc-500 mt-0.5">
              {categoryCount[concentratedCategory]}+ strategies are in the same category ({concentratedCategory}). They may signal together and amplify drawdowns.
            </p>
          </div>
        </div>
      )}

      {/* Strategy list */}
      <div className="space-y-2 mb-4">
        {strategies.length === 0 ? (
          <div className="py-12 text-center border-2 border-dashed border-zinc-800 rounded-xl">
            <p className="text-zinc-600 text-sm">No strategies yet.</p>
            <p className="text-zinc-700 text-xs mt-1">Click "+ Add strategies" below to browse the library.</p>
          </div>
        ) : (
          strategies.map((s, i) => (
            <StrategyRow
              key={s.module_name}
              strategy={s}
              onRemove={() => removeStrategy(i)}
              removable={true}
            />
          ))
        )}
      </div>

      {!atCap && (
        <button
          onClick={() => setPanelOpen(true)}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-xl border-2 border-dashed border-zinc-700 text-zinc-500 hover:text-zinc-300 hover:border-zinc-600 transition-colors text-sm"
        >
          <Plus className="w-4 h-4" />
          Add strategies from library
        </button>
      )}

      {/* Nav */}
      <div className="flex items-center gap-3 mt-8">
        <button onClick={onBack} className="flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-300 transition-colors">
          <ChevronLeft className="w-4 h-4" />
          Pick different template
        </button>
        <button
          onClick={onNext}
          disabled={!canContinue}
          className="ml-auto flex items-center gap-1.5 px-6 py-2.5 rounded-xl bg-lime-500 text-black text-sm font-bold hover:bg-lime-400 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Continue: Configure
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

// ─── Step 3: Configure ────────────────────────────────────────────────────────

function ConfigureStep({
  draft,
  onUpdate,
  onBack,
  onNext,
}: {
  draft: Draft;
  onUpdate: (updates: Partial<Draft>) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const [logPct, setLogPct] = useState(toLog(draft.capitalDollars));
  const capital = fromLog(logPct);

  useEffect(() => { onUpdate({ capitalDollars: capital }); }, [capital]);

  const autoSchedule = detectSchedule(draft.strategies);

  const scheduleOptions: { key: Schedule; label: string; desc: string }[] = [
    { key: "auto", label: "Auto (recommended)", desc: `Detected: ${SCHEDULE_LABELS[autoSchedule]}` },
    { key: "daily_4pm", label: "Daily 4:05 PM ET", desc: "After market close every trading day" },
    { key: "every_4h", label: "Every 4 hours", desc: "Around the clock — good for crypto" },
    { key: "monthly", label: "Monthly", desc: "First Tuesday of each month" },
  ];

  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-1">Configure your bot</h2>
      <p className="text-sm text-zinc-500 mb-6">These settings control how aggressively it trades and how often it runs.</p>

      <div className="space-y-6">
        {/* Bot name */}
        <div>
          <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wide block mb-2">
            Bot name
          </label>
          <input
            type="text"
            value={draft.name}
            onChange={(e) => onUpdate({ name: e.target.value })}
            maxLength={50}
            placeholder="e.g. My Growth Bot"
            className="w-full bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-lime-500/50"
          />
        </div>

        {/* Capital */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wide">Paper capital</label>
            <span className="text-xl font-bold text-white">{formatDollars(capital)}</span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={logPct}
            onChange={(e) => setLogPct(Number(e.target.value))}
            className="w-full accent-lime-500"
          />
          <div className="flex justify-between text-xs text-zinc-700 mt-1">
            <span>$1k</span>
            <span>$10k</span>
            <span>$100k</span>
          </div>
          <p className="text-xs text-zinc-600 mt-1">Paper mode — no real money. You can change this any time in Settings.</p>
        </div>

        {/* Risk profile */}
        <div>
          <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wide block mb-3">Risk profile</label>
          <div className="grid grid-cols-3 gap-3">
            {(["conservative", "standard", "aggressive"] as RiskProfile[]).map((r) => (
              <button
                key={r}
                onClick={() => onUpdate({ riskProfile: r })}
                className={cn(
                  "text-left p-3 rounded-xl border transition-all",
                  draft.riskProfile === r
                    ? "bg-lime-500/15 border-lime-500/40"
                    : "bg-zinc-900 border-zinc-800 hover:border-zinc-700"
                )}
              >
                <p className={cn(
                  "text-xs font-bold capitalize mb-1",
                  draft.riskProfile === r ? "text-lime-400" : "text-zinc-300"
                )}>
                  {r}
                </p>
                <p className="text-[10px] text-zinc-500 leading-relaxed">{RISK_DESCRIPTIONS[r]}</p>
              </button>
            ))}
          </div>
        </div>

        {/* Schedule */}
        <div>
          <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wide block mb-3">Run schedule</label>
          <div className="space-y-2">
            {scheduleOptions.map((opt) => (
              <button
                key={opt.key}
                onClick={() => onUpdate({ schedule: opt.key })}
                className={cn(
                  "w-full text-left flex items-start gap-3 p-3 rounded-xl border transition-all",
                  draft.schedule === opt.key
                    ? "bg-lime-500/10 border-lime-500/30"
                    : "bg-zinc-900 border-zinc-800 hover:border-zinc-700"
                )}
              >
                <div className={cn(
                  "w-4 h-4 rounded-full border-2 flex-shrink-0 mt-0.5 flex items-center justify-center",
                  draft.schedule === opt.key ? "border-lime-500 bg-lime-500" : "border-zinc-700"
                )}>
                  {draft.schedule === opt.key && <div className="w-1.5 h-1.5 rounded-full bg-black" />}
                </div>
                <div>
                  <p className={cn("text-xs font-semibold", draft.schedule === opt.key ? "text-lime-400" : "text-zinc-300")}>
                    {opt.label}
                  </p>
                  <p className="text-[10px] text-zinc-500 mt-0.5">{opt.desc}</p>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3 mt-8">
        <button onClick={onBack} className="flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-300 transition-colors">
          <ChevronLeft className="w-4 h-4" />
          Back
        </button>
        <button
          onClick={onNext}
          disabled={!draft.name.trim()}
          className="ml-auto flex items-center gap-1.5 px-6 py-2.5 rounded-xl bg-lime-500 text-black text-sm font-bold hover:bg-lime-400 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Continue: Review
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

// ─── Step 4: Confirm ──────────────────────────────────────────────────────────

function ConfirmStep({
  draft,
  onBack,
  onDeploy,
  isDeploying,
}: {
  draft: Draft;
  onBack: () => void;
  onDeploy: () => void;
  isDeploying: boolean;
}) {
  const behaviorText = buildExpectedBehavior(draft);
  const scheduleLabel = draft.schedule === "auto"
    ? SCHEDULE_LABELS[detectSchedule(draft.strategies)]
    : SCHEDULE_LABELS[draft.schedule];

  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-1">Review & deploy</h2>
      <p className="text-sm text-zinc-500 mb-6">Check everything looks right, then hit deploy.</p>

      {/* Summary card */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 space-y-4 mb-5">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Bot name</p>
            <p className="text-sm font-bold text-white mt-0.5">{draft.name}</p>
          </div>
          <div>
            <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Strategies</p>
            <p className="text-sm font-bold text-white mt-0.5">{draft.strategies.length}</p>
          </div>
          <div>
            <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Paper capital</p>
            <p className="text-sm font-bold text-white mt-0.5">{formatDollars(draft.capitalDollars)}</p>
          </div>
          <div>
            <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Risk profile</p>
            <p className="text-sm font-bold text-white mt-0.5 capitalize">{draft.riskProfile}</p>
          </div>
          <div className="col-span-2">
            <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Schedule</p>
            <p className="text-sm font-semibold text-white mt-0.5">{scheduleLabel}</p>
          </div>
        </div>

        <div className="border-t border-zinc-800 pt-4">
          <p className="text-[10px] text-zinc-600 uppercase tracking-wide mb-2">Strategies</p>
          <div className="space-y-1">
            {draft.strategies.map((s) => (
              <div key={s.module_name} className="flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full bg-lime-500 flex-shrink-0" />
                <p className="text-xs text-zinc-300">{s.display_name}</p>
                <span className={cn(
                  "text-[9px] px-1.5 py-0.5 rounded-full border ml-auto flex-shrink-0",
                  DIFFICULTY_COLOR[s.difficulty] ?? "bg-zinc-800 text-zinc-400 border-zinc-700"
                )}>
                  {s.difficulty}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Expected behavior */}
      <div className="bg-zinc-950 border border-zinc-800 rounded-xl px-4 py-4 mb-5 space-y-2">
        <div className="flex items-center gap-2">
          <Info className="w-3.5 h-3.5 text-zinc-500" />
          <p className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Expected behavior</p>
        </div>
        <p className="text-xs text-zinc-400 leading-relaxed">{behaviorText}</p>
      </div>

      {/* Paper mode disclaimer */}
      <div className="flex items-center gap-2 bg-teal-500/10 border border-teal-500/20 rounded-xl px-4 py-3 mb-6">
        <div className="w-2 h-2 rounded-full bg-teal-400 flex-shrink-0" />
        <p className="text-xs text-teal-400 font-semibold">
          PAPER MODE — no real money moves. Simulated trades only.
        </p>
      </div>

      {/* Nav */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} disabled={isDeploying} className="flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-300 transition-colors disabled:opacity-40">
          <ChevronLeft className="w-4 h-4" />
          Back
        </button>
        <button
          onClick={onDeploy}
          disabled={isDeploying}
          className="ml-auto flex items-center gap-2 px-8 py-3 rounded-xl bg-lime-500 text-black text-sm font-bold hover:bg-lime-400 transition-colors disabled:opacity-50 shadow-lg shadow-lime-500/20"
        >
          {isDeploying ? (
            <>
              <div className="w-4 h-4 border-2 border-black border-t-transparent rounded-full animate-spin" />
              Deploying…
            </>
          ) : (
            <>
              <Rocket className="w-4 h-4" />
              Deploy Bot
            </>
          )}
        </button>
      </div>
    </div>
  );
}

// ─── Coachmark overlay ────────────────────────────────────────────────────────

const COACHMARKS = [
  { title: "Here's your bot's home", body: "The Strategies tab shows every strategy running and its last signal." },
  { title: "Watchlist rebuilds automatically", body: "Before each session, the bot re-scores the top candidates. Check the Watchlist tab to see who made the cut." },
  { title: "Open positions appear here", body: "Once the bot enters a trade you'll see it in the Positions table with entry, stop, and target prices." },
  { title: "Every decision is logged", body: "The Activity tab shows every signal with plain-English reasoning — so you always know why." },
  { title: "Pause with one click", body: "The Enable/Disable button at the top stops the bot instantly. No positions are closed — just no new entries." },
];

export function CoachmarkOverlay({ botId, onDone }: { botId: string; onDone: () => void }) {
  const [step, setStep] = useState(0);
  const coachmark = COACHMARKS[step];

  return (
    <div className="fixed inset-0 z-[100] pointer-events-none">
      {/* Dim overlay */}
      <div className="absolute inset-0 bg-black/40 pointer-events-auto" onClick={onDone} />
      {/* Floating card — center bottom */}
      <div className="absolute bottom-24 left-1/2 -translate-x-1/2 w-full max-w-sm pointer-events-auto">
        <div className="bg-zinc-900 border border-zinc-700 rounded-2xl p-5 shadow-2xl mx-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex gap-1">
              {COACHMARKS.map((_, i) => (
                <div key={i} className={cn(
                  "w-1.5 h-1.5 rounded-full transition-colors",
                  i === step ? "bg-lime-400" : "bg-zinc-700"
                )} />
              ))}
            </div>
            <button onClick={onDone} className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
              Skip tour
            </button>
          </div>
          <p className="text-sm font-bold text-white mb-1">{coachmark.title}</p>
          <p className="text-xs text-zinc-400 leading-relaxed mb-4">{coachmark.body}</p>
          <div className="flex items-center gap-3">
            {step > 0 && (
              <button onClick={() => setStep((v) => v - 1)} className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
                ← Back
              </button>
            )}
            <button
              onClick={() => step < COACHMARKS.length - 1 ? setStep((v) => v + 1) : onDone()}
              className="ml-auto px-4 py-2 rounded-lg bg-lime-500 text-black text-xs font-bold hover:bg-lime-400 transition-colors"
            >
              {step < COACHMARKS.length - 1 ? "Next →" : "Done"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

const WHIMSICAL_NAMES = [
  "Apex Alpha", "Iron Condor", "The Harvester", "Signal Nine",
  "Midnight Momentum", "The Accumulator", "Market Maker",
  "Theta Gang", "Epsilon Edge", "The Rotator",
];

function randomName() {
  return WHIMSICAL_NAMES[Math.floor(Math.random() * WHIMSICAL_NAMES.length)];
}

export default function CustomBotBuilderPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("templates");
  const [draftId, setDraftId] = useState<number | null>(null);

  const [draft, setDraft] = useState<Draft>({
    templateId: null,
    strategies: [],
    name: randomName(),
    capitalDollars: 10000,
    riskProfile: "standard",
    schedule: "auto",
  });

  // Load existing draft on mount
  const { data: existingDraft } = useQuery({
    queryKey: ["custom-bot-draft"],
    queryFn: () => client.get("/custom-bot/draft").then((r) => r.data?.draft ?? null).catch(() => null),
    staleTime: Infinity,
  });

  useEffect(() => {
    if (!existingDraft) return;
    setDraftId(existingDraft.id);
    if (existingDraft.strategies?.length) {
      // Restore draft state but don't auto-jump steps — user should still pick template
    }
  }, [existingDraft]);

  const updateDraft = useCallback((updates: Partial<Draft>) => {
    setDraft((prev) => ({ ...prev, ...updates }));
  }, []);

  // Auto-save draft on strategy/config changes
  const saveDraftMut = useMutation({
    mutationFn: () => api.saveDraft({
      name: draft.name,
      template_id: draft.templateId,
      strategies: draft.strategies.map((s) => s.module_name),
      config: {
        capital_dollars: draft.capitalDollars,
        risk_profile: draft.riskProfile,
        schedule: draft.schedule,
      },
    }),
    onSuccess: (data) => setDraftId(data.draft_id),
  });

  // Deploy
  const deployMut = useMutation({
    mutationFn: () => api.deploy({
      draft_id: draftId,
      name: draft.name,
      strategies: draft.strategies.map((s) => s.module_name),
      config: {
        capital_dollars: draft.capitalDollars,
        risk_profile: draft.riskProfile,
        schedule: draft.schedule,
      },
    }),
    onSuccess: (data) => {
      const runTime = new Date(data.first_run_ts);
      const timeStr = runTime.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      toast.success(`Bot deployed. First signal coming at ${timeStr}.`);
      // Mark coachmark as needed for this bot
      localStorage.setItem(`coachmark_pending_${data.bot_id}`, "1");
      // Small delay for animation feel
      setTimeout(() => navigate(`/strategy/${data.bot_name}`), 600);
    },
    onError: () => toast.error("Deploy failed — check bot name isn't already taken"),
  });

  function handleTemplateSelect(template: BotTemplate | null) {
    if (!template) {
      // Build from scratch — empty basket
      updateDraft({ templateId: null, strategies: [] });
      setStep("basket");
      return;
    }

    // Load strategy details for template strategies from library
    client.get(`/strategy-library?sort=sharpe`)
      .then((r) => {
        const allStrategies: LibraryStrategy[] = Array.isArray(r.data?.strategies) ? r.data.strategies : [];
        const selected = template.strategies
          .map((name) => allStrategies.find((s) => s.module_name === name))
          .filter(Boolean) as LibraryStrategy[];

        updateDraft({
          templateId: template.id,
          strategies: selected,
          capitalDollars: template.default_config.capital_dollars,
          riskProfile: template.default_config.risk_profile as RiskProfile,
          schedule: template.default_config.schedule as Schedule,
          name: `${template.name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())} Bot`,
        });
        setStep("basket");
      })
      .catch(() => {
        // Fallback: use template with stub strategies
        updateDraft({ templateId: template.id, strategies: [] });
        setStep("basket");
      });
  }

  function handleBasketNext() {
    saveDraftMut.mutate();
    setStep("configure");
  }

  function handleConfigureNext() {
    saveDraftMut.mutate();
    setStep("confirm");
  }

  const isDeploying = deployMut.isPending || step === "deploying";

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 text-xs text-zinc-500 mb-6">
        <button onClick={() => navigate("/strategy")} className="hover:text-zinc-300 transition-colors">Strategy Lab</button>
        <span className="text-zinc-700">/</span>
        <button onClick={() => navigate("/strategy/library")} className="hover:text-zinc-300 transition-colors">Library</button>
        <span className="text-zinc-700">/</span>
        <span className="text-zinc-300 font-semibold">Custom Bot</span>
      </div>

      {step !== "templates" && <StepBar current={step} />}

      {step === "templates" && (
        <>
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-bold text-white">Custom Bot Builder</h1>
              <p className="text-sm text-zinc-500 mt-1">Pick a template or start from scratch. Deploy in under 90 seconds.</p>
            </div>
            <Settings className="w-5 h-5 text-zinc-600" />
          </div>
          <TemplateStep onSelect={handleTemplateSelect} />
        </>
      )}

      {step === "basket" && (
        <BasketStep
          draft={draft}
          onUpdate={(strategies) => updateDraft({ strategies })}
          onBack={() => setStep("templates")}
          onNext={handleBasketNext}
        />
      )}

      {step === "configure" && (
        <ConfigureStep
          draft={draft}
          onUpdate={updateDraft}
          onBack={() => setStep("basket")}
          onNext={handleConfigureNext}
        />
      )}

      {step === "confirm" && (
        <ConfirmStep
          draft={draft}
          onBack={() => setStep("configure")}
          onDeploy={() => deployMut.mutate()}
          isDeploying={isDeploying}
        />
      )}
    </div>
  );
}

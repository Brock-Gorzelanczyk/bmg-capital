import { useState, useEffect, useRef, useCallback } from "react";
import {
  Plus, X, ChevronDown, Zap, Play, Bell, Check, Search,
  BarChart2, ArrowLeft, Brain, GripVertical, Share2,
  AlertTriangle, Settings2,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

type Operator =
  | ">" | "<" | ">=" | "<=" | "=" | "!="
  | "between" | "crosses_above" | "crosses_below"
  | "within_n_bars" | "comparative_gt";

type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1D";

interface Condition {
  id: string;
  not: boolean;
  field: string;
  operator: Operator;
  value: string;
  value2: string; // for "between" / "within_n_bars"
  compareField: string; // for comparative_gt
  timeframe: Timeframe;
}

interface LogicGroup {
  ids: string[];
  combinator: "AND" | "OR";
}

type ImportanceTier = "Routine" | "Significant" | "Breaking";
type RunMode = "alert" | "ondemand";
type BuilderMode = "scanner" | "alert";

// ─── Field catalog ────────────────────────────────────────────────────────────

const FIELD_CATALOG: Record<string, string[]> = {
  Price: ["Close", "Open", "High", "Low", "% Change", "Gap %", "Distance from 52W High", "Distance from 52W Low"],
  Volume: ["Volume", "Relative Volume", "Dollar Volume"],
  Technicals: ["RSI (14)", "MACD", "MACD Signal", "ATR", "BB Width", "Stoch RSI", "ADX", "EMA 20", "EMA 50", "EMA 200", "SMA 20", "SMA 50", "SMA 200", "VWAP"],
  Fundamentals: ["Market Cap", "P/E", "EPS Growth", "Revenue Growth", "Short Interest %", "Days to Cover"],
  Options: ["IV Rank", "Put/Call Ratio", "Open Interest", "Unusual Volume Calls", "Unusual Volume Puts", "GEX"],
  Crypto: ["Funding Rate", "Liquidation Level Distance", "On-chain Flows", "Exchange Netflow"],
  News: ["News Score", "Earnings Days Away", "Analyst Rating Change"],
};

const ALL_FIELDS = Object.values(FIELD_CATALOG).flat();

const NUMERIC_OPS: { label: string; value: Operator }[] = [
  { label: ">", value: ">" },
  { label: "<", value: "<" },
  { label: "≥", value: ">=" },
  { label: "≤", value: "<=" },
  { label: "=", value: "=" },
  { label: "≠", value: "!=" },
  { label: "between", value: "between" },
  { label: "crosses above", value: "crosses_above" },
  { label: "crosses below", value: "crosses_below" },
  { label: "within N bars", value: "within_n_bars" },
  { label: "> field", value: "comparative_gt" },
];

const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1h", "4h", "1D"];
const MOCK_TICKERS = ["NVDA", "AAPL", "TSLA", "AMD", "MSFT", "META", "GOOGL", "AMZN", "QQQ", "SPY"];
const EMOJIS = ["📈", "📉", "🔥", "⚡", "🎯", "💎", "🚀", "🦈"];

function uid() {
  return Math.random().toString(36).slice(2, 9);
}

function makeCondition(overrides: Partial<Condition> = {}): Condition {
  return {
    id: uid(),
    not: false,
    field: "Close",
    operator: "comparative_gt",
    value: "",
    value2: "",
    compareField: "SMA 20",
    timeframe: "1D",
    ...overrides,
  };
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function FieldDropdown({
  value,
  onChange,
  onClose,
}: {
  value: string;
  onChange: (f: string) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { inputRef.current?.focus(); }, []);

  const filtered = q
    ? ALL_FIELDS.filter((f) => f.toLowerCase().includes(q.toLowerCase()))
    : null;

  return (
    <div
      className="absolute z-50 top-full left-0 mt-1 w-64 rounded-xl border border-[var(--border-emphasis)] bg-[var(--bg-elevated-2)] shadow-2xl overflow-hidden"
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border-subtle)]">
        <Search size={14} className="text-[var(--text-tertiary)] shrink-0" />
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search fields…"
          className="w-full bg-transparent text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)]"
        />
      </div>
      <div className="max-h-56 overflow-y-auto">
        {filtered ? (
          filtered.length === 0 ? (
            <div className="py-6 text-center text-xs text-[var(--text-tertiary)]">No results</div>
          ) : (
            filtered.map((f) => (
              <button
                key={f}
                onMouseDown={() => { onChange(f); onClose(); }}
                className={cn(
                  "w-full text-left px-3 py-1.5 text-sm hover:bg-[var(--bg-elevated)] transition-colors",
                  f === value ? "text-[var(--accent-positive)]" : "text-[var(--text-primary)]"
                )}
              >
                {f}
              </button>
            ))
          )
        ) : (
          Object.entries(FIELD_CATALOG).map(([cat, fields]) => (
            <div key={cat}>
              <div className="px-3 pt-2 pb-0.5 text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">{cat}</div>
              {fields.map((f) => (
                <button
                  key={f}
                  onMouseDown={() => { onChange(f); onClose(); }}
                  className={cn(
                    "w-full text-left px-3 py-1.5 text-sm hover:bg-[var(--bg-elevated)] transition-colors",
                    f === value ? "text-[var(--accent-positive)]" : "text-[var(--text-primary)]"
                  )}
                >
                  {f}
                </button>
              ))}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function ConditionRow({
  cond,
  onChange,
  onRemove,
  combinator,
  onToggleCombinator,
  isLast,
}: {
  cond: Condition;
  onChange: (updated: Condition) => void;
  onRemove: () => void;
  combinator?: "AND" | "OR";
  onToggleCombinator?: () => void;
  isLast: boolean;
}) {
  const [fieldOpen, setFieldOpen] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);

  const set = (patch: Partial<Condition>) => onChange({ ...cond, ...patch });

  const needsValue2 = cond.operator === "between" || cond.operator === "within_n_bars";
  const isComparative = cond.operator === "comparative_gt";

  return (
    <div className="relative">
      {/* Row */}
      <div
        className={cn(
          "flex items-center gap-2 px-3 py-2 rounded-xl border transition-colors group",
          cond.not
            ? "border-red-800/60 bg-red-950/20"
            : "border-[var(--border-subtle)] bg-[var(--bg-elevated)]"
        )}
      >
        {/* Drag handle */}
        <GripVertical
          size={14}
          className="text-[var(--text-tertiary)] opacity-0 group-hover:opacity-100 cursor-grab shrink-0"
        />

        {/* NOT toggle */}
        <button
          onClick={() => set({ not: !cond.not })}
          className={cn(
            "text-xs px-1.5 py-0.5 rounded font-bold border transition-colors shrink-0",
            cond.not
              ? "border-red-500 text-red-400 bg-red-900/30"
              : "border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:border-red-500 hover:text-red-400"
          )}
          title="Toggle NOT"
        >
          NOT
        </button>

        {/* Field selector */}
        <div className="relative shrink-0">
          <button
            onClick={() => setFieldOpen((v) => !v)}
            onBlur={() => setTimeout(() => setFieldOpen(false), 150)}
            className="flex items-center gap-1 px-2 py-1 rounded-lg bg-[var(--bg-base)] border border-[var(--border-subtle)] text-sm text-[var(--text-primary)] hover:border-[var(--border-emphasis)] transition-colors whitespace-nowrap"
          >
            {cond.field}
            <ChevronDown size={12} className="text-[var(--text-tertiary)]" />
          </button>
          {fieldOpen && (
            <FieldDropdown
              value={cond.field}
              onChange={(f) => set({ field: f })}
              onClose={() => setFieldOpen(false)}
            />
          )}
        </div>

        {/* Operator */}
        <select
          value={cond.operator}
          onChange={(e) => set({ operator: e.target.value as Operator })}
          className="bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-2 py-1 text-sm text-[var(--text-primary)] outline-none cursor-pointer shrink-0"
        >
          {NUMERIC_OPS.map((op) => (
            <option key={op.value} value={op.value}>{op.label}</option>
          ))}
        </select>

        {/* Value(s) */}
        {isComparative ? (
          <div className="relative shrink-0">
            <button
              onClick={() => setCompareOpen((v) => !v)}
              onBlur={() => setTimeout(() => setCompareOpen(false), 150)}
              className="flex items-center gap-1 px-2 py-1 rounded-lg bg-[var(--bg-base)] border border-[var(--border-subtle)] text-sm text-[var(--text-primary)] hover:border-[var(--border-emphasis)] transition-colors whitespace-nowrap"
            >
              {cond.compareField}
              <ChevronDown size={12} className="text-[var(--text-tertiary)]" />
            </button>
            {compareOpen && (
              <FieldDropdown
                value={cond.compareField}
                onChange={(f) => set({ compareField: f })}
                onClose={() => setCompareOpen(false)}
              />
            )}
          </div>
        ) : (
          <>
            <input
              type="number"
              value={cond.value}
              onChange={(e) => set({ value: e.target.value })}
              placeholder="Value"
              className="w-20 bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-2 py-1 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)] shrink-0"
            />
            {needsValue2 && (
              <>
                <span className="text-xs text-[var(--text-tertiary)] shrink-0">and</span>
                <input
                  type="number"
                  value={cond.value2}
                  onChange={(e) => set({ value2: e.target.value })}
                  placeholder="Value 2"
                  className="w-20 bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-2 py-1 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)] shrink-0"
                />
              </>
            )}
          </>
        )}

        {/* Timeframe */}
        <div className="flex gap-0.5 shrink-0 ml-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => set({ timeframe: tf })}
              className={cn(
                "px-1.5 py-0.5 rounded text-xs font-medium transition-colors",
                cond.timeframe === tf
                  ? "bg-[var(--accent-positive)] text-black"
                  : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)]"
              )}
            >
              {tf}
            </button>
          ))}
        </div>

        {/* Remove */}
        <button
          onClick={onRemove}
          className="ml-auto p-1 rounded-lg text-[var(--text-tertiary)] hover:text-red-400 hover:bg-red-950/30 transition-colors shrink-0"
        >
          <X size={14} />
        </button>
      </div>

      {/* AND/OR combinator between rows */}
      {!isLast && combinator && onToggleCombinator && (
        <div className="flex justify-center my-1">
          <button
            onClick={onToggleCombinator}
            className={cn(
              "px-3 py-0.5 rounded-full text-xs font-bold border transition-colors",
              combinator === "OR"
                ? "border-amber-500 text-amber-400 bg-amber-900/20 hover:bg-amber-900/40"
                : "border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:border-[var(--border-emphasis)] hover:text-[var(--text-secondary)]"
            )}
          >
            {combinator}
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Backtest result types ────────────────────────────────────────────────────

interface BacktestResult {
  fires: number;
  avgReturn: string;
  winRate: number;
  verdict: "good" | "warn";
  curve: string; // SVG polyline points
}

function generateCurve(): string {
  const pts: string[] = [];
  let y = 80;
  for (let x = 0; x <= 200; x += 10) {
    y = Math.max(10, Math.min(90, y + (Math.random() - 0.42) * 12));
    pts.push(`${x},${y}`);
  }
  return pts.join(" ");
}

// ─── Save Modal ───────────────────────────────────────────────────────────────

function SaveModal({
  name,
  emoji,
  onClose,
}: {
  name: string;
  emoji: string;
  onClose: () => void;
}) {
  const [tier, setTier] = useState<ImportanceTier>("Significant");
  const [channels, setChannels] = useState({ push: true, email: false, digest: false });
  const [publish, setPublish] = useState(false);
  const deepLink = `bmg://scanner/${uid()}`;

  const toggleChannel = (ch: keyof typeof channels) =>
    setChannels((prev) => ({ ...prev, [ch]: !prev[ch] }));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border-emphasis)] bg-[var(--bg-elevated-2)] p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-bold text-[var(--text-primary)]">Save Scanner</h2>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-tertiary)]">
            <X size={16} />
          </button>
        </div>

        {/* Name preview */}
        <div className="flex items-center gap-3 p-3 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] mb-5">
          <span className="text-2xl">{emoji}</span>
          <span className="font-semibold text-[var(--text-primary)]">{name || "Untitled Scanner"}</span>
        </div>

        {/* Importance */}
        <div className="mb-4">
          <div className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-2">Importance</div>
          <div className="flex gap-2">
            {(["Routine", "Significant", "Breaking"] as ImportanceTier[]).map((t) => (
              <button
                key={t}
                onClick={() => setTier(t)}
                className={cn(
                  "flex-1 py-1.5 rounded-lg text-sm font-medium border transition-colors",
                  tier === t
                    ? "border-[var(--accent-positive)] text-[var(--accent-positive)] bg-[var(--accent-positive)]/10"
                    : "border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[var(--border-emphasis)]"
                )}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Channels */}
        <div className="mb-4">
          <div className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-2">Channels</div>
          <div className="flex gap-3">
            {(["push", "email", "digest"] as const).map((ch) => (
              <label key={ch} className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={channels[ch]}
                  onChange={() => toggleChannel(ch)}
                  className="accent-[#BEF264]"
                />
                <span className="text-sm capitalize text-[var(--text-secondary)]">{ch}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Publish toggle */}
        <label className="flex items-center justify-between mb-4 cursor-pointer">
          <span className="text-sm text-[var(--text-secondary)]">Publish to community library</span>
          <div
            onClick={() => setPublish((v) => !v)}
            className={cn(
              "w-10 h-5 rounded-full relative transition-colors",
              publish ? "bg-[var(--accent-positive)]" : "bg-[var(--bg-elevated)]"
            )}
          >
            <div className={cn(
              "absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform shadow",
              publish ? "translate-x-5" : "translate-x-0.5"
            )} />
          </div>
        </label>

        {/* Deep link */}
        <div className="flex items-center gap-2 p-2 rounded-lg bg-[var(--bg-base)] border border-[var(--border-subtle)] mb-5">
          <Share2 size={13} className="text-[var(--text-tertiary)] shrink-0" />
          <code className="text-xs text-[var(--text-secondary)] truncate flex-1">{deepLink}</code>
          <button
            onClick={() => { navigator.clipboard.writeText(deepLink); toast.success("Copied!"); }}
            className="text-xs text-[var(--accent-positive)] hover:underline shrink-0"
          >
            Copy
          </button>
        </div>

        <button
          onClick={() => { toast.success("Scanner saved! Watching now."); onClose(); }}
          className="w-full py-2.5 rounded-xl bg-[var(--accent-positive)] text-black font-bold hover:opacity-90 transition-opacity"
        >
          Start watching
        </button>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function AlertBuilderPage() {
  const [builderMode, setBuilderMode] = useState<BuilderMode>("scanner");
  const [runMode, setRunMode] = useState<RunMode>("alert");
  const [dryRun, setDryRun] = useState(false);
  const [scannerName, setScannerName] = useState("Untitled Scanner");
  const [emoji, setEmoji] = useState("📈");
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);

  const [conditions, setConditions] = useState<Condition[]>([
    makeCondition({ field: "Close", operator: "comparative_gt", compareField: "SMA 20", timeframe: "1D" }),
  ]);
  const [combinators, setCombinators] = useState<("AND" | "OR")[]>(["AND"]);
  const [recentFields, setRecentFields] = useState<string[]>(["Close", "RSI (14)", "Volume", "SMA 20"]);

  const [nlText, setNlText] = useState("");
  const [nlParsing, setNlParsing] = useState(false);
  const [nlParsed, setNlParsed] = useState(false);

  const [leftSearch, setLeftSearch] = useState("");
  const [expandedCats, setExpandedCats] = useState<Record<string, boolean>>(
    Object.keys(FIELD_CATALOG).reduce((a, k) => ({ ...a, [k]: true }), {})
  );

  const [matchCount, setMatchCount] = useState(0);
  const [showAllResults, setShowAllResults] = useState(false);
  const [previewTickers, setPreviewTickers] = useState<string[]>([]);

  const [backtestState, setBacktestState] = useState<"idle" | "running" | "done">("idle");
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);

  const [showSaveModal, setShowSaveModal] = useState(false);

  // Debounced match count update
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const updateCount = useCallback((numConditions: number) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      const base = 800 - numConditions * 120 + Math.round((Math.random() - 0.5) * 100);
      const count = Math.max(0, base);
      setMatchCount(count);
      const shuffled = [...MOCK_TICKERS].sort(() => Math.random() - 0.5);
      setPreviewTickers(shuffled.slice(0, 8));
    }, 500);
  }, []);

  useEffect(() => {
    updateCount(conditions.length);
  }, [conditions, updateCount]);

  const addCondition = (field?: string) => {
    const cond = makeCondition(field ? { field } : {});
    setConditions((prev) => [...prev, cond]);
    setCombinators((prev) => [...prev, "AND"]);
    if (field) {
      setRecentFields((prev) => {
        const next = [field, ...prev.filter((f) => f !== field)].slice(0, 4);
        return next;
      });
    }
  };

  const updateCondition = (id: string, updated: Condition) => {
    setConditions((prev) => prev.map((c) => (c.id === id ? updated : c)));
  };

  const removeCondition = (id: string) => {
    setConditions((prev) => {
      const idx = prev.findIndex((c) => c.id === id);
      const next = prev.filter((c) => c.id !== id);
      setCombinators((combs) => {
        const c = [...combs];
        c.splice(Math.max(0, idx - 1), 1);
        return c.slice(0, next.length - 1);
      });
      return next;
    });
  };

  const toggleCombinator = (idx: number) => {
    setCombinators((prev) => {
      const next = [...prev];
      next[idx] = next[idx] === "AND" ? "OR" : "AND";
      return next;
    });
  };

  const parseNL = async () => {
    if (!nlText.trim()) return;
    setNlParsing(true);
    await new Promise((r) => setTimeout(r, 1200));
    const parsed: Condition[] = [
      makeCondition({ field: "Close", operator: "comparative_gt", compareField: "Distance from 52W High", timeframe: "1D" }),
      makeCondition({ field: "RSI (14)", operator: ">", value: "60", timeframe: "1D" }),
      makeCondition({ field: "Close", operator: "<", value: "50", timeframe: "1D" }),
    ];
    setConditions(parsed);
    setCombinators(["AND", "AND"]);
    setNlParsing(false);
    setNlParsed(true);
    toast.success("AI compiled 3 conditions — review and edit");
  };

  const runBacktest = async () => {
    setBacktestState("running");
    setBacktestResult(null);
    await new Promise((r) => setTimeout(r, 1500));
    const fires = Math.floor(Math.random() * 66) + 15;
    const ret = (Math.random() * 2.4 + 0.8).toFixed(1);
    const winRate = Math.floor(Math.random() * 23) + 52;
    const verdict: "good" | "warn" = winRate >= 60 ? "good" : "warn";
    setBacktestResult({ fires, avgReturn: ret, winRate, verdict, curve: generateCurve() });
    setBacktestState("done");
  };

  const countColor =
    matchCount >= 5 && matchCount <= 200
      ? "text-[var(--accent-positive)]"
      : "text-amber-400";

  const filteredFields = leftSearch
    ? Object.fromEntries(
        Object.entries(FIELD_CATALOG).map(([cat, fields]) => [
          cat,
          fields.filter((f) => f.toLowerCase().includes(leftSearch.toLowerCase())),
        ]).filter(([, fields]) => (fields as string[]).length > 0)
      )
    : FIELD_CATALOG;

  return (
    <div className="min-h-screen flex flex-col bg-[var(--bg-base)] text-[var(--text-primary)]">

      {/* ── Top Bar ── */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated)] shrink-0 flex-wrap gap-y-2">
        <button
          onClick={() => window.history.back()}
          className="flex items-center gap-1 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors shrink-0"
        >
          <ArrowLeft size={15} />
          Alerts
        </button>

        <div className="flex items-center gap-1 flex-1 min-w-0">
          {/* Emoji picker */}
          <div className="relative">
            <button
              onClick={() => setShowEmojiPicker((v) => !v)}
              className="text-xl px-1 hover:bg-[var(--bg-elevated-2)] rounded-lg transition-colors"
            >
              {emoji}
            </button>
            {showEmojiPicker && (
              <div className="absolute top-full left-0 mt-1 p-2 rounded-xl border border-[var(--border-emphasis)] bg-[var(--bg-elevated-2)] shadow-xl z-50 flex gap-1">
                {EMOJIS.map((e) => (
                  <button
                    key={e}
                    onClick={() => { setEmoji(e); setShowEmojiPicker(false); }}
                    className="text-lg px-1 py-0.5 hover:bg-[var(--bg-elevated)] rounded transition-colors"
                  >
                    {e}
                  </button>
                ))}
              </div>
            )}
          </div>
          <input
            value={scannerName}
            onChange={(e) => setScannerName(e.target.value)}
            className="bg-transparent text-base font-semibold text-[var(--text-primary)] outline-none border-b border-transparent focus:border-[var(--border-emphasis)] transition-colors truncate min-w-0"
          />
        </div>

        {/* Run mode toggle */}
        <div className="flex rounded-lg overflow-hidden border border-[var(--border-subtle)] shrink-0">
          <button
            onClick={() => setRunMode("alert")}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors",
              runMode === "alert"
                ? "bg-[var(--accent-positive)] text-black"
                : "text-[var(--text-secondary)] hover:bg-[var(--bg-elevated-2)]"
            )}
          >
            <Bell size={12} /> Alert me
          </button>
          <button
            onClick={() => setRunMode("ondemand")}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors",
              runMode === "ondemand"
                ? "bg-[var(--accent-positive)] text-black"
                : "text-[var(--text-secondary)] hover:bg-[var(--bg-elevated-2)]"
            )}
          >
            <Play size={12} /> On-demand
          </button>
        </div>

        {/* Dry run toggle */}
        <label className="flex items-center gap-1.5 cursor-pointer shrink-0">
          <div
            onClick={() => setDryRun((v) => !v)}
            className={cn(
              "w-8 h-4 rounded-full relative transition-colors",
              dryRun ? "bg-[var(--accent-positive)]" : "bg-[var(--bg-elevated-2)]"
            )}
          >
            <div className={cn(
              "absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform",
              dryRun ? "translate-x-4" : "translate-x-0.5"
            )} />
          </div>
          <span className="text-xs text-[var(--text-secondary)]">Dry-run 7d</span>
        </label>

        {/* Backtest */}
        <button
          onClick={runBacktest}
          disabled={backtestState === "running"}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/20 border border-amber-500/50 text-amber-400 text-xs font-semibold hover:bg-amber-500/30 disabled:opacity-50 transition-colors shrink-0"
        >
          <BarChart2 size={13} />
          {backtestState === "running" ? "Running…" : "Backtest Alert"}
        </button>

        {/* Save */}
        <div className="relative group shrink-0">
          <button
            onClick={() => backtestState === "done" && setShowSaveModal(true)}
            disabled={backtestState !== "done"}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-colors",
              backtestState === "done"
                ? "bg-[var(--accent-positive)] text-black hover:opacity-90"
                : "bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] cursor-not-allowed"
            )}
          >
            <Check size={13} />
            Save Scanner
          </button>
          {backtestState !== "done" && (
            <div className="absolute bottom-full right-0 mb-1 px-2 py-1 rounded-lg bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-xs text-[var(--text-secondary)] whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-20">
              Run backtest first
            </div>
          )}
        </div>
      </div>

      {/* ── Alert Type Selector ── */}
      <div className="flex gap-1 px-4 pt-3 pb-0 shrink-0">
        {(["scanner", "alert"] as BuilderMode[]).map((m) => (
          <button
            key={m}
            onClick={() => setBuilderMode(m)}
            className={cn(
              "px-4 py-2 rounded-t-xl text-sm font-semibold border-b-2 transition-colors capitalize",
              builderMode === m
                ? "border-[var(--accent-positive)] text-[var(--accent-positive)]"
                : "border-transparent text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            )}
          >
            {m === "scanner" ? "Scanner — find stocks" : "Alert — notify me when"}
          </button>
        ))}
      </div>

      {/* ── 3-Column Body ── */}
      <div className="flex flex-1 overflow-hidden flex-col lg:flex-row">

        {/* ── Left Rail ── */}
        <div className="w-full lg:w-[200px] border-r border-[var(--border-subtle)] bg-[var(--bg-elevated)] flex flex-col overflow-y-auto shrink-0">
          <div className="px-3 pt-3 pb-2">
            <div className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg bg-[var(--bg-base)] border border-[var(--border-subtle)]">
              <Search size={12} className="text-[var(--text-tertiary)] shrink-0" />
              <input
                value={leftSearch}
                onChange={(e) => setLeftSearch(e.target.value)}
                placeholder="Search fields…"
                className="w-full bg-transparent text-xs text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)]"
              />
            </div>
          </div>

          {/* Recently used */}
          {recentFields.length > 0 && !leftSearch && (
            <div className="px-3 mb-2">
              <div className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-1.5">Recent</div>
              <div className="flex flex-wrap gap-1">
                {recentFields.map((f) => (
                  <button
                    key={f}
                    onClick={() => addCondition(f)}
                    className="px-2 py-0.5 rounded-md bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-xs text-[var(--text-secondary)] hover:border-[var(--accent-positive)] hover:text-[var(--accent-positive)] transition-colors"
                  >
                    {f}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Categories */}
          {Object.entries(filteredFields).map(([cat, fields]) => (
            <div key={cat} className="px-3 mb-2">
              <button
                onClick={() => setExpandedCats((prev) => ({ ...prev, [cat]: !prev[cat] }))}
                className="flex items-center justify-between w-full text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-1 hover:text-[var(--text-secondary)] transition-colors"
              >
                {cat}
                <ChevronDown
                  size={10}
                  className={cn("transition-transform", expandedCats[cat] ? "rotate-0" : "-rotate-90")}
                />
              </button>
              {expandedCats[cat] && (
                <div className="flex flex-wrap gap-1">
                  {fields.map((f) => (
                    <button
                      key={f}
                      onClick={() => addCondition(f)}
                      className="px-2 py-0.5 rounded-md bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-xs text-[var(--text-secondary)] hover:border-[var(--accent-positive)] hover:text-[var(--accent-positive)] transition-colors"
                    >
                      {f}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* ── Center: Condition Stack ── */}
        <div className="flex-1 flex flex-col overflow-y-auto px-4 py-4 gap-3">

          {builderMode === "alert" && (
            <div className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider border-b border-[var(--border-subtle)] pb-2">
              Alert fires when
            </div>
          )}
          {builderMode === "scanner" && (
            <div className="flex items-center gap-3 p-2 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-xs text-[var(--text-secondary)]">
              <Settings2 size={13} className="text-[var(--text-tertiary)]" />
              <span>Refresh interval:</span>
              {["1m", "5m", "15m", "1h"].map((t) => (
                <button key={t} className="px-2 py-0.5 rounded bg-[var(--bg-base)] border border-[var(--border-subtle)] hover:border-[var(--border-emphasis)] transition-colors">{t}</button>
              ))}
            </div>
          )}

          {/* NL Prompt */}
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3">
            <div className="flex items-center gap-2 mb-2">
              <Brain size={14} className="text-[var(--text-tertiary)]" />
              <span className="text-xs font-semibold text-[var(--text-secondary)]">Describe in plain English</span>
            </div>
            <div className="flex gap-2">
              <input
                value={nlText}
                onChange={(e) => setNlText(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && parseNL()}
                placeholder="e.g. semis breaking out with rising RSI under $50"
                className="flex-1 bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-1.5 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)] focus:border-[var(--border-emphasis)] transition-colors"
              />
              <button
                onClick={parseNL}
                disabled={nlParsing || !nlText.trim()}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-xs font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-50 transition-colors shrink-0"
              >
                <Zap size={12} className={nlParsing ? "animate-pulse text-amber-400" : ""} />
                {nlParsing ? "Parsing…" : "Parse with AI →"}
              </button>
            </div>
          </div>

          {/* AI parsed pill */}
          {nlParsed && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-900/20 border border-amber-500/40 text-amber-400 text-xs font-medium w-fit">
              <Brain size={11} />
              AI compiled this — review and edit
            </div>
          )}

          {/* Condition rows */}
          <div className="flex flex-col gap-0">
            {conditions.map((cond, i) => (
              <ConditionRow
                key={cond.id}
                cond={cond}
                onChange={(updated) => updateCondition(cond.id, updated)}
                onRemove={() => removeCondition(cond.id)}
                combinator={i < conditions.length - 1 ? combinators[i] ?? "AND" : undefined}
                onToggleCombinator={i < conditions.length - 1 ? () => toggleCombinator(i) : undefined}
                isLast={i === conditions.length - 1}
              />
            ))}
          </div>

          {conditions.length === 0 && (
            <div className="text-center py-8 text-sm text-[var(--text-tertiary)]">
              No conditions yet. Click a field chip or use the AI parser above.
            </div>
          )}

          {/* Add condition button */}
          <button
            onClick={() => addCondition()}
            className="flex items-center gap-2 px-3 py-2 rounded-xl border border-dashed border-[var(--border-subtle)] text-sm text-[var(--text-tertiary)] hover:border-[var(--accent-positive)] hover:text-[var(--accent-positive)] transition-colors w-fit"
          >
            <Plus size={14} />
            Add Condition
          </button>
        </div>

        {/* ── Right Rail ── */}
        <div className="w-full lg:w-[320px] border-l border-[var(--border-subtle)] bg-[var(--bg-elevated)] flex flex-col overflow-y-auto shrink-0">
          <div className="p-4 border-b border-[var(--border-subtle)]">
            {/* Match count */}
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">Live Preview</span>
              {(matchCount === 0 || matchCount > 500) && (
                <AlertTriangle size={13} className="text-amber-400" />
              )}
            </div>
            <div className={cn(
              "text-4xl font-black tabular-nums transition-all duration-300",
              countColor,
              "animate-pulse-once"
            )}>
              {matchCount.toLocaleString()}
            </div>
            <div className="text-xs text-[var(--text-tertiary)] mt-0.5">
              {matchCount === 0
                ? "No matches — conditions may be too tight"
                : matchCount > 500
                ? "Too many — consider tightening"
                : "matches"}
            </div>
          </div>

          {/* Preview table */}
          <div className="p-3">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[var(--text-tertiary)] border-b border-[var(--border-subtle)]">
                  <th className="text-left py-1 font-medium">Ticker</th>
                  <th className="text-right py-1 font-medium">Price</th>
                  <th className="text-right py-1 font-medium">Signal</th>
                  <th className="text-right py-1 font-medium">Vol</th>
                </tr>
              </thead>
              <tbody>
                {(showAllResults ? previewTickers : previewTickers.slice(0, 8)).map((ticker) => {
                  const price = (100 + Math.random() * 400).toFixed(2);
                  const chg = ((Math.random() - 0.45) * 6).toFixed(2);
                  const vol = `${(Math.random() * 80 + 5).toFixed(1)}M`;
                  const pos = parseFloat(chg) >= 0;
                  return (
                    <tr key={ticker} className="border-b border-[var(--border-subtle)]/50 hover:bg-[var(--bg-elevated-2)] transition-colors">
                      <td className="py-1.5 font-semibold text-[var(--text-primary)]">{ticker}</td>
                      <td className="py-1.5 text-right text-[var(--text-secondary)]">${price}</td>
                      <td className={cn("py-1.5 text-right font-medium", pos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                        {pos ? "+" : ""}{chg}%
                      </td>
                      <td className="py-1.5 text-right text-[var(--text-tertiary)]">{vol}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <button
              onClick={() => setShowAllResults((v) => !v)}
              className="mt-2 text-xs text-[var(--accent-positive)] hover:underline"
            >
              {showAllResults ? "Show fewer" : "Expand results"}
            </button>
          </div>

          {/* Backtest panel */}
          <div className="p-3 border-t border-[var(--border-subtle)]">
            <div className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-3">Backtest</div>

            {backtestState === "idle" && (
              <div className="text-xs text-[var(--text-tertiary)] text-center py-4">
                Click "Backtest Alert" to test over the last 12 months
              </div>
            )}

            {backtestState === "running" && (
              <div className="flex flex-col items-center gap-2 py-6">
                <div className="w-6 h-6 border-2 border-[var(--accent-positive)] border-t-transparent rounded-full animate-spin" />
                <span className="text-xs text-[var(--text-secondary)]">Backtesting last 12 months…</span>
              </div>
            )}

            {backtestState === "done" && backtestResult && (
              <div className="space-y-3">
                {/* Stats */}
                <div className="grid grid-cols-3 gap-2">
                  <div className="rounded-lg bg-[var(--bg-base)] border border-[var(--border-subtle)] p-2 text-center">
                    <div className="text-base font-black text-[var(--text-primary)]">{backtestResult.fires}</div>
                    <div className="text-[10px] text-[var(--text-tertiary)]">fires</div>
                  </div>
                  <div className="rounded-lg bg-[var(--bg-base)] border border-[var(--border-subtle)] p-2 text-center">
                    <div className="text-base font-black text-[var(--accent-positive)]">+{backtestResult.avgReturn}%</div>
                    <div className="text-[10px] text-[var(--text-tertiary)]">avg 1d ret</div>
                  </div>
                  <div className="rounded-lg bg-[var(--bg-base)] border border-[var(--border-subtle)] p-2 text-center">
                    <div className="text-base font-black text-[var(--text-primary)]">{backtestResult.winRate}%</div>
                    <div className="text-[10px] text-[var(--text-tertiary)]">win rate</div>
                  </div>
                </div>

                {/* Equity curve */}
                <div className="rounded-lg bg-[var(--bg-base)] border border-[var(--border-subtle)] p-2">
                  <div className="text-[10px] text-[var(--text-tertiary)] mb-1">Equity curve</div>
                  <svg viewBox="0 0 200 100" className="w-full h-12" preserveAspectRatio="none">
                    <polyline
                      points={backtestResult.curve}
                      fill="none"
                      stroke="#BEF264"
                      strokeWidth="1.5"
                      vectorEffect="non-scaling-stroke"
                    />
                  </svg>
                </div>

                {/* Verdict */}
                <div className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-semibold",
                  backtestResult.verdict === "good"
                    ? "bg-[var(--accent-positive)]/10 border-[var(--accent-positive)]/40 text-[var(--accent-positive)]"
                    : "bg-amber-900/20 border-amber-500/40 text-amber-400"
                )}>
                  {backtestResult.verdict === "good" ? <Check size={12} /> : <AlertTriangle size={12} />}
                  {backtestResult.verdict === "good"
                    ? "Looks good → save"
                    : "High false-positive rate — consider tightening"}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Save Modal ── */}
      {showSaveModal && (
        <SaveModal
          name={scannerName}
          emoji={emoji}
          onClose={() => setShowSaveModal(false)}
        />
      )}
    </div>
  );
}

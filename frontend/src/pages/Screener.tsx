import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { runScreen, runPreset, getSavedScreens, saveScreen, deleteSavedScreen, parseNaturalLanguage } from "@/api/screener";
import { getSectorPerformance } from "@/api/discovery";
import type { FilterConfig, ScreenResult } from "@/types/screener";
import { formatCurrency, formatPercent, formatVolume, cn } from "@/lib/utils";
import { Play, Plus, Trash2, TrendingUp, BarChart2, ArrowDownUp, Zap, Info, Bookmark, BookmarkCheck, X, Sparkles, Loader2, RefreshCw } from "lucide-react";
import { TICKER_NAMES } from "@/data/tickerNames";
import SectorPill from "@/components/ui/SectorPill";

// ── Preset categories ────────────────────────────────────────────────────────

const PRESET_CATEGORIES = [
  {
    label: "Growth & Momentum",
    icon: TrendingUp,
    color: "#26a69a",
    presets: [
      {
        key: "canslim_leaders",
        label: "CAN SLIM Leaders",
        desc: "O'Neil: SMA50, RSI>60, high relative volume",
        info: "Setup: Institutional-quality growth leader in a confirmed uptrend. Entry: Buy as close to the pivot/breakout point as possible on volume ≥ 1.5× average — not extended more than 5% from the buy point. Stop: Cut the loss at 7–8% below your entry, no exceptions. Target: 20–25% profit; sell into strength if it stalls. Position size: Risk no more than 1–2% of total portfolio per trade. Best conditions: Confirmed bull market — count follow-through days to verify.",
      },
      {
        key: "stage2_breakout",
        label: "Stage 2 Breakout",
        desc: "Minervini: price above all MAs, SMA200 trending up",
        info: "Setup: Minervini SEPA — stock in the \"markup phase\" with all MAs properly stacked. Entry: Enter on a tight consolidation breakout with volume surge, or on a pullback to the rising 10-week MA. Stop: 7–8% below entry, or below the 50-day MA if it violates that level on high volume. Target: Hold winners 20–25%+; let them run if volume stays strong. Position size: Full position (2% portfolio risk) — this is a high-conviction setup. Best conditions: Works in any market with a strong sector catalyst.",
      },
      {
        key: "momentum_surge",
        label: "Momentum Surge",
        desc: "Near 52W high, RSI 50+, 1.5× avg volume",
        info: "Setup: Stock near 52-week highs with institutional volume — price and volume confirm each other. Entry: Buy on breakout to new highs with volume ≥ 1.5× 20-day average. Do not chase — wait for a volume spike, not extended price. Stop: Below the most recent consolidation low, typically 5–8% away. Target: 15–20%; momentum names can run hard but reverse fast. Position size: Half position initially; add on first pullback if it holds. Best conditions: Trending bull market; avoid in choppy/range-bound tape.",
      },
      {
        key: "high_rs_momentum",
        label: "High RS Leaders",
        desc: "Top 15% of 52W high, RSI>55, consecutive gains",
        info: "Setup: Market leader in relative strength — outperforming the S&P 500 on the way up. Entry: After 2+ consecutive up days, buy on the next morning's open if price holds above the prior day's close. Stop: Below the low of the 2-day up move — usually 4–6% risk. Target: 15–25%; RS leaders tend to keep leading. Position size: 1.5% portfolio risk — reliable but not guaranteed. Best conditions: Works even in mild downturns; the RS leader is the last to fall.",
      },
      {
        key: "power_trend",
        label: "Power Trend",
        desc: "EMA8>EMA21>EMA55, price above SMA50",
        info: "Setup: EMA8 > EMA21 > EMA55 — all three timeframes aligned bullishly (no noise). Entry: Buy on any pullback that touches the EMA21 and holds, confirmed by a green reversal candle. Stop: Below the EMA55; if the stack breaks, the trend is over — exit without hesitation. Target: Hold as long as EMA stack is intact; ride it for 20–40%+ in strong trends. Position size: 1% risk — trend-following requires tolerance for pullbacks. Best conditions: Best in trending markets; stacks form slowly so the signal is reliable.",
      },
    ],
  },
  {
    label: "Value & Mean Reversion",
    icon: ArrowDownUp,
    color: "#3b82f6",
    presets: [
      {
        key: "mean_reversion_quality",
        label: "Quality Dip Buy",
        desc: "RSI<40, above SMA200, price>$10",
        info: "Setup: Strong stock in a long-term uptrend that has pulled back hard — quality at a discount. Entry: Buy when RSI turns back up from below 40, ideally on a reversal candle with volume. Do not buy a falling knife — wait for the turn. Stop: Below the most recent swing low, or below the 200-day MA if it violates it. Target: 8–12% bounce back toward the 50-day MA; don't expect new highs immediately. Position size: Half position — mean reversion trades have lower win rates; size accordingly. Best conditions: Works best in range-bound markets or mild corrections in uptrends.",
      },
      {
        key: "deep_value_bounce",
        label: "Quality Oversold",
        desc: "RSI<35, above SMA200, high volume spike",
        info: "Setup: Oversold stock with a volume capitulation spike — sellers are exhausted. Entry: Wait for the first green reversal day with volume confirmation before entering. Never buy red into a volume spike. Stop: Below the capitulation low — if price undercuts that low on volume, the selling is not done. Target: 8–15% bounce; this is a trade, not an investment. Take profit quickly. Position size: Small — 0.75% portfolio risk max. Capitulation bounces fail often. Best conditions: Late-stage corrections, earnings blow-ups in otherwise healthy stocks.",
      },
    ],
  },
  {
    label: "Technical Patterns",
    icon: Zap,
    color: "#f59e0b",
    presets: [
      {
        key: "volatility_contraction",
        label: "Volatility Squeeze",
        desc: "BB width <5%, price above SMA50 (VCP setup)",
        info: "Setup: VCP — price coiling tighter and tighter in declining volatility, building energy for a move. Entry: Set a buy stop $0.10 above the high of the tightest contraction bar. Let it trigger on its own — do not anticipate. Stop: Below the lowest low of the VCP base — usually 6–10% risk. Target: 20–30%+; VCPs that work tend to produce explosive moves. Position size: 2% portfolio risk — this is Minervini's highest-conviction setup. Best conditions: Works in any market; the tighter the contraction, the more powerful the breakout.",
      },
      {
        key: "ema_stack_uptrend",
        label: "EMA Stack",
        desc: "EMA8>EMA21>EMA55 — strong momentum trend",
        info: "Setup: Clean multi-timeframe uptrend with no conflicting signals. Entry: Buy on any intraday pullback to the EMA21 — set a limit order, don't chase breakouts. Stop: Below the EMA55 with a daily close confirmation. Target: No fixed target; trail stop up to the EMA21 as it rises. Position size: 1–1.5% risk; this is a \"set and trail\" trade. Best conditions: Trending markets only; flat/choppy action will whipsaw the EMAs.",
      },
      {
        key: "consecutive_gains",
        label: "Momentum Continuation",
        desc: "3+ up days in a row, RSI 40–75",
        info: "Setup: Steady accumulation pattern — stock closing higher day after day, no distribution. Entry: Buy on the open of day 4 if days 1–3 each closed in the upper half of the day's range. Stop: Below the low of day 1 of the up streak — if that breaks, the pattern has failed. Target: 8–12%; three consecutive gains is a short-term momentum signal, not a trend change. Position size: Half position; these setups have moderate win rates. Best conditions: Works best at the start of a new market uptrend or after a sector rotation.",
      },
    ],
  },
  {
    label: "Classic Screens",
    icon: BarChart2,
    color: "#8b5cf6",
    presets: [
      {
        key: "rsi_oversold",
        label: "RSI Oversold",
        desc: "RSI < 30 — extreme short-term oversold",
        info: "Setup: Extreme short-term oversold reading — stock likely down 10–15%+ in a short period. Entry: Do NOT buy RSI < 30 blindly. Wait for RSI to cross back above 30, then enter on the next day's open. Stop: Below the multi-day low of the oversold period — if it fails to reclaim 30, it's a falling knife. Target: Quick 5–10% bounce back toward the mean; take profit fast. Position size: Small — 0.5% portfolio risk. Oversold alone is not a thesis. Best conditions: Only trade RSI oversold when the stock is still above its 200-day MA. Avoid in downtrends.",
      },
      {
        key: "golden_cross",
        label: "Golden Cross",
        desc: "SMA50 just crossed above SMA200",
        info: "Setup: SMA50 just crossed above SMA200 — long-term bullish confirmation. Entry: Buy on the first daily close above both moving averages after the crossover. Volume should confirm — above average on the breakout day. Stop: Below the SMA200 on a closing basis — if it crosses back under, exit. Target: Hold for weeks to months; golden crosses tend to produce sustained trends. Position size: 1.5% risk; this is a slow-burn trend trade, not a quick flip. Best conditions: Works best after prolonged bear markets or sector bottoms — the bigger the base, the bigger the move.",
      },
      {
        key: "macd_bullish",
        label: "MACD Crossover",
        desc: "MACD line just crossed above signal",
        info: "Setup: MACD line just crossed above signal line — shift from bearish to bullish momentum. Entry: Buy at next day's open after confirmed MACD crossover, ideally with price also above the 50-day MA. Stop: Below the low made on the day of the crossover, or 6% below entry — whichever is tighter. Target: 10–15%; MACD crossovers signal direction shifts, not home runs. Take partial profits early. Position size: 1% portfolio risk; MACD crossovers can be noisy in range-bound markets. Best conditions: Most reliable in trending markets; filter out crossovers when price is below the 200-day MA.",
      },
      {
        key: "volume_surge",
        label: "Volume Surge",
        desc: "Volume > 2× 20-day average",
        info: "Setup: Unusual institutional activity — someone big is buying or selling. Follow the direction of price. Entry: If price is UP on the volume surge — buy at the open the next morning. If price is DOWN — do not buy; wait to see if distribution is happening. Stop: Below the low of the high-volume day — institutions usually don't let a breakout close below that. Target: 10–20%; volume surges often precede sustained moves as institutions continue accumulating. Position size: 1% risk; the direction is confirmed by price, but size up on strength. Best conditions: Works in all market conditions — unusual volume is unusual volume.",
      },
      {
        key: "breakout_52w",
        label: "52-Week High",
        desc: "Breaking out to a new 52-week high",
        info: "Setup: New 52-week high — price in territory with no overhead resistance from prior sellers. Entry: Buy within 1–2% of the new high with volume ≥ 1.5× average. Do not buy extended. Stop: Below the prior resistance level that just became support — typically 5–7% risk. Target: 20–30%+; stocks making new highs tend to continue making new highs. Position size: 1.5% risk; this is the buy-high-sell-higher principle — emotionally hard but statistically sound. Best conditions: Bull markets only. Avoid in bear markets; new highs in downtrends are often bull traps.",
      },
    ],
  },
];

const FIELDS = [
  { value: "rsi", label: "RSI" },
  { value: "price", label: "Price" },
  { value: "volume", label: "Volume" },
  { value: "ma_cross", label: "MA Cross" },
  { value: "macd_cross", label: "MACD Cross" },
  { value: "volume_breakout", label: "Volume Breakout" },
  { value: "breakout_52w", label: "52-Week Breakout" },
  { value: "price_above_ma", label: "Price > MA" },
  { value: "stage", label: "Stage 2 (Minervini)" },
  { value: "ema_stack", label: "EMA Stack (8>21>55)" },
  { value: "consecutive_gains", label: "Consecutive Gains" },
  { value: "bollinger_squeeze", label: "Bollinger Squeeze" },
  { value: "relative_high", label: "Near N-Day High" },
];

const OPERATORS = [
  { value: "gt", label: ">" },
  { value: "lt", label: "<" },
  { value: "gte", label: ">=" },
  { value: "lte", label: "<=" },
  { value: "eq", label: "=" },
];

export default function Screener() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [filters, setFilters] = useState<FilterConfig[]>([]);
  const [results, setResults] = useState<ScreenResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [ran, setRan] = useState(false);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [infoOpen, setInfoOpen] = useState<string | null>(null);
  const infoRef = useRef<HTMLDivElement>(null);
  const [saveNameInput, setSaveNameInput] = useState("");
  const [showSaveForm, setShowSaveForm] = useState(false);

  const [nlQuery, setNlQuery] = useState("");
  const [nlParsing, setNlParsing] = useState(false);
  const [nlExplanation, setNlExplanation] = useState<string | null>(null);
  const [nlRefinementChips, setNlRefinementChips] = useState<Array<{ label: string; isNew: boolean }>>([]);
  const [nlFollowUpMode, setNlFollowUpMode] = useState(false);

  // Convert active FilterConfig[] to FilterChip[] for passing as existing_filters
  const filtersAsChips = filters.map((f) => ({
    field: f.field,
    operator: f.operator,
    value: f.value as string | number,
    label: `${f.field} ${f.operator} ${f.value}`,
  }));

  const handleNLSearch = async () => {
    if (!nlQuery.trim() || nlParsing) return;
    setNlParsing(true);
    setNlExplanation(null);
    const isFollowUp = filters.length > 0;
    try {
      const result = await parseNaturalLanguage(
        nlQuery.trim(),
        isFollowUp ? filtersAsChips : undefined,
      );
      if (result.filters.length > 0) {
        const incoming = result.filters.map((f) => ({
          field: f.field,
          operator: f.operator,
          value: f.value,
        }));
        if (result.merge) {
          // Merge: overwrite by field, append new fields
          const merged = [...filters];
          const refinementChips: Array<{ label: string; isNew: boolean }> = [];
          for (const inc of incoming) {
            const existingIdx = merged.findIndex((e) => e.field === inc.field);
            if (existingIdx >= 0) {
              refinementChips.push({ label: `Changed: ${inc.field}`, isNew: false });
              merged[existingIdx] = inc;
            } else {
              refinementChips.push({ label: `+ ${inc.field}`, isNew: true });
              merged.push(inc);
            }
          }
          setFilters(merged);
          setNlRefinementChips(refinementChips);
          setNlFollowUpMode(true);
        } else {
          setFilters(incoming);
          setNlRefinementChips([]);
          setNlFollowUpMode(false);
        }
        setNlExplanation(result.explanation);
      }
    } catch {
      // silently ignore — user can retry
    } finally {
      setNlParsing(false);
    }
  };

  const handleClearAndStartOver = () => {
    setFilters([]);
    setNlQuery("");
    setNlExplanation(null);
    setNlRefinementChips([]);
    setNlFollowUpMode(false);
    setRan(false);
    setResults([]);
    setActivePreset(null);
  };

  const { data: savedScreens = [] } = useQuery({
    queryKey: ["saved-screens"],
    queryFn: getSavedScreens,
  });

  const { data: sectorData, isLoading: sectorsLoading, refetch: refetchSectors, isFetching: sectorsFetching } = useQuery({
    queryKey: ["sectors"],
    queryFn: getSectorPerformance,
    staleTime: 60_000,
  });

  const saveMut = useMutation({
    mutationFn: () => saveScreen(saveNameInput.trim(), filters),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["saved-screens"] });
      setSaveNameInput("");
      setShowSaveForm(false);
    },
  });

  const deleteMut = useMutation({
    mutationFn: deleteSavedScreen,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-screens"] }),
  });

  // Close info popover on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (infoRef.current && !infoRef.current.contains(e.target as Node)) {
        setInfoOpen(null);
      }
    };
    if (infoOpen) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [infoOpen]);

  const addFilter = () => setFilters([...filters, { field: "rsi", operator: "lt", value: 30 }]);
  const removeFilter = (i: number) => {
    const next = filters.filter((_, idx) => idx !== i);
    setFilters(next);
    if (next.length === 0) {
      setNlRefinementChips([]);
      setNlFollowUpMode(false);
    }
  };
  const updateFilter = (i: number, patch: Partial<FilterConfig>) =>
    setFilters(filters.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));

  const run = async (filterList = filters) => {
    setLoading(true);
    setRan(false);
    setActivePreset(null);
    try {
      const res = await runScreen(filterList);
      setResults(res);
    } finally {
      setLoading(false);
      setRan(true);
    }
  };

  const runPresetScreen = async (key: string) => {
    setLoading(true);
    setRan(false);
    setActivePreset(key);
    try {
      const res = await runPreset(key);
      setResults(res);
    } finally {
      setLoading(false);
      setRan(true);
    }
  };

  const activePresetMeta = PRESET_CATEGORIES.flatMap((c) => c.presets).find((p) => p.key === activePreset);
  const openInfoPreset = PRESET_CATEGORIES.flatMap((c) => c.presets).find((p) => p.key === infoOpen);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-[var(--text-primary)]">Stock Screener</h2>
        <span className="text-xs text-[var(--text-tertiary)]">Universe: 500+ stocks</span>
      </div>

      {/* Natural language input */}
      <div className="space-y-2">
        <div className="relative">
          <input
            value={nlQuery}
            onChange={e => setNlQuery(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleNLSearch()}
            placeholder={filters.length > 0 ? 'Refine results, e.g. "now narrow to large-cap"' : 'Try: "show me tech stocks with RSI under 30 and rising volume"'}
            className="w-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3 text-sm text-[var(--text-secondary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--accent-positive)] pr-24"
          />
          <button
            onClick={handleNLSearch}
            disabled={nlParsing || !nlQuery.trim()}
            className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent-positive)] text-black text-xs font-semibold rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {nlParsing ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
            {nlParsing ? "Parsing…" : "Search"}
          </button>
        </div>
        {nlExplanation && (
          <div className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)]">
            <Sparkles size={11} className="text-[var(--accent-positive)] shrink-0" />
            <span><span className="text-[var(--text-secondary)] font-medium">Interpreted as:</span> {nlExplanation}</span>
          </div>
        )}
        {nlFollowUpMode && nlRefinementChips.length > 0 && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">Refined:</span>
            {nlRefinementChips.map((chip, i) => (
              <span
                key={i}
                className={cn(
                  "inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium border",
                  chip.isNew
                    ? "bg-[var(--accent-positive)]/10 border-[var(--accent-positive)]/30 text-[var(--accent-positive)]"
                    : "bg-[var(--bg-elevated-2)] border-[var(--border-emphasis)] text-[var(--text-secondary)]"
                )}
              >
                {chip.label}
              </span>
            ))}
            <button
              onClick={handleClearAndStartOver}
              className="ml-auto text-[11px] text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] transition-colors underline underline-offset-2"
            >
              Clear &amp; start over
            </button>
          </div>
        )}
      </div>

      {/* Strategy category cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {PRESET_CATEGORIES.map((cat) => {
          const Icon = cat.icon;
          return (
            <div key={cat.label} className="bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-xl p-4 space-y-3">
              <div className="flex items-center gap-2">
                <Icon size={14} style={{ color: cat.color }} />
                <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: cat.color }}>
                  {cat.label}
                </span>
              </div>
              <div className="space-y-1">
                {cat.presets.map((p) => {
                  const isActive = activePreset === p.key && !loading;
                  return (
                    <div key={p.key} className="relative group">
                      <button
                        onClick={() => runPresetScreen(p.key)}
                        disabled={loading}
                        className={cn(
                          "w-full text-left px-3 py-2 pr-8 rounded-lg border transition-all text-sm",
                          isActive
                            ? "border-zinc-600 bg-[#334155] text-[var(--text-primary)]"
                            : "border-transparent hover:border-[var(--border-emphasis)] hover:bg-[var(--bg-elevated-2)] text-[var(--text-secondary)]"
                        )}
                      >
                        <div className="font-medium">{p.label}</div>
                        <div className="text-[11px] text-[var(--text-tertiary)] mt-0.5 leading-tight">{p.desc}</div>
                      </button>

                      {/* Info button — visible on hover */}
                      <button
                        onClick={(e) => { e.stopPropagation(); setInfoOpen(infoOpen === p.key ? null : p.key); }}
                        className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-opacity"
                        title="What does this screen do?"
                      >
                        <Info size={13} />
                      </button>

                      {/* Info popover */}
                      {infoOpen === p.key && (
                        <div
                          ref={infoRef}
                          className="absolute z-50 left-0 right-0 top-full mt-1 bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] rounded-lg p-3 shadow-2xl text-xs text-[var(--text-secondary)] leading-relaxed"
                        >
                          {p.info}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Custom filter builder */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-3">
        <p className="text-[var(--text-tertiary)] text-xs uppercase tracking-widest">Custom Filter Builder</p>
        {filters.map((f, i) => (
          <div key={i} className="flex gap-2 items-center flex-wrap">
            <select
              value={f.field}
              onChange={(e) => updateFilter(i, { field: e.target.value })}
              className="bg-[#020617] text-[var(--text-primary)] text-base md:text-sm px-2 py-1.5 rounded border border-[var(--border-emphasis)] focus:outline-none focus:border-zinc-600"
            >
              {FIELDS.map((ff) => <option key={ff.value} value={ff.value}>{ff.label}</option>)}
            </select>
            <select
              value={f.operator}
              onChange={(e) => updateFilter(i, { operator: e.target.value })}
              className="bg-[#020617] text-[var(--text-primary)] text-base md:text-sm px-2 py-1.5 rounded border border-[var(--border-emphasis)] w-16 focus:outline-none focus:border-zinc-600"
            >
              {OPERATORS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <input
              type="number"
              value={f.value as number}
              onChange={(e) => updateFilter(i, { value: parseFloat(e.target.value) })}
              className="bg-[#020617] text-[var(--text-primary)] text-base md:text-sm px-2 py-1.5 rounded border border-[var(--border-emphasis)] w-24 focus:outline-none focus:border-zinc-600"
            />
            <button onClick={() => removeFilter(i)} className="text-[var(--text-tertiary)] hover:text-[var(--accent-negative)]">
              <Trash2 size={15} />
            </button>
          </div>
        ))}
        <div className="flex gap-2 pt-1 flex-wrap">
          <button onClick={addFilter} className="flex items-center gap-1 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            <Plus size={13} /> Add Filter
          </button>
          {filters.length > 0 && (
            <button
              onClick={() => setShowSaveForm((s) => !s)}
              className="flex items-center gap-1 text-sm text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
            >
              <Bookmark size={13} /> Save Screen
            </button>
          )}
          <button
            onClick={() => run()}
            disabled={loading || !filters.length}
            className="flex items-center gap-1 bg-[var(--accent-positive)] hover:brightness-110 disabled:opacity-40 text-[var(--text-primary)] font-semibold text-sm px-3 py-1.5 rounded ml-auto"
          >
            <Play size={13} /> {loading ? "Scanning..." : "Run Screen"}
          </button>
        </div>
        {showSaveForm && (
          <div className="flex gap-2 items-center pt-1">
            <input
              autoFocus
              value={saveNameInput}
              onChange={(e) => setSaveNameInput(e.target.value)}
              placeholder="Screen name…"
              className="bg-[#020617] text-[var(--text-primary)] text-sm px-2 py-1.5 rounded border border-[var(--border-emphasis)] w-40 placeholder-zinc-600 focus:outline-none focus:border-zinc-500"
            />
            <button
              onClick={() => { if (saveNameInput.trim()) saveMut.mutate(); }}
              disabled={!saveNameInput.trim() || saveMut.isPending}
              className="bg-[var(--accent-positive)] text-[var(--text-primary)] font-semibold text-xs px-3 py-1.5 rounded hover:brightness-110 disabled:opacity-50"
            >
              Save
            </button>
            <button onClick={() => setShowSaveForm(false)} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)]">
              <X size={13} />
            </button>
          </div>
        )}
      </div>

      {/* Saved screens */}
      {savedScreens.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider">Saved:</span>
          {savedScreens.map((s) => (
            <div key={s.id} className="group flex items-center gap-1 bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] rounded-full px-3 py-1">
              <button
                onClick={() => { setFilters(s.filters); run(s.filters); setActivePreset(null); }}
                className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center gap-1.5"
              >
                <BookmarkCheck size={11} className="text-[var(--text-tertiary)]" />
                {s.name}
              </button>
              <button
                onClick={() => deleteMut.mutate(s.id)}
                className="opacity-0 group-hover:opacity-100 text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] ml-1 transition-opacity"
              >
                <X size={10} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="text-center py-8 text-[var(--text-secondary)] text-sm animate-pulse">
          Scanning 500+ stocks...
        </div>
      )}

      {/* Sector heatmap — shown when no screen has been run yet */}
      {!loading && !ran && (() => {
        const sectors = sectorData?.sectors ?? [];
        const max = Math.max(...sectors.map((s) => Math.abs(s.change_pct)), 0.01);
        function heatColor(pct: number, maxVal: number): string {
          const intensity = Math.min(Math.abs(pct) / maxVal, 1);
          if (pct > 0) {
            const g = Math.round(100 + intensity * 100);
            return `rgb(0, ${g}, 60)`;
          }
          const r = Math.round(100 + intensity * 120);
          return `rgb(${r}, 0, 30)`;
        }
        return (
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Sector Performance</h3>
                <p className="text-xs text-[var(--text-tertiary)] mt-0.5">Run a screen above or explore sector performance</p>
              </div>
              <button
                onClick={() => refetchSectors()}
                className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
              >
                <RefreshCw size={13} className={sectorsFetching ? "animate-spin" : ""} />
              </button>
            </div>
            {sectorsLoading ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
                {[...Array(11)].map((_, i) => (
                  <div key={i} className="h-20 bg-[var(--bg-elevated-2)] rounded-xl animate-pulse" />
                ))}
              </div>
            ) : sectors.length === 0 ? (
              <div className="text-center py-12 text-[var(--text-tertiary)] text-sm">
                Sector data unavailable — add Alpaca API keys to enable live data
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
                {sectors
                  .slice()
                  .sort((a, b) => b.change_pct - a.change_pct)
                  .map((s) => (
                    <div
                      key={s.sector}
                      className="rounded-xl p-3 flex flex-col gap-1 transition-transform hover:scale-[1.02] cursor-default"
                      style={{ backgroundColor: heatColor(s.change_pct, max) }}
                    >
                      <div className="text-[var(--text-primary)] font-semibold text-sm leading-tight">{s.sector}</div>
                      <div className="text-[var(--text-primary)]/70 text-[11px] font-mono">{s.symbol}</div>
                      <div className="flex items-center justify-between mt-auto">
                        <span className="text-[var(--text-primary)]/80 text-xs font-mono">${s.price.toFixed(2)}</span>
                        <span className="text-[var(--text-primary)] font-bold text-sm">
                          {(s.change_pct >= 0 ? "+" : "") + s.change_pct.toFixed(2) + "%"}
                        </span>
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>
        );
      })()}

      {/* Results */}
      {!loading && ran && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
            <div>
              <span className="text-sm font-semibold text-[var(--text-primary)]">{results.length} results</span>
              {activePresetMeta && (
                <span className="ml-2 text-xs text-[var(--text-tertiary)]">· {activePresetMeta.label}</span>
              )}
            </div>
            {activePreset && (
              <span className="text-[11px] text-[var(--text-tertiary)]">Click a ticker to open chart with this screen's indicators</span>
            )}
          </div>
          {results.length === 0 ? (
            <div className="py-12 text-center text-[var(--text-tertiary)]">No stocks matched the criteria.</div>
          ) : (
            <div className="overflow-x-auto -mx-3 md:mx-0">
              <table className="w-full text-sm min-w-[480px]">
                <thead>
                  <tr className="border-b border-[var(--border-subtle)] text-[11px] text-[var(--text-tertiary)] uppercase tracking-wide whitespace-nowrap">
                    <th className="text-left px-4 py-2">Symbol</th>
                    <th className="text-right px-4 py-2">Price</th>
                    <th className="text-right px-4 py-2">1D Chg</th>
                    <th className="text-right px-4 py-2 hidden sm:table-cell">5D Chg</th>
                    <th className="text-right px-4 py-2 hidden sm:table-cell">Volume</th>
                    <th className="text-right px-4 py-2">Rel Vol</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r) => (
                    <tr
                      key={r.symbol}
                      onClick={() => navigate(`/chart?symbol=${r.symbol}${activePreset ? `&preset=${activePreset}` : ""}`)}
                      className="border-b border-[var(--border-subtle)]/50 hover:bg-[var(--bg-elevated-2)]/50 cursor-pointer transition-colors"
                    >
                      <td className="px-4 py-3">
                        <div className="font-mono font-semibold text-[var(--text-primary)]">{r.symbol}</div>
                        {TICKER_NAMES[r.symbol] && (
                          <div className="text-[11px] text-[var(--text-tertiary)] truncate max-w-[160px]">{TICKER_NAMES[r.symbol]}</div>
                        )}
                        <SectorPill symbol={r.symbol} className="mt-0.5" />
                      </td>
                      <td className="px-4 py-3 text-right text-[var(--text-primary)]">{formatCurrency(r.price)}</td>
                      <td className={cn("px-4 py-3 text-right font-medium", r.change_pct >= 0 ? "text-[#26a69a]" : "text-[#ef5350]")}>
                        {r.change_pct >= 0 ? "+" : ""}{formatPercent(r.change_pct)}
                      </td>
                      <td className={cn("px-4 py-3 text-right font-medium hidden sm:table-cell", (r.change_5d ?? 0) >= 0 ? "text-[#26a69a]" : "text-[#ef5350]")}>
                        {(r.change_5d ?? 0) >= 0 ? "+" : ""}{formatPercent(r.change_5d ?? 0)}
                      </td>
                      <td className="px-4 py-3 text-right text-[var(--text-secondary)] hidden sm:table-cell">{formatVolume(r.volume)}</td>
                      <td className={cn("px-4 py-3 text-right font-medium", (r.rel_volume ?? 1) >= 1.5 ? "text-[#26a69a]" : "text-[var(--text-secondary)]")}>
                        {(r.rel_volume ?? 1).toFixed(2)}×
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

import { useState, useEffect, useRef, useCallback } from "react";
import { CheckSquare, Square, Lock, ChevronDown, ChevronUp, Upload, Flame, BookOpen, X, Trophy, Loader2, AlertCircle } from "lucide-react";
import RetiredBanner from "@/components/RetiredBanner";
import { cn } from "@/lib/utils";
import { analyzeImage, type ImageAnalysis } from "@/api/workshop";
import { useIsAdmin } from "@/store/authStore";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Lesson { id: string; name: string; difficulty: "Beginner" | "Intermediate" | "Advanced"; description: string; }
interface Section { id: string; emoji: string; title: string; lessons: Lesson[]; defaultExpanded?: boolean; showCount?: number; }
interface TAProgress { completed: string[]; streak: number; lastDate: string; }
interface DailyQuiz { question: string; options: string[]; correctIndex: number; explanation: string; }

// ── Data ──────────────────────────────────────────────────────────────────────

const TOTAL_LESSONS = 38;

const SECTIONS: Section[] = [
  {
    id: "basics", emoji: "📊", title: "Chart Basics", defaultExpanded: true,
    lessons: [
      { id: "candle-anatomy", name: "Candlestick anatomy", difficulty: "Beginner", description: "Learn the body, wick, and shadow. Open, high, low, and close tell the story of every session." },
      { id: "trend-lines", name: "Trend lines", difficulty: "Beginner", description: "Higher highs/lows define uptrends; lower highs/lows define downtrends. Trend lines frame the market's bias." },
      { id: "support-resistance", name: "Support and resistance", difficulty: "Beginner", description: "Levels where buying or selling has historically reversed price. Old resistance becomes new support after a breakout." },
      { id: "volume-basics", name: "Volume basics", difficulty: "Beginner", description: "Volume confirms moves. A breakout on heavy volume is far more reliable than one on thin, indifferent volume." },
      { id: "time-frames", name: "Time frames", difficulty: "Beginner", description: "Daily shows the trend, 5-minute shows noise. Always know which time frame you are trading and which frame sets context." },
      { id: "gaps", name: "Gaps and breakaways", difficulty: "Intermediate", description: "Breakaway gaps launch new trends; exhaustion gaps end them. Gap direction and volume determine which type you have." },
      { id: "multi-tf", name: "Multi-time-frame analysis", difficulty: "Intermediate", description: "Align weekly, daily, and intraday before entering. Trades with all frames in agreement have the highest probability." },
      { id: "log-linear", name: "Log vs linear scales", difficulty: "Intermediate", description: "Log scale makes equal percentage moves look equal. Use it for long-term charts to avoid misleading size distortions." },
    ],
  },
  {
    id: "indicators", emoji: "📈", title: "Indicators", showCount: 4,
    lessons: [
      { id: "ma", name: "Moving averages (SMA, EMA)", difficulty: "Beginner", description: "SMAs weight all bars equally; EMAs emphasize recent price. The 21, 50, and 200 EMAs are watched by institutions." },
      { id: "rsi", name: "RSI", difficulty: "Beginner", description: "Momentum oscillator on a 0–100 scale. Over 70 = overbought; under 30 = oversold — but extremes can persist in trends." },
      { id: "macd", name: "MACD", difficulty: "Intermediate", description: "Trend and momentum in one. Histogram crossovers above/below the signal line signal entries and exits." },
      { id: "bollinger", name: "Bollinger Bands", difficulty: "Intermediate", description: "Bands widen in volatility, narrow in consolidation. Upper-band touch in an uptrend is continuation, not reversal." },
      { id: "vwap", name: "VWAP", difficulty: "Intermediate", description: "The institutional day-trading benchmark. Above = bullish bias; below = bearish. Reclaims and failures are key events." },
      { id: "atr", name: "ATR", difficulty: "Intermediate", description: "Average True Range in dollars. Use it to calibrate stop distances and position sizes to current volatility." },
      { id: "adx", name: "ADX / DMI", difficulty: "Advanced", description: "ADX > 25 means trending; < 20 means chop. Filter range and trend regimes before applying your strategy." },
      { id: "stoch", name: "Stochastics", difficulty: "Intermediate", description: "Compares close to range over N bars. Best for overbought/oversold signals in non-trending, range-bound markets." },
      { id: "obv", name: "OBV / Accumulation", difficulty: "Advanced", description: "On-Balance Volume tracks cumulative buying power. OBV diverging from price often leads reversals by weeks." },
      { id: "ichimoku", name: "Ichimoku cloud", difficulty: "Advanced", description: "A complete system in one chart. Price above the cloud is bullish; the cloud acts as dynamic support/resistance." },
      { id: "fib", name: "Fibonacci retracements", difficulty: "Intermediate", description: "38.2%, 50%, and 61.8% are magnetic pullback targets. Combine with volume confirmation for high-probability entries." },
      { id: "pivots", name: "Pivot points", difficulty: "Intermediate", description: "Mathematical support/resistance watched by floor traders and algos. Daily and weekly pivots define intraday range." },
    ],
  },
  {
    id: "patterns", emoji: "🔥", title: "Chart Patterns", showCount: 4,
    lessons: [
      { id: "cup-handle", name: "Cup and handle", difficulty: "Intermediate", description: "U-shaped base + tight handle. Breakout above the handle on heavy volume is the classic buy trigger per O'Neil." },
      { id: "head-shoulders", name: "Head and shoulders", difficulty: "Intermediate", description: "Three peaks; the middle is highest. Neckline break = trend reversal. The inverse version signals a bottoming." },
      { id: "flags", name: "Bull/bear flags", difficulty: "Beginner", description: "Tight pullback after a sharp pole. Represents pause before continuation — buy the break above the flag's upper line." },
      { id: "triangles", name: "Triangles and wedges", difficulty: "Intermediate", description: "Ascending triangles favor upside; descending favor downside. Wedges typically break opposite to the wedge slope." },
      { id: "double-bottom", name: "Double top / double bottom", difficulty: "Beginner", description: "Two tests of the same level that hold. W-shaped bottoms and M-shaped tops are among the most reliable reversals." },
      { id: "vcp", name: "Volatility Contraction Pattern", difficulty: "Advanced", description: "Series of contracting swings in a base — each pullback smaller than the last. Pivot buy on the final tight breakout." },
      { id: "flat-base", name: "Flat base", difficulty: "Intermediate", description: "5–15% range over 5+ weeks after a prior uptrend. One of the most reliable continuation bases in a healthy market." },
      { id: "rounding-bottom", name: "Rounding bottom", difficulty: "Intermediate", description: "Slow, gradual reversal over months. Gentle curve from institutional accumulation; high win rate on the breakout." },
      { id: "ascending-base", name: "Ascending base", difficulty: "Advanced", description: "Three pullbacks each with a higher low — a staircase. Shows persistent demand as weak hands exit at each pullback." },
      { id: "high-tight", name: "High tight flag", difficulty: "Advanced", description: "Stock doubles in 8 weeks, then pulls back just 10–25%. Rarest and most powerful continuation pattern per O'Neil." },
    ],
  },
  {
    id: "systems", emoji: "⚡", title: "Practitioner Systems", showCount: 4,
    lessons: [
      { id: "canslim", name: "CAN SLIM (O'Neil)", difficulty: "Advanced", description: "Seven-factor system: Current earnings, Annual earnings, New catalysts, Supply/demand, Leaders, Institutional sponsorship, Market direction." },
      { id: "minervini", name: "Minervini VCP", difficulty: "Advanced", description: "Stage 2 stocks forming tight, low-volume VCP bases before a volume-driven pivot breakout — Minervini's core methodology." },
      { id: "weinstein", name: "Weinstein Stage 2", difficulty: "Advanced", description: "Four-stage stock cycle. Buy in Stage 2 (advancing above rising 30-week MA). Avoid Stages 3–4 entirely." },
      { id: "turtle", name: "Turtle Donchian", difficulty: "Advanced", description: "Richard Dennis's system: buy 20/55-day channel breakouts, ATR stops, add to winners. Pure trend-following at scale." },
      { id: "darvas", name: "Darvas Box", difficulty: "Intermediate", description: "Buy breakouts from box-shaped bases defined by natural swing highs and lows. Simple, mechanical, and time-tested." },
      { id: "momentum", name: "52-week high momentum", difficulty: "Intermediate", description: "Stocks near 52-week highs tend to outperform 6–12 months forward. 'Nearness to high' is one of finance's most robust factors." },
      { id: "wyckoff", name: "Wyckoff accumulation / distribution", difficulty: "Advanced", description: "Identifies institutional accumulation (spring/test) and distribution (upthrust) phases to project future price targets." },
      { id: "market-breadth", name: "Market breadth reading", difficulty: "Advanced", description: "A/D line, new highs vs. lows, and % above 50-day MA reveal rally health. Breadth divergences precede index tops." },
    ],
  },
];

const DAILY_QUIZZES: DailyQuiz[] = [
  { question: "BTC forms a higher low after -30%. Volume is declining on each pullback. What pattern is forming?", options: ["A) Falling wedge", "B) Cup and handle", "C) Bear flag", "D) Rounding bottom"], correctIndex: 0, explanation: "Declining volume in a falling wedge = diminishing sell pressure. Price breaks above the upper line — often sharply." },
  { question: "NVDA breaks out of a 6-week flat base on 200% above-average volume. What's the signal?", options: ["A) Sell the news", "B) Momentum entry", "C) Wait for pullback", "D) Short it"], correctIndex: 1, explanation: "2x+ volume breakouts are institutional buying — the CAN SLIM momentum entry. Waiting for a pullback often costs you the best gains." },
  { question: "Rising price but RSI is making lower highs. What is this?", options: ["A) RSI confirmation", "B) Bearish divergence", "C) Oversold condition", "D) Breakout signal"], correctIndex: 1, explanation: "Bearish divergence: momentum failing to confirm new price highs signals weakening buying pressure and often precedes a reversal." },
  { question: "Stock consolidates 8 weeks in a tight range after a 3-month uptrend. Volume dries up. What pattern?", options: ["A) Head and shoulders", "B) Distribution", "C) Flat base", "D) Double top"], correctIndex: 2, explanation: "Flat base + volume contraction = institutional quiet accumulation. Buy trigger is a break above the base high on heavy volume." },
  { question: "When is the ideal time to buy according to Weinstein's stage analysis?", options: ["A) Stage 1 (basing)", "B) Stage 2 (advancing)", "C) Stage 3 (topping)", "D) Stage 4 (declining)"], correctIndex: 1, explanation: "Stage 2 — rising above the rising 30-week MA on expanding volume. Stage 1 you wait; Stages 3–4 you sell or short." },
  { question: "Which volume pattern is most bullish during a multi-week base?", options: ["A) Heavy up weeks, light down weeks", "B) Consistent volume throughout", "C) Light up weeks, heavy down weeks", "D) Volume doesn't matter"], correctIndex: 0, explanation: "Heavy volume on up bars, light on down bars = accumulation signature. Institutions are absorbing supply rather than distributing." },
  { question: "A cup and handle formed over 15 weeks. The handle retraces 35%. Valid setup?", options: ["A) Yes — depth doesn't matter", "B) No — handle too deep", "C) Only if RSI is oversold", "D) Yes if volume dried up"], correctIndex: 1, explanation: "A proper handle retraces ≤12–15%. A 35% handle suggests a failed base or distribution — not a controlled consolidation." },
];

// ── localStorage ──────────────────────────────────────────────────────────────

function loadProgress(): TAProgress {
  try { const r = localStorage.getItem("bmg_ta_progress"); if (r) return JSON.parse(r); } catch { /* */ }
  return { completed: ["candle-anatomy", "trend-lines"], streak: 1, lastDate: "" };
}
function saveProgress(p: TAProgress) { try { localStorage.setItem("bmg_ta_progress", JSON.stringify(p)); } catch { /* */ } }
function updateStreak(p: TAProgress): TAProgress {
  const today = new Date().toISOString().slice(0, 10);
  if (p.lastDate === today) return p;
  const yesterday = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
  return { ...p, streak: p.lastDate === yesterday ? p.streak + 1 : 1, lastDate: today };
}

// ── Sub-components ────────────────────────────────────────────────────────────

function DiffBadge({ level }: { level: Lesson["difficulty"] }) {
  const cls = level === "Beginner" ? "bg-emerald-900/40 text-emerald-400" : level === "Intermediate" ? "bg-yellow-900/40 text-yellow-400" : "bg-purple-900/40 text-purple-400";
  return <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded-full", cls)}>{level}</span>;
}

function LessonModal({ lesson, completed, onToggle, onClose }: { lesson: Lesson; completed: boolean; onToggle: () => void; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(2,6,23,0.75)" }} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="bg-zinc-900 border border-zinc-700 rounded-2xl p-6 w-full max-w-md animate-in zoom-in-95 duration-150">
        <div className="flex items-start justify-between mb-3">
          <div><h3 className="font-bold text-white mb-1.5">{lesson.name}</h3><DiffBadge level={lesson.difficulty} /></div>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300 p-1 transition-colors"><X size={16} /></button>
        </div>
        <p className="text-sm text-zinc-300 leading-relaxed mb-5">{lesson.description}</p>
        <button onClick={() => { onToggle(); onClose(); }} className={cn("w-full py-2.5 rounded-xl text-sm font-semibold transition-colors", completed ? "bg-zinc-700 hover:bg-zinc-600 text-zinc-300" : "bg-[#4ade80] hover:bg-[#a3e635] text-zinc-900")}>
          {completed ? "Mark incomplete" : "Mark complete"}
        </button>
      </div>
    </div>
  );
}

function SkillSection({ section, completed, onOpenLesson }: { section: Section; completed: Set<string>; onOpenLesson: (l: Lesson) => void }) {
  const [open, setOpen] = useState(section.defaultExpanded ?? false);
  const [expanded, setExpanded] = useState(false);
  const showCount = section.showCount ?? section.lessons.length;
  const visible = expanded ? section.lessons : section.lessons.slice(0, showCount);
  const doneCount = section.lessons.filter((l) => completed.has(l.id)).length;
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 mb-4">
      <button className="w-full flex items-center justify-between group" onClick={() => setOpen((v) => !v)}>
        <div className="flex items-center gap-3">
          <span className="text-xl">{section.emoji}</span>
          <span className="font-bold text-white">{section.title}</span>
          <span className="text-xs text-zinc-500">{doneCount}/{section.lessons.length}</span>
        </div>
        <div className="flex items-center gap-2">
          {doneCount > 0 && <div className="w-16 h-1.5 bg-zinc-800 rounded-full overflow-hidden"><div className="h-full bg-[#4ade80] rounded-full" style={{ width: `${(doneCount / section.lessons.length) * 100}%` }} /></div>}
          {open ? <ChevronUp size={16} className="text-zinc-500" /> : <ChevronDown size={16} className="text-zinc-500" />}
        </div>
      </button>
      {open && (
        <div className="mt-4 space-y-1">
          {visible.map((lesson) => {
            const done = completed.has(lesson.id);
            return (
              <button key={lesson.id} onClick={() => onOpenLesson(lesson)} className="w-full flex items-center gap-3 p-3 rounded-xl hover:bg-zinc-800/60 transition-colors text-left">
                {done ? <CheckSquare size={15} className="text-emerald-400 flex-shrink-0" /> : <Square size={15} className="text-zinc-600 flex-shrink-0" />}
                <span className={cn("flex-1 text-sm", done ? "text-emerald-400" : "text-zinc-300")}>{lesson.name}</span>
                <DiffBadge level={lesson.difficulty} />
              </button>
            );
          })}
          {section.showCount && section.lessons.length > showCount && (
            <button onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v); }} className="w-full text-xs text-zinc-500 hover:text-zinc-300 transition-colors py-2 text-center">
              {expanded ? "Show less" : `See all ${section.lessons.length} lessons`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function DailyChallenge() {
  const quiz = DAILY_QUIZZES[new Date().getDay() % DAILY_QUIZZES.length];
  const [selected, setSelected] = useState<number | null>(null);
  const revealed = selected !== null;
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 mb-4">
      <div className="flex items-center gap-2 mb-4">
        <Trophy size={15} className="text-yellow-400" />
        <h2 className="font-bold text-white">Daily Setup Quiz</h2>
        <span className="ml-auto text-xs text-zinc-500">{["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][new Date().getDay()]}</span>
      </div>
      <p className="text-sm text-zinc-200 mb-4 leading-relaxed">{quiz.question}</p>
      <div className="space-y-2 mb-4">
        {quiz.options.map((opt, i) => {
          const isCorrect = i === quiz.correctIndex;
          let cls = "border border-zinc-700 text-zinc-300 hover:border-zinc-500 hover:text-white";
          if (revealed) cls = isCorrect ? "border border-emerald-500 bg-emerald-900/30 text-emerald-300" : i === selected ? "border border-red-500 bg-red-900/20 text-red-400" : "border border-zinc-800 text-zinc-600";
          return <button key={i} disabled={revealed} onClick={() => setSelected(i)} className={cn("w-full text-left px-4 py-3 rounded-xl text-sm transition-colors", cls, !revealed && "cursor-pointer")}>{opt}</button>;
        })}
      </div>
      {revealed ? (
        <div className="bg-zinc-800/50 border border-zinc-700 rounded-xl p-4 text-sm text-zinc-300 leading-relaxed">
          <span className={cn("font-semibold mr-2", selected === quiz.correctIndex ? "text-emerald-400" : "text-red-400")}>{selected === quiz.correctIndex ? "Correct!" : "Not quite."}</span>
          {quiz.explanation}
        </div>
      ) : <p className="text-xs text-zinc-600 text-center">Select an answer to reveal the explanation</p>}
    </div>
  );
}

function TAImageReadUnlocked() {
  const [isDragging, setIsDragging] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<ImageAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(async (file: File) => {
    if (!file.type.startsWith("image/")) {
      setError("Please upload an image file (PNG, JPG, WebP)");
      return;
    }
    setPreview(URL.createObjectURL(file));
    setAnalysis(null);
    setError(null);
    setIsAnalyzing(true);
    try {
      const result = await analyzeImage(file);
      setAnalysis(result.analysis);
    } catch {
      setError("Analysis failed — try a clearer chart image");
    } finally {
      setIsAnalyzing(false);
    }
  }, []);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const qualityColor = analysis?.setup_quality === "strong"
    ? "text-lime-400" : analysis?.setup_quality === "moderate"
    ? "text-yellow-400" : "text-red-400";

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 mb-4">
      <div className="flex items-center gap-2 mb-3">
        <Upload size={15} className="text-lime-400" />
        <h2 className="font-bold text-zinc-200">TA Image Read</h2>
        <span className="ml-auto text-[10px] font-bold bg-lime-500/20 text-lime-400 px-2 py-0.5 rounded-full border border-lime-500/30">UNLOCKED</span>
      </div>
      <p className="text-sm text-zinc-500 mb-4 leading-relaxed">Upload a chart screenshot and AI will identify the pattern, support/resistance levels, and entry signals.</p>

      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={cn(
          "relative rounded-xl border-2 border-dashed p-6 flex flex-col items-center gap-3 cursor-pointer transition-colors",
          isDragging ? "border-lime-500/60 bg-lime-500/5" : "border-zinc-700 hover:border-zinc-600 bg-zinc-950/50"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
        />
        {preview ? (
          <img src={preview} alt="Chart preview" className="max-h-48 rounded-lg object-contain" />
        ) : (
          <>
            <Upload size={28} className="text-zinc-600" />
            <p className="text-xs text-zinc-500 font-medium">Drop a chart image here, or click to browse</p>
          </>
        )}
        {isAnalyzing && (
          <div className="absolute inset-0 flex items-center justify-center bg-zinc-900/80 rounded-xl">
            <div className="flex items-center gap-2 text-zinc-300">
              <Loader2 size={16} className="animate-spin" />
              <span className="text-sm font-medium">Analyzing chart…</span>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="mt-3 flex items-center gap-2 text-red-400 text-sm">
          <AlertCircle size={14} />
          {error}
        </div>
      )}

      {analysis && (
        <div className="mt-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {analysis.asset && <span className="text-xs font-semibold text-zinc-300 bg-zinc-800 px-2 py-0.5 rounded">{analysis.asset}</span>}
              {analysis.timeframe && <span className="text-xs text-zinc-500">{analysis.timeframe}</span>}
            </div>
            <span className={cn("text-xs font-bold capitalize", qualityColor)}>
              {analysis.setup_quality} setup
            </span>
          </div>

          <p className="text-sm text-zinc-300 leading-relaxed">{analysis.thesis_summary}</p>

          {analysis.setup_quality_reason && (
            <p className="text-xs text-zinc-500 italic">{analysis.setup_quality_reason}</p>
          )}

          {analysis.key_levels.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-1.5">Key Levels</p>
              <div className="flex flex-wrap gap-1.5">
                {analysis.key_levels.map((l, i) => (
                  <span key={i} className="text-xs bg-zinc-800 text-zinc-300 px-2 py-0.5 rounded border border-zinc-700">
                    {l.label}: ${l.price}
                  </span>
                ))}
              </div>
            </div>
          )}

          {analysis.supporting.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-lime-600 uppercase tracking-wide mb-1">Bullish</p>
              <ul className="space-y-0.5">
                {analysis.supporting.map((s, i) => <li key={i} className="text-xs text-zinc-400 flex gap-1.5"><span className="text-lime-500 flex-shrink-0">+</span>{s}</li>)}
              </ul>
            </div>
          )}

          {analysis.counterarguments.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-red-600 uppercase tracking-wide mb-1">Bearish</p>
              <ul className="space-y-0.5">
                {analysis.counterarguments.map((s, i) => <li key={i} className="text-xs text-zinc-400 flex gap-1.5"><span className="text-red-500 flex-shrink-0">−</span>{s}</li>)}
              </ul>
            </div>
          )}

          {analysis.invalidation && (
            <div className="bg-zinc-950 rounded-xl px-3 py-2 border border-zinc-800">
              <p className="text-xs font-semibold text-zinc-500 mb-0.5">Invalidation</p>
              <p className="text-xs text-zinc-400">{analysis.invalidation}</p>
            </div>
          )}

          <button
            onClick={() => { setAnalysis(null); setPreview(null); setError(null); if (inputRef.current) inputRef.current.value = ""; }}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors underline underline-offset-2"
          >
            Analyze another chart
          </button>
        </div>
      )}
    </div>
  );
}

function LockedFeature() {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 mb-4 relative overflow-hidden">
      <div className="flex items-center gap-2 mb-3">
        <Lock size={15} className="text-zinc-500" />
        <h2 className="font-bold text-zinc-400">TA Image Read</h2>
        <span className="ml-auto text-[10px] font-bold bg-purple-900/40 text-purple-400 px-2 py-0.5 rounded-full border border-purple-800/40">Pro+</span>
      </div>
      <p className="text-sm text-zinc-500 mb-5 leading-relaxed">Upload a chart screenshot and our AI will identify the pattern, support/resistance levels, and entry signals.</p>
      <div className="relative rounded-xl border-2 border-dashed border-zinc-800 bg-zinc-950/50 p-8 flex flex-col items-center gap-3 opacity-40 pointer-events-none select-none">
        <Upload size={28} className="text-zinc-700" />
        <p className="text-xs text-zinc-600 font-medium">Drop a chart image here</p>
      </div>
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="bg-zinc-900/90 border border-zinc-700 rounded-2xl px-5 py-3 flex items-center gap-2 shadow-xl">
          <Lock size={13} className="text-purple-400" />
          <span className="text-sm font-semibold text-zinc-300">Available with Pro+ subscription</span>
        </div>
      </div>
    </div>
  );
}

function ProgressSummary({ completed, streak, onScroll }: { completed: Set<string>; streak: number; onScroll: () => void }) {
  const count = completed.size;
  const pct = Math.round((count / TOTAL_LESSONS) * 100);
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 mb-4">
      <h2 className="font-bold text-white mb-4 flex items-center gap-2"><BookOpen size={15} className="text-[#4ade80]" />Your Progress</h2>
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="bg-zinc-950/60 rounded-xl p-4 text-center">
          <div className="text-2xl font-bold text-[#4ade80]">{streak}</div>
          <div className="text-xs text-zinc-500 mt-0.5 flex items-center justify-center gap-1"><Flame size={10} className="text-orange-400" />day streak</div>
        </div>
        <div className="bg-zinc-950/60 rounded-xl p-4 text-center">
          <div className="text-2xl font-bold text-white">{count}<span className="text-zinc-500 text-base font-normal">/{TOTAL_LESSONS}</span></div>
          <div className="text-xs text-zinc-500 mt-0.5">lessons done</div>
        </div>
      </div>
      <div className="mb-4">
        <div className="flex justify-between text-xs text-zinc-500 mb-1"><span>Overall completion</span><span>{pct}%</span></div>
        <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden"><div className="h-full bg-[#4ade80] rounded-full transition-all duration-500" style={{ width: `${pct}%` }} /></div>
      </div>
      <button onClick={onScroll} className="w-full py-2.5 bg-[#4ade80] hover:bg-[#a3e635] text-zinc-900 font-bold text-sm rounded-xl transition-colors">Continue training</button>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function WorkshopPage() {
  const [progress, setProgress] = useState<TAProgress>(loadProgress);
  const [activeLesson, setActiveLesson] = useState<Lesson | null>(null);
  const treeRef = useRef<HTMLDivElement>(null);
  const isAdmin = useIsAdmin();

  useEffect(() => {
    setProgress((prev) => { const u = updateStreak(prev); saveProgress(u); return u; });
  }, []);

  const completedSet = new Set(progress.completed);

  function toggleLesson(id: string) {
    setProgress((prev) => {
      const set = new Set(prev.completed);
      set.has(id) ? set.delete(id) : set.add(id);
      const updated = { ...prev, completed: Array.from(set) };
      saveProgress(updated);
      return updated;
    });
  }

  return (
    <div className="max-w-3xl mx-auto pb-24 px-4 md:px-0">
      <RetiredBanner />
      {/* Header */}
      <div className="pt-6 pb-8 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">TA Workshop</h1>
          <p className="text-sm text-zinc-400 mt-1">Learn to read charts. Practice with real historical setups.</p>
        </div>
        <button onClick={() => treeRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })} className="flex-shrink-0 bg-[#4ade80] hover:bg-[#a3e635] text-zinc-900 font-bold text-sm px-5 py-2.5 rounded-xl transition-colors">
          Start Training
        </button>
      </div>

      <ProgressSummary completed={completedSet} streak={progress.streak} onScroll={() => treeRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })} />
      <DailyChallenge />

      <div ref={treeRef} className="scroll-mt-4">
        {SECTIONS.map((s) => <SkillSection key={s.id} section={s} completed={completedSet} onOpenLesson={setActiveLesson} />)}
      </div>

      {isAdmin ? <TAImageReadUnlocked /> : <LockedFeature />}

      {activeLesson && (
        <LessonModal lesson={activeLesson} completed={completedSet.has(activeLesson.id)} onToggle={() => toggleLesson(activeLesson.id)} onClose={() => setActiveLesson(null)} />
      )}
    </div>
  );
}

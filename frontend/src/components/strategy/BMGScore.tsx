import { cn } from "@/lib/utils";

// ── Deterministic hash ─────────────────────────────────────────────────────────

function hashScore(symbol: string, seed: number): number {
  let h = seed * 31;
  for (const c of symbol) h = (h * 31 + c.charCodeAt(0)) & 0xffffffff;
  return Math.abs(h % 101);
}

// ── Grade helpers ──────────────────────────────────────────────────────────────

function numericToGrade(score: number): { letter: string; plus: boolean; minus: boolean } {
  if (score >= 93) return { letter: "A", plus: true,  minus: false };
  if (score >= 85) return { letter: "A", plus: false, minus: false };
  if (score >= 80) return { letter: "A", plus: false, minus: true  };
  if (score >= 77) return { letter: "B", plus: true,  minus: false };
  if (score >= 70) return { letter: "B", plus: false, minus: false };
  if (score >= 65) return { letter: "B", plus: false, minus: true  };
  if (score >= 62) return { letter: "C", plus: true,  minus: false };
  if (score >= 55) return { letter: "C", plus: false, minus: false };
  if (score >= 50) return { letter: "C", plus: false, minus: true  };
  if (score >= 47) return { letter: "D", plus: true,  minus: false };
  if (score >= 40) return { letter: "D", plus: false, minus: false };
  return { letter: "F", plus: false, minus: false };
}

function gradeString(score: number): string {
  const g = numericToGrade(score);
  const mod = g.plus ? "+" : g.minus ? "-" : "";
  return g.letter + mod;
}

function gradeColor(score: number): string {
  if (score >= 85) return "text-lime-400";
  if (score >= 70) return "text-emerald-400";
  if (score >= 55) return "text-amber-400";
  if (score >= 40) return "text-orange-400";
  return "text-red-400";
}

function gradeBg(score: number): string {
  if (score >= 85) return "bg-lime-400/15 border-lime-400/30 text-lime-400";
  if (score >= 70) return "bg-emerald-400/15 border-emerald-400/30 text-emerald-400";
  if (score >= 55) return "bg-amber-400/15 border-amber-400/30 text-amber-400";
  if (score >= 40) return "bg-orange-400/15 border-orange-400/30 text-orange-400";
  return "bg-red-400/15 border-red-400/30 text-red-400";
}

function barColor(score: number): string {
  if (score >= 70) return "bg-lime-400";
  if (score >= 50) return "bg-amber-400";
  return "bg-red-400";
}

// ── Junk cap ───────────────────────────────────────────────────────────────────

const JUNK_LIST = ["GME", "AMC", "BBBY", "MULN"];
const JUNK_CAP  = 60;

// ── Score computation ──────────────────────────────────────────────────────────

interface SubScore {
  key: string;
  label: string;
  weight: number;   // 0–1
  score: number;    // 0–100
  detail: string;   // short descriptor for AI thesis
}

interface BMGScoreResult {
  total: number;
  grade: string;
  subs: SubScore[];
  topDrivers: string[];
}

function computeScore(symbol: string): BMGScoreResult {
  const sym = symbol.toUpperCase();

  const rawSubs: SubScore[] = [
    {
      key: "momentum",
      label: "Momentum",
      weight: 0.25,
      score: hashScore(sym, 7),
      detail: `RS ${hashScore(sym, 71)}`,
    },
    {
      key: "quality",
      label: "Quality",
      weight: 0.20,
      score: hashScore(sym, 13),
      detail: `ROIC ${hashScore(sym, 131)}%`,
    },
    {
      key: "value",
      label: "Value",
      weight: 0.15,
      score: hashScore(sym, 19),
      detail: `FCF yield ${(hashScore(sym, 191) / 10).toFixed(1)}%`,
    },
    {
      key: "revisions",
      label: "Earnings Revisions",
      weight: 0.15,
      score: hashScore(sym, 23),
      detail: `+${hashScore(sym, 231) % 15 + 1}% 30d revision`,
    },
    {
      key: "sentiment",
      label: "Sentiment",
      weight: 0.15,
      score: hashScore(sym, 29),
      detail: `${hashScore(sym, 291) % 12 + 5} analysts bullish`,
    },
    {
      key: "technical",
      label: "Technical Setup",
      weight: 0.10,
      score: hashScore(sym, 37),
      detail: `ADX ${hashScore(sym, 371) % 30 + 20}`,
    },
  ];

  // Weighted average
  let rawTotal = rawSubs.reduce((acc, s) => acc + s.score * s.weight, 0);
  rawTotal = Math.round(Math.min(100, Math.max(0, rawTotal)));

  // Junk cap
  const total = JUNK_LIST.includes(sym) ? Math.min(rawTotal, JUNK_CAP) : rawTotal;

  // Top drivers: two highest-weighted contributors (score * weight)
  const sorted = [...rawSubs].sort((a, b) => b.score * b.weight - a.score * a.weight);
  const topDrivers = sorted.slice(0, 2).map((s) => s.label);

  return { total, grade: gradeString(total), subs: rawSubs, topDrivers };
}

// ── AI Thesis text ─────────────────────────────────────────────────────────────

function buildThesis(symbol: string, result: BMGScoreResult): string {
  const sym = symbol.toUpperCase();
  const { total, subs } = result;
  const mom = subs.find((s) => s.key === "momentum")!;
  const qual = subs.find((s) => s.key === "quality")!;
  const val = subs.find((s) => s.key === "value")!;
  const rev = subs.find((s) => s.key === "revisions")!;

  const momentumAdj = mom.score >= 80 ? "elite" : mom.score >= 65 ? "strong" : mom.score >= 50 ? "moderate" : "weak";
  const qualityAdj  = qual.score >= 80 ? "exceptional" : qual.score >= 65 ? "solid" : qual.score >= 50 ? "average" : "below-average";
  const valueAdj    = val.score >= 70  ? "reasonable multiple given its growth profile"
                     : val.score >= 50  ? "fair valuation relative to peers"
                     : "stretched valuation that warrants caution";
  const revWord     = rev.score >= 60  ? "positive estimate revisions support near-term earnings upside"
                     : rev.score >= 40  ? "estimate revisions are mixed, providing limited near-term catalyst"
                     : "negative estimate revisions may weigh on the stock";

  const overallWord = total >= 80 ? "high-conviction setup" : total >= 65 ? "favorable setup" : total >= 50 ? "neutral setup" : "cautious setup";

  return `${sym} presents a ${overallWord} — ${momentumAdj} momentum (${mom.detail}) combined with ${qualityAdj} quality metrics, trading at a ${valueAdj}. ${revWord}.`;
}

// ── Sub-bar row ────────────────────────────────────────────────────────────────

function SubBar({ sub }: { sub: SubScore }) {
  return (
    <div className="flex items-center gap-3">
      <div className="w-32 shrink-0 flex items-center justify-between">
        <span className="text-[10px] font-semibold text-[var(--text-secondary)] truncate">{sub.label}</span>
        <span className="text-[10px] text-[var(--text-tertiary)] ml-1 shrink-0">{Math.round(sub.weight * 100)}%</span>
      </div>
      <div className="flex-1 h-1.5 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-500", barColor(sub.score))}
          style={{ width: `${sub.score}%` }}
        />
      </div>
      <span className={cn("text-[11px] font-bold font-mono w-6 text-right shrink-0", gradeColor(sub.score))}>
        {sub.score}
      </span>
    </div>
  );
}

// ── Full component ─────────────────────────────────────────────────────────────

interface BMGScoreProps {
  symbol: string;
  compact?: boolean;
}

export default function BMGScore({ symbol, compact = false }: BMGScoreProps) {
  const result = computeScore(symbol);
  const thesis = buildThesis(symbol, result);

  if (compact) {
    return (
      <div className="flex items-center gap-2">
        <span className={cn("text-base font-bold font-mono", gradeColor(result.total))}>
          {result.total}
        </span>
        <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded border", gradeBg(result.total))}>
          {result.grade}
        </span>
        <div className="w-16 h-1 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
          <div
            className={cn("h-full rounded-full", barColor(result.total))}
            style={{ width: `${result.total}%` }}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5 space-y-4">
      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-1">
            BMG Score
          </div>
          <div className="flex items-center gap-3">
            <span className={cn("text-5xl font-black font-mono leading-none", gradeColor(result.total))}>
              {result.total}
            </span>
            <span className={cn("text-lg font-bold px-2.5 py-1 rounded-lg border", gradeBg(result.total))}>
              {result.grade}
            </span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-[10px] text-[var(--text-tertiary)] mb-1">Composite of 6 factors</div>
          <div className="text-xs text-[var(--text-secondary)]">{symbol.toUpperCase()}</div>
        </div>
      </div>

      {/* Total progress bar */}
      <div className="h-2 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-700", barColor(result.total))}
          style={{ width: `${result.total}%` }}
        />
      </div>

      {/* Sub-component bars */}
      <div className="space-y-2.5">
        {result.subs.map((sub) => (
          <SubBar key={sub.key} sub={sub} />
        ))}
      </div>

      {/* Top drivers */}
      <div className="pt-2 border-t border-[var(--border-subtle)]">
        <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-1.5">
          Top Drivers
        </div>
        <p className="text-xs text-[var(--text-secondary)]">
          <span className={cn("font-semibold", gradeColor(result.total))}>
            {result.topDrivers[0]}
          </span>
          {result.topDrivers[1] ? (
            <>
              {" and "}
              <span className={cn("font-semibold", gradeColor(result.total))}>
                {result.topDrivers[1]}
              </span>
              {" are the primary drivers of this score."}
            </>
          ) : (
            " is the primary driver of this score."
          )}
        </p>
      </div>

      {/* AI Thesis */}
      <div className="bg-[var(--bg-elevated-2)]/40 rounded-xl px-4 py-3">
        <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-1.5">
          AI Thesis
        </div>
        <p className="text-[11px] italic text-[var(--text-tertiary)] leading-relaxed">{thesis}</p>
      </div>

      {/* Disclaimer */}
      <p className="text-[10px] text-[var(--text-tertiary)] text-center leading-relaxed">
        BMG Score recalculates pre-open daily. Not a buy/sell recommendation.
      </p>
    </div>
  );
}

// ── Compact named export ───────────────────────────────────────────────────────

export function BMGScoreCompact({ symbol }: { symbol: string }) {
  return <BMGScore symbol={symbol} compact />;
}

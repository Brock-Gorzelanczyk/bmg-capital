import { useState } from "react";
import { Bot, TrendingUp, TrendingDown, Grid3X3, BarChart3 } from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { cn } from "@/lib/utils";

// ── Data ───────────────────────────────────────────────────────────────────────

const SECTORS = [
  { name: "Technology",        pct1d: 1.84,  pct5d: 3.12, pct1m: 6.41, pct3m: 12.8, pctYtd: 18.4, cap: "$14.2T", flex: 22 },
  { name: "Financials",        pct1d: 0.97,  pct5d: 1.44, pct1m: 2.81, pct3m: 7.2,  pctYtd: 11.3, cap: "$8.1T",  flex: 14 },
  { name: "Healthcare",        pct1d: -0.31, pct5d: -0.88,pct1m: -1.2, pct3m: -2.4, pctYtd: 3.1,  cap: "$6.8T",  flex: 12 },
  { name: "Consumer Disc.",    pct1d: 1.23,  pct5d: 2.01, pct1m: 4.55, pct3m: 9.1,  pctYtd: 14.6, cap: "$5.4T",  flex: 9  },
  { name: "Industrials",       pct1d: 0.44,  pct5d: 0.92, pct1m: 2.10, pct3m: 5.8,  pctYtd: 9.7,  cap: "$5.1T",  flex: 9  },
  { name: "Communication",     pct1d: 2.11,  pct5d: 3.44, pct1m: 7.22, pct3m: 14.1, pctYtd: 21.2, cap: "$4.8T",  flex: 8  },
  { name: "Consumer Staples",  pct1d: -0.18, pct5d: -0.31,pct1m: 0.44, pct3m: 1.2,  pctYtd: 4.8,  cap: "$4.2T",  flex: 7  },
  { name: "Energy",            pct1d: -0.87, pct5d: -2.14,pct1m: -3.88,pct3m: -8.1, pctYtd: -5.4, cap: "$3.6T",  flex: 6  },
  { name: "Utilities",         pct1d: -0.52, pct5d: -0.74,pct1m: 1.22, pct3m: 3.4,  pctYtd: 6.1,  cap: "$2.9T",  flex: 5  },
  { name: "Materials",         pct1d: 0.66,  pct5d: 1.12, pct1m: 2.44, pct3m: 4.8,  pctYtd: 7.2,  cap: "$2.3T",  flex: 4  },
  { name: "Real Estate",       pct1d: 0.22,  pct5d: 0.41, pct1m: 1.84, pct3m: 3.1,  pctYtd: 5.9,  cap: "$1.8T",  flex: 4  },
];

const SP500_STOCKS = [
  { t: "NVDA",  pct: 3.2  }, { t: "MSFT",  pct: 1.1  }, { t: "AAPL",  pct: 0.8  }, { t: "GOOGL", pct: 2.4  },
  { t: "META",  pct: 2.9  }, { t: "AMZN",  pct: 1.5  }, { t: "TSLA",  pct: 4.1  }, { t: "NFLX",  pct: 2.2  },
  { t: "AMD",   pct: 2.8  }, { t: "AVGO",  pct: 1.9  }, { t: "JPM",   pct: 1.1  }, { t: "BAC",   pct: 0.7  },
  { t: "GS",    pct: 1.4  }, { t: "MS",    pct: 0.9  }, { t: "V",     pct: 0.6  }, { t: "UNH",   pct: -0.4 },
  { t: "LLY",   pct: -0.2 }, { t: "JNJ",   pct: -0.1 }, { t: "PFE",   pct: -1.2 }, { t: "ABBV",  pct: 0.3  },
  { t: "XOM",   pct: -0.9 }, { t: "CVX",   pct: -0.7 }, { t: "NEE",   pct: -0.5 }, { t: "DUK",   pct: -0.3 },
  { t: "AMT",   pct: 0.2  }, { t: "PLD",   pct: 0.4  }, { t: "SPG",   pct: 0.1  }, { t: "CAT",   pct: 0.5  },
  { t: "DE",    pct: 0.3  }, { t: "BA",    pct: -0.8 },
];

const GAINERS = [
  { ticker: "TSLA", sector: "Tech", pct: 4.1 },
  { ticker: "NVDA", sector: "Tech", pct: 3.2 },
  { ticker: "COIN", sector: "Fin",  pct: 3.0 },
  { ticker: "META", sector: "Comm", pct: 2.9 },
  { ticker: "AMD",  sector: "Tech", pct: 2.8 },
];

const LOSERS = [
  { ticker: "PFE",  sector: "HC",   pct: -1.2 },
  { ticker: "XOM",  sector: "Enrg", pct: -0.9 },
  { ticker: "CVX",  sector: "Enrg", pct: -0.7 },
  { ticker: "BA",   sector: "Ind",  pct: -0.8 },
  { ticker: "NEE",  sector: "Util", pct: -0.5 },
];

const PERIODS = ["1D", "5D", "1M", "3M", "YTD"] as const;
type Period = typeof PERIODS[number];

// ── Helpers ───────────────────────────────────────────────────────────────────

function pctToColor(pct: number): string {
  if (pct >= 2)   return "#14532d";
  if (pct >= 1)   return "#166534";
  if (pct >= 0.5) return "#15803d";
  if (pct >= 0.1) return "#22c55e44";
  if (pct >= 0)   return "#22c55e22";
  if (pct >= -0.1)return "#ef444422";
  if (pct >= -0.5)return "#dc262644";
  if (pct >= -1)  return "#dc2626";
  if (pct >= -2)  return "#b91c1c";
  return "#991b1b";
}

function pctFg(pct: number): string {
  return Math.abs(pct) >= 0.5 ? "#fff" : pct >= 0 ? "#22c55e" : "#ef4444";
}

function getSectorPct(s: typeof SECTORS[0], period: Period) {
  if (period === "1D") return s.pct1d;
  if (period === "5D") return s.pct5d;
  if (period === "1M") return s.pct1m;
  if (period === "3M") return s.pct3m;
  return s.pctYtd;
}

function PctBadge({ pct }: { pct: number }) {
  const pos = pct >= 0;
  return (
    <span className={cn("text-xs font-mono font-bold", pos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
      {pos ? "▲" : "▼"} {Math.abs(pct).toFixed(2)}%
    </span>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function HeatMapPage() {
  const [period, setPeriod] = useState<Period>("1D");
  const [view, setView] = useState<"sectors" | "sp500">("sectors");
  const [aiOpen, setAiOpen] = useState(false);

  return (
    <div className="max-w-[1600px] mx-auto pb-20 md:pb-6 space-y-5">

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Market Heat Map</h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">
            {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })} · S&P 500 performance by sector
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Period selector */}
          <div className="flex gap-1 bg-[var(--bg-elevated-2)] p-1 rounded-xl">
            {PERIODS.map((p) => (
              <button key={p} onClick={() => setPeriod(p)}
                className={cn("px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer",
                  period === p ? "bg-[var(--bg-elevated)] text-[var(--text-primary)] shadow-sm" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
                )}>{p}</button>
            ))}
          </div>
          {/* View toggle */}
          <div className="flex gap-1 bg-[var(--bg-elevated-2)] p-1 rounded-xl">
            <button onClick={() => setView("sectors")}
              className={cn("px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5",
                view === "sectors" ? "bg-[var(--bg-elevated)] text-[var(--text-primary)] shadow-sm" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
              )}><BarChart3 size={11} /> Sectors</button>
            <button onClick={() => setView("sp500")}
              className={cn("px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5",
                view === "sp500" ? "bg-[var(--bg-elevated)] text-[var(--text-primary)] shadow-sm" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
              )}><Grid3X3 size={11} /> S&P 500</button>
          </div>
          <button onClick={() => setAiOpen(true)}
            className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors">
            <Bot size={12} /> Ask AI
          </button>
        </div>
      </div>

      {/* Breadth Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "VIX", value: "18.42", note: "Low volatility", color: "text-[var(--accent-positive)]" },
          { label: "Put/Call Ratio", value: "0.84", note: "Bullish sentiment", color: "text-[var(--accent-positive)]" },
          { label: "Advancing", value: "312", note: "of 500 stocks", color: "text-[var(--accent-positive)]" },
          { label: "Declining", value: "188", note: "of 500 stocks", color: "text-[var(--accent-negative)]" },
        ].map((s) => (
          <div key={s.label} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3">
            <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-1">{s.label}</div>
            <div className={cn("text-2xl font-bold font-mono", s.color)}>{s.value}</div>
            <div className="text-[10px] text-[var(--text-tertiary)] mt-0.5">{s.note}</div>
          </div>
        ))}
      </div>

      {/* Main heat map */}
      {view === "sectors" ? (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden p-4">
          <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-3">S&P 500 Sectors — {period} Performance</div>
          <div className="flex flex-wrap gap-2" style={{ minHeight: 220 }}>
            {SECTORS.map((s) => {
              const pct = getSectorPct(s, period);
              const bg = pctToColor(pct);
              const fg = pctFg(pct);
              return (
                <div key={s.name}
                  className="rounded-xl flex flex-col items-center justify-center p-3 cursor-pointer hover:opacity-90 transition-all border border-white/5 hover:border-white/20"
                  style={{ backgroundColor: bg, flex: s.flex, minWidth: 90, minHeight: 90 }}
                >
                  <div className="text-[11px] font-bold text-center leading-tight mb-1" style={{ color: fg }}>{s.name}</div>
                  <div className="text-base font-bold font-mono" style={{ color: fg }}>
                    {pct >= 0 ? "+" : ""}{pct.toFixed(2)}%
                  </div>
                  <div className="text-[9px] mt-1 opacity-70" style={{ color: fg }}>{s.cap}</div>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden p-4">
          <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-3">S&P 500 Individual Stocks — 1D Performance</div>
          <div className="flex flex-wrap gap-1.5">
            {SP500_STOCKS.map((s) => {
              const bg = pctToColor(s.pct);
              const fg = Math.abs(s.pct) >= 0.5 ? "#fff" : s.pct >= 0 ? "#86efac" : "#fca5a5";
              return (
                <div key={s.t}
                  className="rounded-lg flex flex-col items-center justify-center cursor-pointer hover:opacity-90 transition-all border border-white/5"
                  style={{ backgroundColor: bg, width: 72, height: 44 }}
                >
                  <div className="text-[10px] font-bold" style={{ color: fg }}>{s.t}</div>
                  <div className="text-[9px] font-mono" style={{ color: fg }}>
                    {s.pct >= 0 ? "+" : ""}{s.pct.toFixed(1)}%
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Lower grid: breadth + movers */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Breadth indicators */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-4 space-y-4">
          <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">Market Breadth</div>
          {[
            { label: "% Above 200 MA", val: 68, color: "#22c55e" },
            { label: "% Above 50 MA",  val: 54, color: "#22c55e" },
            { label: "% Above 20 MA",  val: 41, color: "#f59e0b" },
          ].map((b) => (
            <div key={b.label}>
              <div className="flex justify-between mb-1">
                <span className="text-xs text-[var(--text-secondary)]">{b.label}</span>
                <span className="text-xs font-mono font-bold" style={{ color: b.color }}>{b.val}%</span>
              </div>
              <div className="h-1.5 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${b.val}%`, backgroundColor: b.color }} />
              </div>
            </div>
          ))}
          <div className="grid grid-cols-2 gap-3 pt-2 border-t border-[var(--border-subtle)]">
            <div>
              <div className="text-[10px] text-[var(--text-tertiary)]">New 52W Highs</div>
              <div className="text-lg font-bold font-mono text-[var(--accent-positive)]">47</div>
            </div>
            <div>
              <div className="text-[10px] text-[var(--text-tertiary)]">New 52W Lows</div>
              <div className="text-lg font-bold font-mono text-[var(--accent-negative)]">12</div>
            </div>
            <div>
              <div className="text-[10px] text-[var(--text-tertiary)]">McClellan Osc</div>
              <div className="text-lg font-bold font-mono text-[var(--accent-positive)]">+45</div>
            </div>
            <div>
              <div className="text-[10px] text-[var(--text-tertiary)]">AAII Bull %</div>
              <div className="text-lg font-bold font-mono text-[var(--accent-positive)]">44.2%</div>
            </div>
          </div>
        </div>

        {/* Top Gainers */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={13} className="text-[var(--accent-positive)]" />
            <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">Top Gainers</div>
          </div>
          <div className="space-y-2">
            {GAINERS.map((g) => (
              <div key={g.ticker} className="flex items-center justify-between py-1.5 border-b border-[var(--border-subtle)] last:border-0">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg bg-[var(--accent-positive)]/10 border border-[var(--accent-positive)]/20 flex items-center justify-center text-[10px] font-bold text-[var(--accent-positive)]">
                    {g.ticker.slice(0, 2)}
                  </div>
                  <div>
                    <div className="text-sm font-bold text-[var(--text-primary)]">{g.ticker}</div>
                    <div className="text-[10px] text-[var(--text-tertiary)]">{g.sector}</div>
                  </div>
                </div>
                <span className="text-sm font-bold font-mono text-[var(--accent-positive)]">+{g.pct.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>

        {/* Top Losers */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingDown size={13} className="text-[var(--accent-negative)]" />
            <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">Top Losers</div>
          </div>
          <div className="space-y-2">
            {LOSERS.map((g) => (
              <div key={g.ticker} className="flex items-center justify-between py-1.5 border-b border-[var(--border-subtle)] last:border-0">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg bg-[var(--accent-negative)]/10 border border-[var(--accent-negative)]/20 flex items-center justify-center text-[10px] font-bold text-[var(--accent-negative)]">
                    {g.ticker.slice(0, 2)}
                  </div>
                  <div>
                    <div className="text-sm font-bold text-[var(--text-primary)]">{g.ticker}</div>
                    <div className="text-[10px] text-[var(--text-tertiary)]">{g.sector}</div>
                  </div>
                </div>
                <span className="text-sm font-bold font-mono text-[var(--accent-negative)]">{g.pct.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Sector table */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-[var(--border-subtle)]">
          <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">Sector Performance Table</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[var(--border-subtle)]">
                {["Sector", "1D", "5D", "1M", "3M", "YTD", "Market Cap"].map((h) => (
                  <th key={h} className={cn("px-4 py-2.5 font-semibold text-[var(--text-tertiary)] tracking-wider", h === "Sector" ? "text-left" : "text-right")}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {SECTORS.map((s, i) => (
                <tr key={s.name} className={i % 2 === 0 ? "bg-[var(--bg-elevated-2)]/40" : ""}>
                  <td className="px-4 py-2.5 font-semibold text-[var(--text-primary)]">{s.name}</td>
                  {[s.pct1d, s.pct5d, s.pct1m, s.pct3m, s.pctYtd].map((p, j) => (
                    <td key={j} className={cn("px-4 py-2.5 text-right font-mono font-bold", p >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                      {p >= 0 ? "+" : ""}{p.toFixed(2)}%
                    </td>
                  ))}
                  <td className="px-4 py-2.5 text-right text-[var(--text-tertiary)]">{s.cap}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title="Ask BMG about Markets"
        context="Market Heat Map — sector and stock performance, market breadth indicators"
        suggestedQuestions={[
          "Which sectors are leading the market today?",
          "What does the McClellan Oscillator tell us?",
          "How do I interpret put/call ratio for market direction?",
          "What happens when fewer stocks make new 52-week highs?",
          "Which sectors historically lead in rate cut cycles?",
        ]}
      />
    </div>
  );
}

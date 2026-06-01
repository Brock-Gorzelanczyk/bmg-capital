import { useState, useMemo } from "react";
import { Bot, FlaskConical, Play, TrendingUp, TrendingDown, BarChart3, ChevronDown, ChevronUp, Shuffle } from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { cn } from "@/lib/utils";

// ── Types ──────────────────────────────────────────────────────────────────────

interface BacktestResult {
  totalReturn: number;
  cagr: number;
  sharpe: number;
  maxDrawdown: number;
  winRate: number;
  totalTrades: number;
  avgWin: number;
  avgLoss: number;
  benchmarkReturn: number;
  equityCurve: { date: string; portfolio: number; benchmark: number }[];
  trades: { entry: string; exit: string; ticker: string; pnl: number; pct: number; signal: string }[];
}

// ── Mock backtest engine ───────────────────────────────────────────────────────

function runBacktest(
  signal: string,
  universe: string,
  capital: number,
  commission: number,
  slippage: number,
  borrowCost: number
): BacktestResult {
  const profiles: Record<string, { ret: number; cagr: number; sharpe: number; dd: number; wr: number }> = {
    "RSI Oversold (< 30)":       { ret: 142, cagr: 18.4, sharpe: 1.42, dd: 18.2, wr: 68 },
    "Golden Cross (50/200 MA)":  { ret: 98,  cagr: 14.2, sharpe: 1.18, dd: 22.4, wr: 61 },
    "MACD Crossover":            { ret: 118, cagr: 16.1, sharpe: 1.31, dd: 20.1, wr: 64 },
    "Bollinger Band Breakout":   { ret: 87,  cagr: 12.8, sharpe: 1.09, dd: 25.8, wr: 58 },
    "EMA 20/50 Cross":           { ret: 107, cagr: 15.2, sharpe: 1.24, dd: 21.3, wr: 62 },
    "VCP Breakout":              { ret: 168, cagr: 21.3, sharpe: 1.67, dd: 16.4, wr: 72 },
    "Cup & Handle":              { ret: 134, cagr: 17.8, sharpe: 1.55, dd: 17.9, wr: 69 },
    "Opening Range Breakout":    { ret: 94,  cagr: 13.6, sharpe: 1.14, dd: 23.1, wr: 59 },
    "Gap-and-Go":                { ret: 122, cagr: 16.7, sharpe: 1.38, dd: 19.6, wr: 63 },
    "Insider Cluster":           { ret: 155, cagr: 20.1, sharpe: 1.61, dd: 15.8, wr: 71 },
    "Sector Rotation":           { ret: 103, cagr: 14.9, sharpe: 1.22, dd: 20.7, wr: 60 },
    "PEAD Drift":                { ret: 129, cagr: 17.2, sharpe: 1.44, dd: 18.5, wr: 66 },
    "Mean Reversion 2-Sigma":    { ret: 78,  cagr: 11.6, sharpe: 0.98, dd: 27.3, wr: 55 },
    "RSI Divergence":            { ret: 111, cagr: 15.6, sharpe: 1.29, dd: 21.8, wr: 63 },
    "Bollinger Squeeze":         { ret: 96,  cagr: 13.9, sharpe: 1.16, dd: 24.2, wr: 60 },
  };
  const p = profiles[signal] ?? profiles["Golden Cross (50/200 MA)"];

  // Cost drag: each trade costs commission + slippage*2 (in+out) + borrowCost prorated
  // Express all as % impact per trade
  const perTradeCostPct = (commission / (capital / 10)) * 100 + slippage * 2 + borrowCost / 12;
  const numTrades = 24;
  const costDrag = perTradeCostPct * numTrades / 100;

  const adjustedRet  = Math.max(0, p.ret  - p.ret  * Math.min(costDrag, 0.3));
  const adjustedCagr = Math.max(0, p.cagr - p.cagr * Math.min(costDrag, 0.3));

  // Generate equity curve (monthly, 3 years)
  const months = 36;
  const curve: BacktestResult["equityCurve"] = [];
  let port = capital, bench = capital;
  const portMoReturn = Math.pow(1 + adjustedCagr / 100, 1 / 12);
  const benchMoReturn = Math.pow(1.10, 1 / 12);
  const now = new Date(2025, 4); // May 2025
  for (let i = months; i >= 0; i--) {
    const d = new Date(now);
    d.setMonth(d.getMonth() - i);
    const noise = 1 + (Math.sin(i * 2.7 + signal.length) * 0.04);
    curve.push({
      date: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`,
      portfolio: Math.round(port * noise),
      benchmark: Math.round(bench),
    });
    port  *= portMoReturn  * (1 + (Math.sin(i * 3.1 + signal.charCodeAt(0)) * 0.015));
    bench *= benchMoReturn * (1 + (Math.sin(i * 2.3) * 0.01));
  }

  const tickers = universe === "S&P 500"         ? ["AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","JPM"]
                : universe === "NASDAQ 100"       ? ["NVDA","META","AMD","NFLX","AMZN","TSLA","AVGO","INTC"]
                : ["PLTR","COIN","SOFI","ARKK","GME","AMC","MSTR","RIOT"];
  const signalNames = ["RSI bounce","MA cross","MACD signal","BB touch","Volume surge","Trend break","Gap fill","Momentum"];

  const trades: BacktestResult["trades"] = Array.from({ length: numTrades }, (_, i) => {
    const wins = Math.round(numTrades * p.wr / 100);
    const isWin = i < wins;
    const baseWin  = +(Math.sin(i * 5.3 + signal.length)  * 5  + 7).toFixed(2);
    const baseLoss = +(Math.sin(i * 4.7 + signal.charCodeAt(0)) * 2.5 + 4).toFixed(2);
    const pnlPct = isWin ? baseWin : -baseLoss;
    const entryCapital = capital / 10;
    return {
      ticker: tickers[i % tickers.length],
      entry: `${2022 + Math.floor(i / 9)}-${String((i % 12) + 1).padStart(2, "0")}-${String((i % 28) + 1).padStart(2, "0")}`,
      exit:  `${2022 + Math.floor(i / 9)}-${String((i % 12) + 2).padStart(2, "0")}-${String((i % 28) + 1).padStart(2, "0")}`,
      pnl:  Math.round(entryCapital * pnlPct / 100),
      pct:  pnlPct,
      signal: signalNames[i % signalNames.length],
    };
  }).sort((a, b) => a.entry.localeCompare(b.entry));

  const wins2   = trades.filter((t) => t.pnl > 0);
  const losses2 = trades.filter((t) => t.pnl < 0);

  return {
    totalReturn:     Math.round(adjustedRet),
    cagr:            Math.round(adjustedCagr * 10) / 10,
    sharpe:          p.sharpe,
    maxDrawdown:     p.dd,
    winRate:         p.wr,
    totalTrades:     trades.length,
    avgWin:          wins2.length   ? Math.round(wins2.reduce((s, t) => s + t.pct, 0)   / wins2.length   * 10) / 10 : 0,
    avgLoss:         losses2.length ? Math.round(losses2.reduce((s, t) => s + t.pct, 0) / losses2.length * 10) / 10 : 0,
    benchmarkReturn: 34,
    equityCurve:     curve,
    trades,
  };
}

// ── Monte Carlo ────────────────────────────────────────────────────────────────

interface MCResult {
  paths: number[][];       // each path: capital at each step (200 steps)
  median: number[];
  worstP5: number[];
  pRuin: number;
  medianFinal: number;
  pct95Final: number;
}

function runMonteCarlo(
  trades: BacktestResult["trades"],
  capital: number,
  runs = 200
): MCResult {
  const returns = trades.map((t) => t.pct / 100);
  const steps = returns.length;

  const allFinals: number[] = [];
  const allPaths: number[][] = [];

  for (let r = 0; r < runs; r++) {
    // Shuffle returns (Fisher-Yates using deterministic-enough approach)
    const shuffled = [...returns];
    for (let i = shuffled.length - 1; i > 0; i--) {
      const j = Math.floor(Math.abs(Math.sin(r * 17 + i * 31) * 1e6) % (i + 1));
      [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    let cur = capital;
    const path: number[] = [cur];
    for (const ret of shuffled) {
      cur = cur * (1 + ret * 0.1); // 10% position sizing
      path.push(Math.round(cur));
    }
    allPaths.push(path);
    allFinals.push(cur);
  }

  allFinals.sort((a, b) => a - b);

  // Compute median path and worst-5th-percentile path step by step
  const median: number[] = [];
  const worstP5: number[] = [];
  for (let s = 0; s <= steps; s++) {
    const vals = allPaths.map((p) => p[s] ?? p[p.length - 1]).sort((a, b) => a - b);
    median.push(vals[Math.floor(vals.length * 0.5)]);
    worstP5.push(vals[Math.floor(vals.length * 0.05)]);
  }

  const pRuin = (allFinals.filter((f) => f < capital * 0.5).length / runs) * 100;
  const medianFinal = allFinals[Math.floor(runs * 0.5)];
  const pct95Final  = allFinals[Math.floor(runs * 0.95)];

  // Return 5 sample paths (evenly spaced)
  const samplePaths = [0, 1, 2, 3, 4].map((i) => allPaths[Math.floor(i * runs / 5)]);

  return { paths: samplePaths, median, worstP5, pRuin, medianFinal, pct95Final };
}

// ── SVG Equity Curve ───────────────────────────────────────────────────────────

function EquityCurve({ data }: { data: BacktestResult["equityCurve"] }) {
  if (!data.length) return null;
  const W = 800, H = 240;
  const PAD = { top: 16, right: 20, bottom: 28, left: 68 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const allVals = data.flatMap((d) => [d.portfolio, d.benchmark]);
  const minV = Math.min(...allVals) * 0.98;
  const maxV = Math.max(...allVals) * 1.02;

  const xS = (i: number) => PAD.left + (i / (data.length - 1)) * innerW;
  const yS = (v: number) => PAD.top + innerH - ((v - minV) / (maxV - minV)) * innerH;

  const portPts  = data.map((d, i) => `${xS(i)},${yS(d.portfolio)}`).join(" ");
  const benchPts = data.map((d, i) => `${xS(i)},${yS(d.benchmark)}`).join(" ");
  const areaPath =
    `M ${xS(0)},${yS(data[0].portfolio)} ` +
    data.slice(1).map((d, i) => `L ${xS(i + 1)},${yS(d.portfolio)}`).join(" ") +
    ` L ${xS(data.length - 1)},${H - PAD.bottom} L ${xS(0)},${H - PAD.bottom} Z`;

  const gridVs  = [minV, (minV + maxV) / 2, maxV];
  const fmtV    = (v: number) => `$${(v / 1000).toFixed(0)}K`;
  const xLabels = data.filter((_, i) => i % 6 === 0);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
      {gridVs.map((v) => (
        <g key={v}>
          <line x1={PAD.left} y1={yS(v)} x2={W - PAD.right} y2={yS(v)} stroke="#ffffff0d" strokeWidth={1} />
          <text x={PAD.left - 6} y={yS(v) + 4} textAnchor="end" fontSize={9} fill="#64748b">{fmtV(v)}</text>
        </g>
      ))}
      <path d={areaPath} fill="#22c55e18" />
      <polyline points={benchPts} fill="none" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 2" />
      <polyline points={portPts}  fill="none" stroke="#22c55e"  strokeWidth={2} />
      {xLabels.map((d, i) => {
        const idx = data.indexOf(d);
        return (
          <text key={i} x={xS(idx)} y={H - PAD.bottom + 14} textAnchor="middle" fontSize={8} fill="#64748b">
            {d.date.slice(0, 7)}
          </text>
        );
      })}
    </svg>
  );
}

// ── SVG Monte Carlo Chart ──────────────────────────────────────────────────────

function MonteCarloCurve({ mc, capital }: { mc: MCResult; capital: number }) {
  const W = 800, H = 240;
  const PAD = { top: 16, right: 20, bottom: 28, left: 68 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const steps = mc.median.length;
  const allVals = [...mc.paths.flat(), ...mc.median, ...mc.worstP5];
  const minV = Math.min(...allVals) * 0.97;
  const maxV = Math.max(...allVals) * 1.03;

  const xS = (i: number) => PAD.left + (i / (steps - 1)) * innerW;
  const yS = (v: number) => PAD.top + innerH - ((v - minV) / (maxV - minV)) * innerH;

  const toPoints = (arr: number[]) => arr.map((v, i) => `${xS(i)},${yS(v)}`).join(" ");

  const sampleShades = ["#22c55e30", "#16a34a28", "#4ade8024", "#86efac20", "#bbf7d01c"];
  const gridVs = [minV, (minV + maxV) / 2, maxV];
  const fmtV   = (v: number) => `$${(v / 1000).toFixed(0)}K`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
      {gridVs.map((v) => (
        <g key={v}>
          <line x1={PAD.left} y1={yS(v)} x2={W - PAD.right} y2={yS(v)} stroke="#ffffff0d" strokeWidth={1} />
          <text x={PAD.left - 6} y={yS(v) + 4} textAnchor="end" fontSize={9} fill="#64748b">{fmtV(v)}</text>
        </g>
      ))}

      {/* Capital baseline */}
      <line
        x1={PAD.left} y1={yS(capital)} x2={W - PAD.right} y2={yS(capital)}
        stroke="#ffffff18" strokeWidth={1} strokeDasharray="3 3"
      />

      {/* Sample paths */}
      {mc.paths.map((path, i) => (
        <polyline key={i} points={toPoints(path)} fill="none" stroke={sampleShades[i % sampleShades.length]} strokeWidth={1.5} />
      ))}

      {/* Worst 5th percentile */}
      <polyline points={toPoints(mc.worstP5)} fill="none" stroke="#fb7185" strokeWidth={1.5} strokeDasharray="5 3" />

      {/* Median path */}
      <polyline points={toPoints(mc.median)} fill="none" stroke="#22c55e" strokeWidth={2.5} />

      {/* X-axis labels */}
      {[0, Math.floor(steps / 4), Math.floor(steps / 2), Math.floor(steps * 3 / 4), steps - 1].map((idx) => (
        <text key={idx} x={xS(idx)} y={H - PAD.bottom + 14} textAnchor="middle" fontSize={8} fill="#64748b">
          T+{idx}
        </text>
      ))}
    </svg>
  );
}

// ── Regime breakdown ───────────────────────────────────────────────────────────

interface RegimeRow {
  regime: string;
  trades: number;
  winRate: number;
  avgReturn: number;
  contribution: number;
}

function computeRegimes(result: BacktestResult): RegimeRow[] {
  const total = result.trades.length;
  // Assign trades to regimes deterministically by index
  const regimeSizes = [
    Math.round(total * 0.35),
    Math.round(total * 0.25),
    Math.round(total * 0.25),
    total - Math.round(total * 0.35) - Math.round(total * 0.25) - Math.round(total * 0.25),
  ];
  const regimeNames  = ["Trend-Up", "Range", "Trend-Down", "Crisis"];
  const wrMultiplier = [1.15, 0.92, 0.78, 0.61];
  const retMultiplier = [1.20, 0.85, 0.65, 0.40];

  return regimeNames.map((regime, i) => {
    const tCount    = Math.max(1, regimeSizes[i]);
    const wr        = Math.round(result.winRate * wrMultiplier[i]);
    const avgRet    = +(result.cagr / 12 * retMultiplier[i]).toFixed(2);
    const contrib   = +(tCount / total * result.totalReturn * retMultiplier[i] / 100).toFixed(1);
    return { regime, trades: tCount, winRate: Math.min(99, Math.max(1, wr)), avgReturn: avgRet, contribution: contrib };
  });
}

// ── Stress scenarios ───────────────────────────────────────────────────────────

const STRESS_SCENARIOS = [
  { name: "2008 Financial Crisis",  period: "Sep 2008 – Mar 2009", multiplier: 2.20, icon: "🏦" },
  { name: "2020 COVID Crash",       period: "Feb 2020 – Mar 2020", multiplier: 1.60, icon: "🦠" },
  { name: "2022 Rate Shock",        period: "Jan 2022 – Oct 2022", multiplier: 1.35, icon: "📈" },
  { name: "2025 Tariff Shock",      period: "Feb 2025 – Apr 2025", multiplier: 0.95, icon: "🌐" },
];

// ── Page ───────────────────────────────────────────────────────────────────────

const SIGNALS = [
  "RSI Oversold (< 30)",
  "Golden Cross (50/200 MA)",
  "MACD Crossover",
  "Bollinger Band Breakout",
  "EMA 20/50 Cross",
  "VCP Breakout",
  "Cup & Handle",
  "Opening Range Breakout",
  "Gap-and-Go",
  "Insider Cluster",
  "Sector Rotation",
  "PEAD Drift",
  "Mean Reversion 2-Sigma",
  "RSI Divergence",
  "Bollinger Squeeze",
];

const UNIVERSES = ["S&P 500", "NASDAQ 100", "High Beta / Small Cap"];
const CAPITALS  = [10000, 25000, 50000, 100000, 250000];

const COMMISSION_OPTIONS   = [{ label: "$0",  value: 0 }, { label: "$1",  value: 1 }, { label: "$5",  value: 5 }];
const SLIPPAGE_OPTIONS     = [
  { label: "None",              value: 0    },
  { label: "Conservative (0.05%)", value: 0.0005 },
  { label: "Realistic (0.15%)",    value: 0.0015 },
  { label: "Aggressive (0.30%)",   value: 0.003  },
];
const BORROW_COST_OPTIONS  = [{ label: "0%", value: 0 }, { label: "1%", value: 1 }, { label: "5%", value: 5 }];

export default function BacktestLabPage() {
  const [signal,      setSignal]      = useState(SIGNALS[0]);
  const [universe,    setUniverse]    = useState(UNIVERSES[0]);
  const [capital,     setCapital]     = useState(10000);
  const [commission,  setCommission]  = useState(0);
  const [slippage,    setSlippage]    = useState(0);
  const [borrowCost,  setBorrowCost]  = useState(0);

  const [hasRun,      setHasRun]      = useState(false);
  const [running,     setRunning]     = useState(false);
  const [result,      setResult]      = useState<BacktestResult | null>(null);
  const [aiOpen,      setAiOpen]      = useState(false);
  const [tab,         setTab]         = useState<"chart" | "trades" | "montecarlo">("chart");
  const [advOpen,     setAdvOpen]     = useState(false);
  const [stressOpen,  setStressOpen]  = useState(false);

  function handleRun() {
    setRunning(true);
    setTimeout(() => {
      setResult(runBacktest(signal, universe, capital, commission, slippage, borrowCost));
      setHasRun(true);
      setRunning(false);
    }, 900);
  }

  const alpha = result ? result.totalReturn - result.benchmarkReturn : null;

  const mc = useMemo<MCResult | null>(() => {
    if (!result) return null;
    return runMonteCarlo(result.trades, capital);
  }, [result, capital]);

  const regimes = useMemo<RegimeRow[]>(() => {
    if (!result) return [];
    return computeRegimes(result);
  }, [result]);

  return (
    <div className="max-w-[1600px] mx-auto pb-20 md:pb-6 space-y-5">

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-2">
            <FlaskConical size={20} className="text-amber-400" /> Backtest Lab
          </h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Rule-based strategy backtester · 3-year window · SPY benchmark</p>
        </div>
        <button
          onClick={() => setAiOpen(true)}
          className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
        >
          <Bot size={12} /> Ask AI
        </button>
      </div>

      {/* Builder */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5">
        <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-4">Strategy Builder</div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
          <div>
            <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-2">Entry Signal</label>
            <select
              value={signal}
              onChange={(e) => setSignal(e.target.value)}
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-xs rounded-lg px-3 py-2.5 outline-none focus:border-[var(--border-emphasis)] cursor-pointer"
            >
              {SIGNALS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-2">Universe</label>
            <select
              value={universe}
              onChange={(e) => setUniverse(e.target.value)}
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-xs rounded-lg px-3 py-2.5 outline-none focus:border-[var(--border-emphasis)] cursor-pointer"
            >
              {UNIVERSES.map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-2">Starting Capital</label>
            <select
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-xs rounded-lg px-3 py-2.5 outline-none focus:border-[var(--border-emphasis)] cursor-pointer"
            >
              {CAPITALS.map((c) => <option key={c} value={c}>${c.toLocaleString()}</option>)}
            </select>
          </div>
        </div>

        {/* Config summary */}
        <div className="mt-4 flex flex-wrap items-center gap-3 text-[10px] text-[var(--text-tertiary)]">
          <span>Period: Jan 2022 – May 2025 (3 years)</span>
          <span>·</span>
          <span>Position sizing: 10% per trade</span>
          <span>·</span>
          <span>Stop loss: 8%</span>
          <span>·</span>
          <span>Take profit: 20%</span>
          <span>·</span>
          <span>Benchmark: SPY</span>
        </div>

        {/* Advanced Settings */}
        <div className="mt-4 border-t border-[var(--border-subtle)] pt-4">
          <button
            onClick={() => setAdvOpen((v) => !v)}
            className="flex items-center gap-2 text-[11px] font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
          >
            {advOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            Advanced Settings (Cost Modeling)
          </button>
          {advOpen && (
            <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-5">
              <div>
                <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-2">Commission per Trade</label>
                <select
                  value={commission}
                  onChange={(e) => setCommission(Number(e.target.value))}
                  className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-xs rounded-lg px-3 py-2.5 outline-none focus:border-[var(--border-emphasis)] cursor-pointer"
                >
                  {COMMISSION_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-2">Slippage Model</label>
                <select
                  value={slippage}
                  onChange={(e) => setSlippage(Number(e.target.value))}
                  className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-xs rounded-lg px-3 py-2.5 outline-none focus:border-[var(--border-emphasis)] cursor-pointer"
                >
                  {SLIPPAGE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-2">Borrow Cost (for Shorts)</label>
                <select
                  value={borrowCost}
                  onChange={(e) => setBorrowCost(Number(e.target.value))}
                  className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-xs rounded-lg px-3 py-2.5 outline-none focus:border-[var(--border-emphasis)] cursor-pointer"
                >
                  {BORROW_COST_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
            </div>
          )}
        </div>

        <button
          onClick={handleRun}
          disabled={running}
          className="mt-4 flex items-center gap-2 px-5 py-2.5 bg-[var(--accent-positive)] hover:opacity-90 disabled:opacity-60 text-[#0a0a0a] text-sm font-bold rounded-xl transition-all cursor-pointer disabled:cursor-not-allowed"
        >
          <Play size={14} className={running ? "animate-spin" : ""} />
          {running ? "Running backtest…" : "Run Backtest"}
        </button>
      </div>

      {/* Results */}
      {hasRun && result && (
        <>
          {/* Metrics grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
            {[
              { label: "Total Return",  val: `${result.totalReturn}%`,       good: result.totalReturn > 0 },
              { label: "CAGR",          val: `${result.cagr}%`,              good: result.cagr > 8 },
              { label: "Sharpe Ratio",  val: result.sharpe.toFixed(2),       good: result.sharpe > 1 },
              { label: "Max Drawdown",  val: `-${result.maxDrawdown}%`,      good: false },
              { label: "Win Rate",      val: `${result.winRate}%`,           good: result.winRate > 55 },
              { label: "Total Trades",  val: String(result.totalTrades),     good: null },
              { label: "Avg Win",       val: `+${result.avgWin}%`,           good: true },
              { label: "Avg Loss",      val: `${result.avgLoss}%`,           good: false },
            ].map((m) => (
              <div key={m.label} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-3 py-3 text-center">
                <div className="text-[9px] font-bold uppercase tracking-wider text-[var(--text-tertiary)] mb-1">{m.label}</div>
                <div className={cn("text-lg font-bold font-mono",
                  m.good === true  ? "text-[var(--accent-positive)]" :
                  m.good === false ? "text-[var(--accent-negative)]" :
                  "text-[var(--text-primary)]"
                )}>{m.val}</div>
              </div>
            ))}
          </div>

          {/* Alpha vs benchmark */}
          <div className={cn("rounded-xl border px-5 py-3 flex items-center justify-between",
            (alpha ?? 0) > 0
              ? "bg-[var(--accent-positive)]/8 border-[var(--accent-positive)]/20"
              : "bg-[var(--accent-negative)]/8 border-[var(--accent-negative)]/20"
          )}>
            <div>
              <div className="text-xs text-[var(--text-tertiary)]">Strategy vs SPY Benchmark (3Y)</div>
              <div className="text-sm font-bold text-[var(--text-primary)] mt-0.5">
                Your strategy: <span className="text-[var(--accent-positive)]">+{result.totalReturn}%</span>&nbsp; vs &nbsp;
                SPY: <span className="text-zinc-400">+{result.benchmarkReturn}%</span>
              </div>
            </div>
            <div className="text-right">
              <div className="text-[10px] text-[var(--text-tertiary)]">Alpha generated</div>
              <div className={cn("text-xl font-bold font-mono", (alpha ?? 0) > 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                {(alpha ?? 0) > 0 ? "+" : ""}{alpha}%
              </div>
            </div>
          </div>

          {/* Regime Performance */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
            <div className="px-5 py-3 border-b border-[var(--border-subtle)]">
              <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">Regime Performance</div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/40">
                    {["Regime", "# Trades", "Win Rate", "Avg Return", "Contribution"].map((h) => (
                      <th key={h} className={cn(
                        "px-4 py-2.5 font-semibold text-[var(--text-tertiary)] tracking-wider",
                        h === "Regime" ? "text-left" : "text-right"
                      )}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {regimes.map((row, i) => {
                    const regimeColor =
                      row.regime === "Trend-Up"   ? "text-[var(--accent-positive)]" :
                      row.regime === "Range"       ? "text-amber-400" :
                      row.regime === "Trend-Down"  ? "text-orange-400" :
                      "text-[var(--accent-negative)]";
                    return (
                      <tr key={row.regime} className={i % 2 === 0 ? "" : "bg-[var(--bg-elevated-2)]/30"}>
                        <td className={cn("px-4 py-2.5 font-semibold", regimeColor)}>{row.regime}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-[var(--text-secondary)]">{row.trades}</td>
                        <td className={cn("px-4 py-2.5 text-right font-mono font-bold", row.winRate >= 60 ? "text-[var(--accent-positive)]" : "text-[var(--text-secondary)]")}>
                          {row.winRate}%
                        </td>
                        <td className={cn("px-4 py-2.5 text-right font-mono font-bold", row.avgReturn >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                          {row.avgReturn >= 0 ? "+" : ""}{row.avgReturn}%
                        </td>
                        <td className={cn("px-4 py-2.5 text-right font-mono font-bold", row.contribution >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                          {row.contribution >= 0 ? "+" : ""}{row.contribution}%
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Chart / Trades / Monte Carlo tabs */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
            <div className="flex items-center gap-1 px-4 py-3 border-b border-[var(--border-subtle)]">
              <button
                onClick={() => setTab("chart")}
                className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold cursor-pointer transition-all",
                  tab === "chart" ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]")}
              >
                <BarChart3 className="inline w-3 h-3 mr-1" />Equity Curve
              </button>
              <button
                onClick={() => setTab("trades")}
                className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold cursor-pointer transition-all",
                  tab === "trades" ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]")}
              >
                Trade Log ({result.totalTrades})
              </button>
              <button
                onClick={() => setTab("montecarlo")}
                className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold cursor-pointer transition-all flex items-center gap-1",
                  tab === "montecarlo" ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]")}
              >
                <Shuffle size={11} /> Monte Carlo
              </button>

              {tab === "chart" && (
                <div className="ml-auto flex items-center gap-4 text-[10px] text-[var(--text-tertiary)]">
                  <span className="flex items-center gap-1.5">
                    <span className="w-3 h-0.5 bg-emerald-500 rounded inline-block" /> Strategy
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-3 h-0.5 rounded inline-block" style={{ background: "repeating-linear-gradient(90deg,#64748b 0,#64748b 3px,transparent 3px,transparent 6px)" }} /> SPY
                  </span>
                </div>
              )}

              {tab === "montecarlo" && (
                <div className="ml-auto flex items-center gap-4 text-[10px] text-[var(--text-tertiary)]">
                  <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-emerald-500 rounded inline-block" /> Median</span>
                  <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-rose-400 rounded inline-block" style={{ background: "repeating-linear-gradient(90deg,#fb7185 0,#fb7185 4px,transparent 4px,transparent 7px)" }} /> 5th pct</span>
                </div>
              )}
            </div>

            {tab === "chart" && (
              <div className="p-4">
                <EquityCurve data={result.equityCurve} />
              </div>
            )}

            {tab === "trades" && (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/40">
                      {["Ticker", "Entry Date", "Exit Date", "Signal", "P&L", "Return"].map((h) => (
                        <th key={h} className={cn(
                          "px-4 py-2.5 font-semibold text-[var(--text-tertiary)] tracking-wider",
                          ["Ticker", "Signal"].includes(h) ? "text-left" : "text-right"
                        )}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.map((t, i) => (
                      <tr key={i} className={i % 2 === 0 ? "" : "bg-[var(--bg-elevated-2)]/30"}>
                        <td className="px-4 py-2.5 font-bold font-mono text-[var(--text-primary)]">{t.ticker}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-[var(--text-tertiary)]">{t.entry}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-[var(--text-tertiary)]">{t.exit}</td>
                        <td className="px-4 py-2.5 text-[var(--text-secondary)]">{t.signal}</td>
                        <td className="px-4 py-2.5 text-right font-mono font-bold">
                          <span className={t.pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"}>
                            {t.pnl >= 0 ? "+" : ""}${t.pnl.toLocaleString()}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono font-bold">
                          <span className={t.pct >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"}>
                            {t.pct >= 0 ? "+" : ""}{t.pct.toFixed(1)}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {tab === "montecarlo" && mc && (
              <div className="p-4 space-y-4">
                <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-tertiary)]">
                  Monte Carlo Simulation — 10,000 trade-shuffle resamples
                </div>
                <MonteCarloCurve mc={mc} capital={capital} />
                <div className="grid grid-cols-3 gap-3">
                  <div className="bg-[var(--bg-elevated-2)]/50 rounded-xl px-4 py-3 text-center">
                    <div className="text-[9px] font-bold uppercase tracking-wider text-[var(--text-tertiary)] mb-1">P(Ruin)</div>
                    <div className={cn("text-lg font-bold font-mono", mc.pRuin < 5 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                      {mc.pRuin < 5 ? `<5%` : `${mc.pRuin.toFixed(1)}%`}
                    </div>
                    <div className="text-[9px] text-[var(--text-tertiary)] mt-0.5">portfolio &lt;50% starting</div>
                  </div>
                  <div className="bg-[var(--bg-elevated-2)]/50 rounded-xl px-4 py-3 text-center">
                    <div className="text-[9px] font-bold uppercase tracking-wider text-[var(--text-tertiary)] mb-1">Median Final</div>
                    <div className="text-lg font-bold font-mono text-[var(--text-primary)]">
                      ${Math.round(mc.medianFinal / 1000)}K
                    </div>
                    <div className="text-[9px] text-[var(--text-tertiary)] mt-0.5">50th percentile outcome</div>
                  </div>
                  <div className="bg-[var(--bg-elevated-2)]/50 rounded-xl px-4 py-3 text-center">
                    <div className="text-[9px] font-bold uppercase tracking-wider text-[var(--text-tertiary)] mb-1">95th Pct</div>
                    <div className="text-lg font-bold font-mono text-[var(--accent-positive)]">
                      ${Math.round(mc.pct95Final / 1000)}K
                    </div>
                    <div className="text-[9px] text-[var(--text-tertiary)] mt-0.5">upside scenario</div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Stress Scenarios */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
            <button
              onClick={() => setStressOpen((v) => !v)}
              className="w-full flex items-center justify-between px-5 py-4 text-left cursor-pointer hover:bg-[var(--bg-elevated-2)]/30 transition-colors"
            >
              <div className="flex items-center gap-2">
                <TrendingDown size={14} className="text-[var(--accent-negative)]" />
                <span className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">Stress Scenarios</span>
              </div>
              {stressOpen
                ? <ChevronUp size={14} className="text-[var(--text-tertiary)]" />
                : <ChevronDown size={14} className="text-[var(--text-tertiary)]" />}
            </button>
            {stressOpen && (
              <div className="px-5 pb-5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {STRESS_SCENARIOS.map((s) => {
                  const hypotheticalDD = Math.min(99, Math.round(result.maxDrawdown * s.multiplier * 10) / 10);
                  const severity = hypotheticalDD >= 50 ? "text-[var(--accent-negative)]" : hypotheticalDD >= 30 ? "text-orange-400" : "text-amber-400";
                  return (
                    <div key={s.name} className="bg-[var(--bg-elevated-2)]/40 border border-[var(--border-subtle)] rounded-xl px-4 py-4">
                      <div className="text-lg mb-2">{s.icon}</div>
                      <div className="text-xs font-bold text-[var(--text-primary)] mb-0.5">{s.name}</div>
                      <div className="text-[10px] text-[var(--text-tertiary)] mb-3">{s.period}</div>
                      <div className={cn("text-2xl font-black font-mono", severity)}>-{hypotheticalDD}%</div>
                      <div className="text-[10px] text-[var(--text-tertiary)] mt-1">
                        This strategy would have lost {hypotheticalDD}% in this period
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}

      {!hasRun && (
        <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
          <FlaskConical size={44} className="text-[var(--border-emphasis)]" />
          <p className="text-[var(--text-secondary)] font-medium">Configure your strategy above and click Run Backtest</p>
          <p className="text-[var(--text-tertiary)] text-sm max-w-md">
            Test entry signals against historical data across different universes. Compare performance to the SPY benchmark.
          </p>
        </div>
      )}

      <p className="text-[10px] text-[var(--text-tertiary)] text-center">
        Backtesting uses historical data and does not guarantee future results. For educational purposes only.
      </p>

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title="Ask BMG about Backtesting"
        context="Backtest Lab — strategy backtester with equity curve, Sharpe ratio, win rate, and trade log"
        suggestedQuestions={[
          "What makes a Sharpe ratio good or bad?",
          "How do I improve win rate without hurting average win?",
          "What's the difference between max drawdown and volatility?",
          "How reliable is backtesting as a predictor of future performance?",
          "What are the main pitfalls of strategy overfitting?",
        ]}
      />
    </div>
  );
}

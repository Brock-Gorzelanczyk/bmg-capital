import { useState, useMemo } from "react";
import { Bot, FlaskConical, Play, TrendingUp, TrendingDown, BarChart3 } from "lucide-react";
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

function runBacktest(signal: string, universe: string, capital: number): BacktestResult {
  // Deterministic mock results based on signal type
  const profiles: Record<string, { ret: number; cagr: number; sharpe: number; dd: number; wr: number }> = {
    "RSI Oversold (< 30)":      { ret: 142, cagr: 18.4, sharpe: 1.42, dd: 18.2, wr: 68 },
    "Golden Cross (50/200 MA)": { ret: 98,  cagr: 14.2, sharpe: 1.18, dd: 22.4, wr: 61 },
    "MACD Crossover":           { ret: 118, cagr: 16.1, sharpe: 1.31, dd: 20.1, wr: 64 },
    "Bollinger Band Breakout":  { ret: 87,  cagr: 12.8, sharpe: 1.09, dd: 25.8, wr: 58 },
    "EMA 20/50 Cross":          { ret: 107, cagr: 15.2, sharpe: 1.24, dd: 21.3, wr: 62 },
  };
  const p = profiles[signal] ?? profiles["Golden Cross (50/200 MA)"];

  // Generate equity curve (monthly, 3 years)
  const months = 36;
  const curve: BacktestResult["equityCurve"] = [];
  let port = capital, bench = capital;
  const portMoReturn = Math.pow(1 + p.cagr / 100, 1 / 12);
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
    port *= portMoReturn * (1 + (Math.random() - 0.5) * 0.03);
    bench *= benchMoReturn * (1 + (Math.random() - 0.5) * 0.02);
  }

  const tickers = universe === "S&P 500" ? ["AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","JPM"]
                : universe === "NASDAQ 100" ? ["NVDA","META","AMD","NFLX","AMZN","TSLA","AVGO","INTC"]
                : ["PLTR","COIN","SOFI","ARKK","GME","AMC","MSTR","RIOT"];
  const signals = ["RSI bounce","MA cross","MACD signal","BB touch","Volume surge","Trend break","Gap fill","Momentum"];

  const trades: BacktestResult["trades"] = Array.from({ length: 24 }, (_, i) => {
    const wins = Math.round(24 * p.wr / 100);
    const isWin = i < wins;
    const pnlPct = isWin ? +(Math.random() * 12 + 2).toFixed(2) : -(Math.random() * 7 + 1).toFixed(2);
    const entryCapital = capital / 10;
    return {
      ticker: tickers[i % tickers.length],
      entry: `${2022 + Math.floor(i / 9)}-${String((i % 12) + 1).padStart(2, "0")}-${String(Math.floor(Math.random() * 28) + 1).padStart(2, "0")}`,
      exit:  `${2022 + Math.floor(i / 9)}-${String((i % 12) + 2).padStart(2, "0")}-${String(Math.floor(Math.random() * 28) + 1).padStart(2, "0")}`,
      pnl: Math.round(entryCapital * pnlPct / 100),
      pct: pnlPct,
      signal: signals[i % signals.length],
    };
  }).sort((a, b) => a.entry.localeCompare(b.entry));

  const wins2 = trades.filter((t) => t.pnl > 0);
  const losses2 = trades.filter((t) => t.pnl < 0);

  return {
    totalReturn: p.ret,
    cagr: p.cagr,
    sharpe: p.sharpe,
    maxDrawdown: p.dd,
    winRate: p.wr,
    totalTrades: trades.length,
    avgWin: wins2.length ? Math.round(wins2.reduce((s, t) => s + t.pct, 0) / wins2.length * 10) / 10 : 0,
    avgLoss: losses2.length ? Math.round(losses2.reduce((s, t) => s + t.pct, 0) / losses2.length * 10) / 10 : 0,
    benchmarkReturn: 34,
    equityCurve: curve,
    trades,
  };
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

  const portPts = data.map((d, i) => `${xS(i)},${yS(d.portfolio)}`).join(" ");
  const benchPts = data.map((d, i) => `${xS(i)},${yS(d.benchmark)}`).join(" ");
  const areaPath = `M ${xS(0)},${yS(data[0].portfolio)} ` +
    data.slice(1).map((d, i) => `L ${xS(i + 1)},${yS(d.portfolio)}`).join(" ") +
    ` L ${xS(data.length - 1)},${H - PAD.bottom} L ${xS(0)},${H - PAD.bottom} Z`;

  const gridVs = [minV, (minV + maxV) / 2, maxV];
  const fmtV = (v: number) => `$${(v / 1000).toFixed(0)}K`;

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
      <polyline points={portPts} fill="none" stroke="#22c55e" strokeWidth={2} />
      {xLabels.map((d, i) => {
        const idx = data.indexOf(d);
        return <text key={i} x={xS(idx)} y={H - PAD.bottom + 14} textAnchor="middle" fontSize={8} fill="#64748b">{d.date.slice(0, 7)}</text>;
      })}
    </svg>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const SIGNALS = ["RSI Oversold (< 30)", "Golden Cross (50/200 MA)", "MACD Crossover", "Bollinger Band Breakout", "EMA 20/50 Cross"];
const UNIVERSES = ["S&P 500", "NASDAQ 100", "High Beta / Small Cap"];
const CAPITALS = [10000, 25000, 50000, 100000, 250000];

export default function BacktestLabPage() {
  const [signal, setSignal]   = useState(SIGNALS[0]);
  const [universe, setUniverse] = useState(UNIVERSES[0]);
  const [capital, setCapital] = useState(10000);
  const [hasRun, setHasRun]   = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult]   = useState<BacktestResult | null>(null);
  const [aiOpen, setAiOpen]   = useState(false);
  const [tab, setTab]         = useState<"chart" | "trades">("chart");

  function handleRun() {
    setRunning(true);
    setTimeout(() => {
      setResult(runBacktest(signal, universe, capital));
      setHasRun(true);
      setRunning(false);
    }, 900);
  }

  const alpha = result ? result.totalReturn - result.benchmarkReturn : null;

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
        <button onClick={() => setAiOpen(true)}
          className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors">
          <Bot size={12} /> Ask AI
        </button>
      </div>

      {/* Builder */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5">
        <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-4">Strategy Builder</div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
          <div>
            <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-2">Entry Signal</label>
            <select value={signal} onChange={(e) => setSignal(e.target.value)}
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-xs rounded-lg px-3 py-2.5 outline-none focus:border-[var(--border-emphasis)] cursor-pointer">
              {SIGNALS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-2">Universe</label>
            <select value={universe} onChange={(e) => setUniverse(e.target.value)}
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-xs rounded-lg px-3 py-2.5 outline-none focus:border-[var(--border-emphasis)] cursor-pointer">
              {UNIVERSES.map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-2">Starting Capital</label>
            <select value={capital} onChange={(e) => setCapital(Number(e.target.value))}
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-xs rounded-lg px-3 py-2.5 outline-none focus:border-[var(--border-emphasis)] cursor-pointer">
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

        <button onClick={handleRun} disabled={running}
          className="mt-4 flex items-center gap-2 px-5 py-2.5 bg-[var(--accent-positive)] hover:opacity-90 disabled:opacity-60 text-[#0a0a0a] text-sm font-bold rounded-xl transition-all cursor-pointer disabled:cursor-not-allowed">
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
              { label: "Total Return",    val: `${result.totalReturn}%`,    good: result.totalReturn > 0 },
              { label: "CAGR",            val: `${result.cagr}%`,           good: result.cagr > 8 },
              { label: "Sharpe Ratio",    val: result.sharpe.toFixed(2),    good: result.sharpe > 1 },
              { label: "Max Drawdown",    val: `-${result.maxDrawdown}%`,   good: false },
              { label: "Win Rate",        val: `${result.winRate}%`,        good: result.winRate > 55 },
              { label: "Total Trades",    val: String(result.totalTrades),  good: null },
              { label: "Avg Win",         val: `+${result.avgWin}%`,        good: true },
              { label: "Avg Loss",        val: `${result.avgLoss}%`,        good: false },
            ].map((m) => (
              <div key={m.label} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-3 py-3 text-center">
                <div className="text-[9px] font-bold uppercase tracking-wider text-[var(--text-tertiary)] mb-1">{m.label}</div>
                <div className={cn("text-lg font-bold font-mono",
                  m.good === true ? "text-[var(--accent-positive)]" : m.good === false ? "text-[var(--accent-negative)]" : "text-[var(--text-primary)]"
                )}>{m.val}</div>
              </div>
            ))}
          </div>

          {/* Alpha vs benchmark */}
          <div className={cn("rounded-xl border px-5 py-3 flex items-center justify-between",
            (alpha ?? 0) > 0 ? "bg-[var(--accent-positive)]/8 border-[var(--accent-positive)]/20" : "bg-[var(--accent-negative)]/8 border-[var(--accent-negative)]/20"
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

          {/* Chart / Trades tabs */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
            <div className="flex items-center gap-1 px-4 py-3 border-b border-[var(--border-subtle)]">
              <button onClick={() => setTab("chart")}
                className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold cursor-pointer transition-all", tab==="chart"?"bg-[var(--bg-elevated-2)] text-[var(--text-primary)]":"text-[var(--text-tertiary)] hover:text-[var(--text-primary)]")}>
                <BarChart3 className="inline w-3 h-3 mr-1" />Equity Curve
              </button>
              <button onClick={() => setTab("trades")}
                className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold cursor-pointer transition-all", tab==="trades"?"bg-[var(--bg-elevated-2)] text-[var(--text-primary)]":"text-[var(--text-tertiary)] hover:text-[var(--text-primary)]")}>
                Trade Log ({result.totalTrades})
              </button>
              <div className="ml-auto flex items-center gap-4 text-[10px] text-[var(--text-tertiary)]">
                <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-emerald-500 rounded inline-block" /> Strategy</span>
                <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-zinc-500 rounded inline-block" style={{background:"repeating-linear-gradient(90deg,#64748b 0,#64748b 3px,transparent 3px,transparent 6px)"}} /> SPY</span>
              </div>
            </div>

            {tab === "chart" ? (
              <div className="p-4">
                <EquityCurve data={result.equityCurve} />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/40">
                      {["Ticker","Entry Date","Exit Date","Signal","P&L","Return"].map((h) => (
                        <th key={h} className={cn("px-4 py-2.5 font-semibold text-[var(--text-tertiary)] tracking-wider", ["Ticker","Signal"].includes(h)?"text-left":"text-right")}>{h}</th>
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
          </div>
        </>
      )}

      {!hasRun && (
        <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
          <FlaskConical size={44} className="text-[var(--border-emphasis)]" />
          <p className="text-[var(--text-secondary)] font-medium">Configure your strategy above and click Run Backtest</p>
          <p className="text-[var(--text-tertiary)] text-sm max-w-md">Test entry signals against historical data across different universes. Compare performance to the SPY benchmark.</p>
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

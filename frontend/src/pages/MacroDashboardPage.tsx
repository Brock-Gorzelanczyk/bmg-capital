import { useState } from "react";
import { Bot, Globe, TrendingUp, TrendingDown, Calendar, Activity } from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { cn } from "@/lib/utils";

// ── Data ───────────────────────────────────────────────────────────────────────

const YIELD_CURVE = [
  { label: "1M",  y: 5.28 }, { label: "3M",  y: 5.31 }, { label: "6M",  y: 5.24 },
  { label: "1Y",  y: 5.01 }, { label: "2Y",  y: 4.68 }, { label: "5Y",  y: 4.38 },
  { label: "10Y", y: 4.38 }, { label: "20Y", y: 4.62 }, { label: "30Y", y: 4.56 },
];
const YIELD_PRIOR = [
  { label: "1M",  y: 5.29 }, { label: "3M",  y: 5.32 }, { label: "6M",  y: 5.22 },
  { label: "1Y",  y: 5.08 }, { label: "2Y",  y: 4.78 }, { label: "5Y",  y: 4.48 },
  { label: "10Y", y: 4.50 }, { label: "20Y", y: 4.72 }, { label: "30Y", y: 4.65 },
];

const CENTRAL_BANKS = [
  { bank: "Federal Reserve",          rate: "5.25–5.50%", last: "-25bps (Nov 2024)", dir: "Cutting" },
  { bank: "ECB",                      rate: "4.00%",       last: "-25bps (Dec 2024)", dir: "Cutting" },
  { bank: "Bank of England",          rate: "5.00%",       last: "-25bps (Nov 2024)", dir: "Cutting" },
  { bank: "Bank of Japan",            rate: "0.25%",       last: "+15bps (Jul 2024)", dir: "Hiking"  },
  { bank: "Bank of Canada",           rate: "3.75%",       last: "-25bps (Oct 2024)", dir: "Cutting" },
  { bank: "Reserve Bank of Australia",rate: "4.35%",       last: "Unchanged",         dir: "Hold"    },
  { bank: "Swiss National Bank",      rate: "1.00%",       last: "-25bps (Dec 2024)", dir: "Cutting" },
  { bank: "PBOC",                     rate: "3.45%",       last: "-10bps (Jul 2024)", dir: "Easing"  },
];

const FOMC_MEETINGS = [
  { date: "Jan 28–29, 2025", cut: 11,  hold: 89 },
  { date: "Mar 18–19, 2025", cut: 52,  hold: 48 },
  { date: "May 6–7, 2025",   cut: 71,  hold: 29 },
  { date: "Jun 17–18, 2025", cut: 85,  hold: 15 },
];

const ECO_CALENDAR = [
  { date: "Jun 4",  event: "ISM Manufacturing",  impact: "high",   prior: "49.2",  expected: "49.8",  actual: "" },
  { date: "Jun 5",  event: "ADP Employment",      impact: "med",    prior: "192K",  expected: "180K",  actual: "" },
  { date: "Jun 7",  event: "Nonfarm Payrolls",    impact: "high",   prior: "256K",  expected: "185K",  actual: "" },
  { date: "Jun 7",  event: "Unemployment Rate",   impact: "high",   prior: "3.7%",  expected: "3.7%",  actual: "" },
  { date: "Jun 11", event: "CPI YoY",             impact: "high",   prior: "3.4%",  expected: "3.3%",  actual: "" },
  { date: "Jun 12", event: "Core CPI",            impact: "med",    prior: "3.6%",  expected: "3.5%",  actual: "" },
  { date: "Jun 12", event: "FOMC Decision",       impact: "high",   prior: "5.25%", expected: "Hold",  actual: "" },
  { date: "Jun 14", event: "PPI MoM",             impact: "med",    prior: "0.2%",  expected: "0.2%",  actual: "" },
  { date: "Jun 25", event: "GDP Final Q1",        impact: "high",   prior: "3.2%",  expected: "3.2%",  actual: "" },
  { date: "Jun 28", event: "PCE Price Index",     impact: "high",   prior: "2.7%",  expected: "2.6%",  actual: "" },
];

const COMMODITIES = [
  { name: "Gold",          value: "$2,651",  pct: 0.34  },
  { name: "Crude (WTI)",   value: "$71.42",  pct: -0.87 },
  { name: "Natural Gas",   value: "$2.89",   pct: 1.24  },
  { name: "Copper",        value: "$4.18/lb",pct: 0.51  },
  { name: "Silver",        value: "$31.24",  pct: 0.68  },
  { name: "DXY (Dollar)",  value: "104.82",  pct: -0.21 },
];

// ── SVG Yield Curve ────────────────────────────────────────────────────────────

function YieldCurveChart() {
  const W = 600, H = 200, PAD = { top: 16, right: 16, bottom: 32, left: 44 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const minY = 3.8, maxY = 5.6;
  const xScale = (i: number) => PAD.left + (i / (YIELD_CURVE.length - 1)) * innerW;
  const yScale = (v: number) => PAD.top + innerH - ((v - minY) / (maxY - minY)) * innerH;

  const toPoints = (data: typeof YIELD_CURVE) =>
    data.map((d, i) => `${xScale(i)},${yScale(d.y)}`).join(" ");

  const areaPath = `M ${xScale(0)},${yScale(YIELD_CURVE[0].y)} ` +
    YIELD_CURVE.slice(1).map((d, i) => `L ${xScale(i + 1)},${yScale(d.y)}`).join(" ") +
    ` L ${xScale(YIELD_CURVE.length - 1)},${H - PAD.bottom} L ${xScale(0)},${H - PAD.bottom} Z`;

  const gridYs = [4.0, 4.5, 5.0, 5.5];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" style={{ maxHeight: 200 }}>
      {/* Grid lines */}
      {gridYs.map((v) => (
        <g key={v}>
          <line x1={PAD.left} y1={yScale(v)} x2={W - PAD.right} y2={yScale(v)} stroke="#ffffff10" strokeWidth={1} />
          <text x={PAD.left - 6} y={yScale(v) + 4} textAnchor="end" fontSize={9} fill="#64748b">{v.toFixed(1)}%</text>
        </g>
      ))}

      {/* Area fill (current) */}
      <path d={areaPath} fill="#3b82f620" />

      {/* Prior week line */}
      <polyline points={toPoints(YIELD_PRIOR)} fill="none" stroke="#64748b" strokeWidth={1.5} strokeDasharray="4 2" />

      {/* Current line */}
      <polyline points={toPoints(YIELD_CURVE)} fill="none" stroke="#22c55e" strokeWidth={2} />

      {/* Dots */}
      {YIELD_CURVE.map((d, i) => (
        <circle key={d.label} cx={xScale(i)} cy={yScale(d.y)} r={3} fill="#22c55e" />
      ))}

      {/* X axis labels */}
      {YIELD_CURVE.map((d, i) => (
        <text key={d.label} x={xScale(i)} y={H - PAD.bottom + 14} textAnchor="middle" fontSize={9} fill="#64748b">{d.label}</text>
      ))}
    </svg>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function MacroDashboardPage() {
  const [aiOpen, setAiOpen] = useState(false);

  const dirColor = (d: string) =>
    d === "Cutting" || d === "Easing" ? "text-[var(--accent-positive)] bg-[var(--accent-positive)]/10 border-[var(--accent-positive)]/20"
    : d === "Hiking" ? "text-[var(--accent-negative)] bg-[var(--accent-negative)]/10 border-[var(--accent-negative)]/20"
    : "text-zinc-400 bg-zinc-800/40 border-zinc-700/40";

  const impactDot = (level: string) =>
    level === "high" ? "bg-red-500" : level === "med" ? "bg-amber-400" : "bg-emerald-500";

  return (
    <div className="max-w-[1600px] mx-auto pb-20 md:pb-6 space-y-6">

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-2">
            <Globe size={20} className="text-blue-400" /> Macro Dashboard
          </h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Global economic indicators · Central bank policy · Yield curve</p>
        </div>
        <button onClick={() => setAiOpen(true)}
          className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors">
          <Bot size={12} /> Ask AI
        </button>
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Fed Funds Rate",  value: "5.25–5.50%", sub: "Unchanged since Sep '24", border: "border-l-blue-500",   up: null },
          { label: "US 10Y Yield",    value: "4.38%",       sub: "▼ -0.04% today",          border: "border-l-emerald-500", up: false },
          { label: "DXY Dollar",      value: "104.82",      sub: "▼ -0.21%",                 border: "border-l-amber-500",  up: false },
          { label: "VIX",             value: "18.42",       sub: "▼ -1.2 · Low volatility",  border: "border-l-emerald-500", up: false },
          { label: "CPI YoY",         value: "3.4%",        sub: "▼ from 3.5% prior",        border: "border-l-emerald-500", up: false },
          { label: "Core PCE",        value: "2.7%",        sub: "▼ from 2.8%",              border: "border-l-emerald-500", up: false },
          { label: "Unemployment",    value: "3.7%",        sub: "→ Unchanged",              border: "border-l-blue-500",   up: null },
          { label: "GDP Growth Q4",   value: "3.2%",        sub: "▲ from 3.1% prior",        border: "border-l-emerald-500", up: true  },
        ].map((m) => (
          <div key={m.label} className={cn("bg-[var(--bg-elevated)] border border-[var(--border-subtle)] border-l-2 rounded-xl px-4 py-3", m.border)}>
            <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-1">{m.label}</div>
            <div className="text-xl font-bold font-mono text-[var(--text-primary)]">{m.value}</div>
            <div className={cn("text-[10px] mt-0.5", m.up === true ? "text-[var(--accent-positive)]" : m.up === false ? "text-[var(--accent-negative)]" : "text-[var(--text-tertiary)]")}>{m.sub}</div>
          </div>
        ))}
      </div>

      {/* Yield curve */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-sm font-bold text-[var(--text-primary)]">US Treasury Yield Curve</div>
            <div className="text-[11px] text-[var(--text-tertiary)] mt-0.5">Spot rates vs. 1 week ago (dashed)</div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[9px] font-bold px-2 py-1 rounded-lg bg-amber-900/30 text-amber-400 border border-amber-800/40 uppercase tracking-wider">Inverted 2Y–10Y</span>
            <span className="text-xs font-mono text-[var(--text-tertiary)]">2Y: 4.68% · 10Y: 4.38%</span>
          </div>
        </div>
        <YieldCurveChart />
        <div className="flex items-center gap-5 mt-3 pt-3 border-t border-[var(--border-subtle)]">
          <div className="flex items-center gap-1.5"><div className="w-4 h-0.5 bg-emerald-500 rounded" /><span className="text-[10px] text-[var(--text-tertiary)]">Current</span></div>
          <div className="flex items-center gap-1.5"><div className="w-4 h-0.5 bg-zinc-500 rounded border-dashed border border-zinc-500" style={{background:"repeating-linear-gradient(90deg,#64748b 0,#64748b 4px,transparent 4px,transparent 8px)"}} /><span className="text-[10px] text-[var(--text-tertiary)]">1 Week Ago</span></div>
        </div>
      </div>

      {/* Central banks + FOMC */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Central bank table */}
        <div className="lg:col-span-2 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
          <div className="px-5 py-3 border-b border-[var(--border-subtle)]">
            <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">Global Central Bank Rates</div>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/40">
                {["Central Bank", "Rate", "Last Change", "Direction"].map((h) => (
                  <th key={h} className={cn("px-4 py-2.5 font-semibold text-[var(--text-tertiary)] tracking-wider", h==="Central Bank"?"text-left":"text-right")}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CENTRAL_BANKS.map((b, i) => (
                <tr key={b.bank} className={i % 2 === 0 ? "" : "bg-[var(--bg-elevated-2)]/30"}>
                  <td className="px-4 py-2.5 font-semibold text-[var(--text-primary)]">{b.bank}</td>
                  <td className="px-4 py-2.5 text-right font-mono font-bold text-[var(--text-primary)]">{b.rate}</td>
                  <td className="px-4 py-2.5 text-right text-[var(--text-tertiary)]">{b.last}</td>
                  <td className="px-4 py-2.5 text-right">
                    <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded border uppercase tracking-wider", dirColor(b.dir))}>{b.dir}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* FOMC calendar */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-4">
          <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-4">Next FOMC Meetings</div>
          <div className="space-y-4">
            {FOMC_MEETINGS.map((m) => (
              <div key={m.date}>
                <div className="flex justify-between mb-1.5">
                  <span className="text-xs font-semibold text-[var(--text-primary)]">{m.date}</span>
                </div>
                <div className="flex gap-1 mb-1">
                  <div className="h-3 rounded-sm bg-[var(--accent-positive)]" style={{ width: `${m.cut}%`, minWidth: m.cut > 0 ? 4 : 0 }} />
                  <div className="h-3 rounded-sm bg-[var(--bg-elevated-2)]" style={{ width: `${m.hold}%` }} />
                </div>
                <div className="flex justify-between text-[9px] text-[var(--text-tertiary)]">
                  <span className="text-[var(--accent-positive)] font-bold">Cut {m.cut}%</span>
                  <span>Hold {m.hold}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Economic calendar */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-[var(--border-subtle)] flex items-center gap-2">
          <Calendar size={13} className="text-[var(--text-tertiary)]" />
          <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)]">Economic Calendar — June 2025</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/40">
                {["Date", "Event", "Impact", "Prior", "Expected", "Actual"].map((h) => (
                  <th key={h} className={cn("px-4 py-2.5 font-semibold text-[var(--text-tertiary)] tracking-wider", h==="Event"?"text-left":"text-right")}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ECO_CALENDAR.map((e, i) => (
                <tr key={i} className={i % 2 === 0 ? "" : "bg-[var(--bg-elevated-2)]/30"}>
                  <td className="px-4 py-2.5 text-right font-mono text-[var(--text-tertiary)]">{e.date}</td>
                  <td className="px-4 py-2.5 font-semibold text-[var(--text-primary)]">{e.event}</td>
                  <td className="px-4 py-2.5 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      <div className={cn("w-2 h-2 rounded-full", impactDot(e.impact))} />
                      <span className="text-[var(--text-tertiary)] capitalize">{e.impact}</span>
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-[var(--text-tertiary)]">{e.prior}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-[var(--text-secondary)]">{e.expected}</td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {e.actual ? <span className="font-bold text-[var(--text-primary)]">{e.actual}</span> : <span className="text-[var(--text-tertiary)]">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Commodities */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {COMMODITIES.map((c) => {
          const pos = c.pct >= 0;
          return (
            <div key={c.name} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3">
              <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-1">{c.name}</div>
              <div className="text-lg font-bold font-mono text-[var(--text-primary)]">{c.value}</div>
              <div className={cn("text-[11px] font-mono font-semibold flex items-center gap-0.5 mt-0.5", pos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                {pos ? <TrendingUp size={11} /> : <TrendingDown size={11} />} {pos ? "+" : ""}{c.pct.toFixed(2)}%
              </div>
            </div>
          );
        })}
      </div>

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title="Ask BMG about Macro"
        context="Macro Dashboard — yield curve, central bank rates, economic calendar, commodities"
        suggestedQuestions={[
          "What does yield curve inversion signal for stocks?",
          "How does the Fed rate path affect my portfolio?",
          "What's the relationship between CPI and Fed policy?",
          "How should I position for a rate cut cycle?",
          "What are the most market-moving economic events?",
        ]}
      />
    </div>
  );
}

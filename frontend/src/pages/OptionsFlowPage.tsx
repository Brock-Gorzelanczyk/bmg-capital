import { useState, useMemo } from "react";
import { Bot, Zap, Filter, RefreshCw, TrendingUp, TrendingDown } from "lucide-react";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { cn } from "@/lib/utils";

// ── Types & Data ───────────────────────────────────────────────────────────────

interface FlowEntry {
  id: number; time: string; ticker: string; expiry: string; strike: number;
  type: "CALL" | "PUT"; sentiment: "BULLISH" | "BEARISH" | "NEUTRAL";
  bid: number; ask: number; volume: number; oi: number; premium: number;
  unusual: boolean; sweep: boolean; sector: string;
}

const FLOW_DATA: FlowEntry[] = [
  { id:1,  time:"09:31", ticker:"NVDA",  expiry:"07/18/25", strike:145, type:"CALL", sentiment:"BULLISH",  bid:4.20, ask:4.25, volume:12840, oi:45200, premium:4200, unusual:true,  sweep:true,  sector:"Technology" },
  { id:2,  time:"09:34", ticker:"SPY",   expiry:"06/20/25", strike:585, type:"PUT",  sentiment:"BEARISH",  bid:2.10, ask:2.15, volume:8920,  oi:182000,premium:1800, unusual:false, sweep:true,  sector:"ETF" },
  { id:3,  time:"09:41", ticker:"TSLA",  expiry:"07/18/25", strike:280, type:"CALL", sentiment:"BULLISH",  bid:3.40, ask:3.45, volume:4210,  oi:28400, premium:892,  unusual:false, sweep:false, sector:"Consumer Disc" },
  { id:4,  time:"09:45", ticker:"QQQ",   expiry:"06/27/25", strike:490, type:"PUT",  sentiment:"BEARISH",  bid:1.85, ask:1.90, volume:11200, oi:94000, premium:2100, unusual:true,  sweep:true,  sector:"ETF" },
  { id:5,  time:"09:52", ticker:"META",  expiry:"08/15/25", strike:580, type:"CALL", sentiment:"BULLISH",  bid:6.20, ask:6.30, volume:3840,  oi:18200, premium:1240, unusual:false, sweep:false, sector:"Communication" },
  { id:6,  time:"10:04", ticker:"AAPL",  expiry:"06/20/25", strike:200, type:"CALL", sentiment:"BULLISH",  bid:1.45, ask:1.50, volume:22000, oi:210000,premium:3200, unusual:true,  sweep:true,  sector:"Technology" },
  { id:7,  time:"10:11", ticker:"AMZN",  expiry:"07/18/25", strike:220, type:"CALL", sentiment:"BULLISH",  bid:2.80, ask:2.85, volume:5600,  oi:32000, premium:780,  unusual:false, sweep:false, sector:"Consumer Disc" },
  { id:8,  time:"10:18", ticker:"XLE",   expiry:"06/20/25", strike:88,  type:"PUT",  sentiment:"BEARISH",  bid:0.95, ask:1.00, volume:18400, oi:88000, premium:1840, unusual:true,  sweep:false, sector:"Energy" },
  { id:9,  time:"10:25", ticker:"AMD",   expiry:"07/18/25", strike:175, type:"CALL", sentiment:"BULLISH",  bid:3.10, ask:3.15, volume:6200,  oi:41000, premium:970,  unusual:false, sweep:true,  sector:"Technology" },
  { id:10, time:"10:33", ticker:"MSFT",  expiry:"08/15/25", strike:440, type:"CALL", sentiment:"BULLISH",  bid:5.40, ask:5.50, volume:2800,  oi:22000, premium:1540, unusual:false, sweep:false, sector:"Technology" },
  { id:11, time:"10:41", ticker:"COIN",  expiry:"06/27/25", strike:240, type:"CALL", sentiment:"BULLISH",  bid:4.80, ask:4.90, volume:4400,  oi:12800, premium:2140, unusual:true,  sweep:true,  sector:"Financials" },
  { id:12, time:"10:48", ticker:"PLTR",  expiry:"07/18/25", strike:28,  type:"CALL", sentiment:"BULLISH",  bid:1.20, ask:1.25, volume:14200, oi:68000, premium:1700, unusual:false, sweep:false, sector:"Technology" },
  { id:13, time:"11:02", ticker:"SPY",   expiry:"07/18/25", strike:570, type:"PUT",  sentiment:"BEARISH",  bid:3.20, ask:3.25, volume:6800,  oi:124000,premium:2200, unusual:true,  sweep:true,  sector:"ETF" },
  { id:14, time:"11:14", ticker:"SOFI",  expiry:"06/20/25", strike:14,  type:"CALL", sentiment:"BULLISH",  bid:0.45, ask:0.50, volume:28400, oi:182000,premium:1278, unusual:false, sweep:false, sector:"Financials" },
  { id:15, time:"11:22", ticker:"GOOGL", expiry:"08/15/25", strike:185, type:"CALL", sentiment:"BULLISH",  bid:4.10, ask:4.20, volume:3200,  oi:28000, premium:1320, unusual:false, sweep:true,  sector:"Communication" },
  { id:16, time:"11:35", ticker:"MSTR",  expiry:"06/27/25", strike:380, type:"CALL", sentiment:"BULLISH",  bid:8.40, ask:8.60, volume:2800,  oi:8400,  premium:2400, unusual:true,  sweep:false, sector:"Technology" },
  { id:17, time:"11:48", ticker:"NFLX",  expiry:"07/18/25", strike:680, type:"PUT",  sentiment:"BEARISH",  bid:5.20, ask:5.30, volume:1840,  oi:12800, premium:970,  unusual:false, sweep:false, sector:"Communication" },
  { id:18, time:"12:04", ticker:"JPM",   expiry:"06/20/25", strike:225, type:"PUT",  sentiment:"BEARISH",  bid:1.80, ask:1.85, volume:8200,  oi:44000, premium:1480, unusual:false, sweep:true,  sector:"Financials" },
  { id:19, time:"12:18", ticker:"ARKK",  expiry:"07/18/25", strike:55,  type:"PUT",  sentiment:"BEARISH",  bid:1.40, ask:1.45, volume:12400, oi:88000, premium:1736, unusual:true,  sweep:false, sector:"ETF" },
  { id:20, time:"12:35", ticker:"NVDA",  expiry:"09/19/25", strike:160, type:"CALL", sentiment:"BULLISH",  bid:6.80, ask:6.90, volume:5200,  oi:28000, premium:3588, unusual:true,  sweep:true,  sector:"Technology" },
  { id:21, time:"12:52", ticker:"XLK",   expiry:"06/20/25", strike:230, type:"CALL", sentiment:"BULLISH",  bid:2.40, ask:2.45, volume:7800,  oi:32000, premium:1872, unusual:false, sweep:false, sector:"Technology" },
  { id:22, time:"13:08", ticker:"BAC",   expiry:"07/18/25", strike:44,  type:"PUT",  sentiment:"BEARISH",  bid:0.90, ask:0.95, volume:18800, oi:124000,premium:1692, unusual:false, sweep:true,  sector:"Financials" },
  { id:23, time:"13:24", ticker:"TSLA",  expiry:"08/15/25", strike:260, type:"PUT",  sentiment:"BEARISH",  bid:7.20, ask:7.30, volume:2400,  oi:18400, premium:1752, unusual:true,  sweep:false, sector:"Consumer Disc" },
  { id:24, time:"13:41", ticker:"AMD",   expiry:"09/19/25", strike:200, type:"CALL", sentiment:"BULLISH",  bid:4.40, ask:4.50, volume:3800,  oi:22000, premium:1692, unusual:false, sweep:true,  sector:"Technology" },
  { id:25, time:"14:02", ticker:"META",  expiry:"06/20/25", strike:560, type:"PUT",  sentiment:"NEUTRAL",  bid:3.80, ask:3.90, volume:2200,  oi:14000, premium:847,  unusual:false, sweep:false, sector:"Communication" },
  { id:26, time:"14:18", ticker:"AAPL",  expiry:"09/19/25", strike:210, type:"CALL", sentiment:"BULLISH",  bid:3.20, ask:3.30, volume:6400,  oi:48000, premium:2112, unusual:true,  sweep:true,  sector:"Technology" },
  { id:27, time:"14:35", ticker:"SPY",   expiry:"08/15/25", strike:600, type:"CALL", sentiment:"BULLISH",  bid:2.80, ask:2.85, volume:9200,  oi:82000, premium:2599, unusual:true,  sweep:false, sector:"ETF" },
  { id:28, time:"14:52", ticker:"QQQ",   expiry:"07/18/25", strike:510, type:"CALL", sentiment:"BULLISH",  bid:3.40, ask:3.45, volume:5800,  oi:44000, premium:1996, unusual:false, sweep:true,  sector:"ETF" },
  { id:29, time:"15:08", ticker:"MSFT",  expiry:"06/27/25", strike:420, type:"PUT",  sentiment:"BEARISH",  bid:2.10, ask:2.15, volume:4200,  oi:28000, premium:899,  unusual:false, sweep:false, sector:"Technology" },
  { id:30, time:"15:24", ticker:"COIN",  expiry:"08/15/25", strike:280, type:"CALL", sentiment:"BULLISH",  bid:5.80, ask:5.90, volume:3200,  oi:8800,  premium:1888, unusual:true,  sweep:true,  sector:"Financials" },
];

const PC_SECTORS = [
  { name: "Technology",    ratio: 0.72 },
  { name: "Financials",    ratio: 0.91 },
  { name: "Energy",        ratio: 1.23 },
  { name: "Healthcare",    ratio: 0.88 },
  { name: "Consumer",      ratio: 1.14 },
  { name: "Crypto",        ratio: 0.64 },
];

const TOP_TICKERS = [
  { ticker: "NVDA", premium: 7788, direction: "BULLISH"  },
  { ticker: "SPY",  premium: 6599, direction: "BEARISH"  },
  { ticker: "AAPL", premium: 5312, direction: "BULLISH"  },
  { ticker: "COIN", premium: 4028, direction: "BULLISH"  },
  { ticker: "QQQ",  premium: 4096, direction: "MIXED"    },
];

function fmtPremium(k: number) {
  if (k >= 1000) return `$${(k / 1000).toFixed(1)}M`;
  return `$${k}K`;
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function OptionsFlowPage() {
  const [sentiment, setSentiment] = useState<"ALL" | "BULLISH" | "BEARISH" | "NEUTRAL">("ALL");
  const [typeFilter, setTypeFilter] = useState<"ALL" | "CALL" | "PUT">("ALL");
  const [unusualOnly, setUnusualOnly] = useState(false);
  const [sweepsOnly, setSweepsOnly]   = useState(false);
  const [showAll, setShowAll]         = useState(false);
  const [aiOpen, setAiOpen]           = useState(false);

  const filtered = useMemo(() => {
    return FLOW_DATA.filter((e) => {
      if (sentiment !== "ALL" && e.sentiment !== sentiment) return false;
      if (typeFilter !== "ALL" && e.type !== typeFilter) return false;
      if (unusualOnly && !e.unusual) return false;
      if (sweepsOnly && !e.sweep) return false;
      return true;
    });
  }, [sentiment, typeFilter, unusualOnly, sweepsOnly]);

  const displayed = showAll ? filtered : filtered.slice(0, 20);

  const totalPremium = FLOW_DATA.reduce((a, e) => a + e.premium, 0);
  const bullish = FLOW_DATA.filter((e) => e.sentiment === "BULLISH").length;
  const bearish = FLOW_DATA.filter((e) => e.sentiment === "BEARISH").length;
  const unusual = FLOW_DATA.filter((e) => e.unusual).length;
  const sweeps  = FLOW_DATA.filter((e) => e.sweep).length;

  return (
    <div className="max-w-[1600px] mx-auto pb-20 md:pb-6 space-y-5">

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Options Flow</h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Live unusual options activity · Large premium trades · Institutional positioning</p>
        </div>
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors px-3 py-1.5 rounded-lg bg-[var(--bg-elevated-2)] cursor-pointer">
            <RefreshCw size={12} /> Refresh
          </button>
          <button onClick={() => setAiOpen(true)}
            className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors">
            <Bot size={12} /> Ask AI
          </button>
        </div>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Total Premium Today", value: fmtPremium(totalPremium), color: "text-[var(--text-primary)]" },
          { label: "Bull / Bear Ratio",   value: `${(bullish/bearish).toFixed(2)}`, color: "text-[var(--accent-positive)]" },
          { label: "Unusual Trades",      value: String(unusual), color: "text-amber-400" },
          { label: "Sweep Orders",        value: String(sweeps),  color: "text-violet-400" },
        ].map((s) => (
          <div key={s.label} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3">
            <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-1">{s.label}</div>
            <div className={cn("text-2xl font-bold font-mono", s.color)}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl px-4 py-3">
        <Filter size={13} className="text-[var(--text-tertiary)]" />
        <div className="flex gap-1">
          {(["ALL","BULLISH","BEARISH","NEUTRAL"] as const).map((s) => (
            <button key={s} onClick={() => setSentiment(s)}
              className={cn("px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all cursor-pointer",
                sentiment === s ? (s==="BULLISH"?"bg-emerald-900/50 text-emerald-400 border border-emerald-700/60":s==="BEARISH"?"bg-red-900/50 text-red-400 border border-red-700/60":"bg-[var(--bg-elevated-2)] text-[var(--text-primary)] border border-[var(--border-emphasis)]") : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
              )}>{s}</button>
          ))}
        </div>
        <div className="w-px h-4 bg-[var(--border-subtle)]" />
        <div className="flex gap-1">
          {(["ALL","CALL","PUT"] as const).map((t) => (
            <button key={t} onClick={() => setTypeFilter(t)}
              className={cn("px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all cursor-pointer",
                typeFilter === t ? (t==="CALL"?"bg-emerald-900/40 text-emerald-400 border border-emerald-800/60":t==="PUT"?"bg-red-900/40 text-red-400 border border-red-800/60":"bg-[var(--bg-elevated-2)] text-[var(--text-primary)] border border-[var(--border-emphasis)]") : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
              )}>{t}</button>
          ))}
        </div>
        <div className="w-px h-4 bg-[var(--border-subtle)]" />
        <label className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)] cursor-pointer">
          <input type="checkbox" checked={unusualOnly} onChange={(e) => setUnusualOnly(e.target.checked)} className="accent-amber-400" />
          Unusual only
        </label>
        <label className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)] cursor-pointer">
          <input type="checkbox" checked={sweepsOnly} onChange={(e) => setSweepsOnly(e.target.checked)} className="accent-violet-400" />
          Sweeps only
        </label>
        <span className="ml-auto text-[10px] text-[var(--text-tertiary)] font-mono">{filtered.length} trades</span>
      </div>

      {/* Main layout */}
      <div className="flex gap-5 flex-col lg:flex-row">

        {/* Flow table */}
        <div className="flex-1 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-elevated-2)]/60">
                  {["Time","Ticker","Expiry","Strike","Type","Bid / Ask","Volume","OI","Premium","Flags","Sentiment"].map((h) => (
                    <th key={h} className={cn("px-3 py-3 font-semibold text-[var(--text-tertiary)] tracking-wider whitespace-nowrap", h==="Ticker"||h==="Time"?"text-left":"text-right", h==="Sentiment"?"text-left":"")}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {displayed.map((e, i) => (
                  <tr key={e.id}
                    className={cn(
                      "border-b border-[var(--border-subtle)]/50 hover:bg-[var(--bg-elevated-2)] transition-colors",
                      e.unusual ? "border-l-2 border-l-amber-500" : "",
                      i % 2 === 0 ? "" : "bg-[var(--bg-elevated-2)]/30"
                    )}
                  >
                    <td className="px-3 py-2.5 font-mono text-[var(--text-tertiary)]">{e.time}</td>
                    <td className="px-3 py-2.5 font-bold text-[var(--text-primary)] font-mono">{e.ticker}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-[var(--text-secondary)]">{e.expiry}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-[var(--text-secondary)]">${e.strike}</td>
                    <td className="px-3 py-2.5 text-right">
                      <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded uppercase", e.type==="CALL" ? "bg-emerald-900/50 text-emerald-300 border border-emerald-800/60" : "bg-red-900/50 text-red-300 border border-red-800/60")}>
                        {e.type}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-[var(--text-secondary)]">{e.bid.toFixed(2)} / {e.ask.toFixed(2)}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-[var(--text-secondary)]">{e.volume.toLocaleString()}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-[var(--text-tertiary)]">{e.oi.toLocaleString()}</td>
                    <td className="px-3 py-2.5 text-right font-bold font-mono">
                      <span className={cn(e.sentiment==="BULLISH"?"text-[var(--accent-positive)]":e.sentiment==="BEARISH"?"text-[var(--accent-negative)]":"text-[var(--text-secondary)]")}>
                        {fmtPremium(e.premium)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <div className="flex items-center justify-end gap-1">
                        {e.sweep && <span title="Sweep" className="text-[9px] font-bold text-violet-400"><Zap size={10} /></span>}
                        {e.unusual && <span className="text-[8px] font-bold px-1 py-0.5 rounded bg-amber-900/40 text-amber-400 border border-amber-800/50">UNS</span>}
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={cn("text-[9px] font-bold uppercase",
                        e.sentiment==="BULLISH"?"text-[var(--accent-positive)]":e.sentiment==="BEARISH"?"text-[var(--accent-negative)]":"text-[var(--text-tertiary)]"
                      )}>{e.sentiment}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!showAll && filtered.length > 20 && (
            <div className="px-4 py-3 border-t border-[var(--border-subtle)]">
              <button onClick={() => setShowAll(true)}
                className="text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] cursor-pointer transition-colors">
                Show {filtered.length - 20} more trades ↓
              </button>
            </div>
          )}
        </div>

        {/* Side panel */}
        <div className="w-full lg:w-72 shrink-0 space-y-4">

          {/* Put/Call by sector */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-4">
            <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-3">Put/Call Ratio by Sector</div>
            <div className="space-y-3">
              {PC_SECTORS.map((s) => {
                const bullish = s.ratio < 1;
                const pct = Math.min(s.ratio / 2, 1) * 100;
                return (
                  <div key={s.name}>
                    <div className="flex justify-between mb-1">
                      <span className="text-[11px] text-[var(--text-secondary)]">{s.name}</span>
                      <span className={cn("text-[11px] font-mono font-bold", bullish ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>{s.ratio.toFixed(2)}</span>
                    </div>
                    <div className="h-1.5 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
                      <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: bullish ? "#22c55e" : "#ef4444" }} />
                    </div>
                  </div>
                );
              })}
              <div className="text-[9px] text-[var(--text-tertiary)] mt-2">P/C &lt; 1 = bullish · P/C &gt; 1 = bearish</div>
            </div>
          </div>

          {/* Top tickers */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-4">
            <div className="text-xs font-bold uppercase tracking-widest text-[var(--text-tertiary)] mb-3">Top by Premium</div>
            <div className="space-y-2">
              {TOP_TICKERS.map((t, i) => (
                <div key={t.ticker} className="flex items-center gap-3 py-1.5 border-b border-[var(--border-subtle)] last:border-0">
                  <span className="text-[10px] font-bold text-[var(--text-tertiary)] font-mono w-4">{i + 1}</span>
                  <span className="font-bold text-[var(--text-primary)] text-sm font-mono flex-1">{t.ticker}</span>
                  <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded uppercase",
                    t.direction==="BULLISH"?"text-emerald-400 bg-emerald-900/30":t.direction==="BEARISH"?"text-red-400 bg-red-900/30":"text-zinc-400 bg-zinc-800/60"
                  )}>{t.direction}</span>
                  <span className="text-xs font-mono font-bold text-[var(--text-primary)]">{fmtPremium(t.premium)}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Legend */}
          <div className="bg-[var(--bg-elevated-2)] rounded-xl p-3 space-y-1.5">
            <div className="text-[9px] font-bold uppercase tracking-wider text-[var(--text-tertiary)] mb-2">Legend</div>
            <div className="flex items-center gap-2 text-[10px] text-[var(--text-tertiary)]"><Zap size={10} className="text-violet-400" /> Sweep order (multi-exchange)</div>
            <div className="flex items-center gap-2 text-[10px] text-[var(--text-tertiary)]"><span className="text-[8px] font-bold px-1 py-0.5 rounded bg-amber-900/40 text-amber-400 border border-amber-800/50">UNS</span> Unusual volume (vol/OI &gt; 3x)</div>
            <div className="flex items-center gap-2 text-[10px] text-[var(--text-tertiary)]"><span className="w-2 h-full border-l-2 border-amber-500 inline-block" /> Row highlight = unusual trade</div>
          </div>
        </div>
      </div>

      {/* Disclaimer */}
      <p className="text-[10px] text-[var(--text-tertiary)] text-center">
        Options flow is delayed 15 minutes. For educational purposes only. Not financial advice.
      </p>

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title="Ask BMG about Options Flow"
        context="Options Flow page — unusual options activity, large premium trades, put/call ratios by sector"
        suggestedQuestions={[
          "What does high put/call ratio signal for the market?",
          "How do sweep orders indicate institutional positioning?",
          "What's the difference between unusual volume and a sweep?",
          "How do I use options premium as a sentiment indicator?",
          "What are the key options flow signals before earnings?",
        ]}
      />
    </div>
  );
}

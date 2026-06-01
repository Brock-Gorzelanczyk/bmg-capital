import { useState, useCallback, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, RefreshCw, X, Bot, Zap, TrendingUp, TrendingDown, AlertTriangle, Play, Pause, DollarSign, Activity } from "lucide-react";
import { getOptionsChain, getExpirations } from "@/api/options";
import OptionsChain from "@/components/options/OptionsChain";
import SpreadBuilder from "@/components/options/SpreadBuilder";
import PLChart from "@/components/options/PLChart";
import type { OptionContract, OptionsLeg } from "@/types/options";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const DEFAULT_SYMBOLS = ["AAPL", "TSLA", "SPY", "QQQ", "NVDA", "AMZN", "MSFT", "META"];

// ── Big Money Flow ─────────────────────────────────────────────────────────────

interface FlowSignal {
  id: number;
  ticker: string;
  type: "CALL" | "PUT";
  strike: number;
  expiry: string;
  premium: number;
  contracts: number;
  sentiment: "bullish" | "bearish" | "neutral";
  time: string;
  confidence: number;
  source: "Sweep" | "Block" | "Dark Pool";
  deployed?: boolean;
}

const SEED_FLOW: FlowSignal[] = [
  { id: 1,  ticker: "NVDA",  type: "CALL", strike: 150,  expiry: "Jun 20", premium: 2_480_000, contracts: 3200, sentiment: "bullish", time: "09:34 AM", confidence: 94, source: "Sweep" },
  { id: 2,  ticker: "SPY",   type: "PUT",  strike: 525,  expiry: "Jun 7",  premium: 1_820_000, contracts: 4100, sentiment: "bearish", time: "09:41 AM", confidence: 88, source: "Block" },
  { id: 3,  ticker: "AAPL",  type: "CALL", strike: 215,  expiry: "Jun 27", premium: 960_000,   contracts: 1800, sentiment: "bullish", time: "09:52 AM", confidence: 76, source: "Dark Pool" },
  { id: 4,  ticker: "TSLA",  type: "PUT",  strike: 160,  expiry: "Jun 14", premium: 3_100_000, contracts: 5500, sentiment: "bearish", time: "10:04 AM", confidence: 91, source: "Sweep" },
  { id: 5,  ticker: "QQQ",   type: "CALL", strike: 490,  expiry: "Jun 20", premium: 2_240_000, contracts: 2900, sentiment: "bullish", time: "10:09 AM", confidence: 83, source: "Block" },
  { id: 6,  ticker: "META",  type: "CALL", strike: 640,  expiry: "Jul 18", premium: 1_540_000, contracts: 1200, sentiment: "bullish", time: "10:18 AM", confidence: 79, source: "Dark Pool" },
  { id: 7,  ticker: "AMZN",  type: "PUT",  strike: 185,  expiry: "Jun 7",  premium: 870_000,   contracts: 1600, sentiment: "bearish", time: "10:26 AM", confidence: 71, source: "Block" },
  { id: 8,  ticker: "MSFT",  type: "CALL", strike: 470,  expiry: "Jun 20", premium: 1_890_000, contracts: 2100, sentiment: "bullish", time: "10:33 AM", confidence: 86, source: "Sweep" },
  { id: 9,  ticker: "NVDA",  type: "PUT",  strike: 110,  expiry: "Jun 14", premium: 680_000,   contracts: 900,  sentiment: "bearish", time: "10:41 AM", confidence: 65, source: "Dark Pool" },
  { id: 10, ticker: "SPY",   type: "CALL", strike: 545,  expiry: "Jun 20", premium: 4_200_000, contracts: 6800, sentiment: "bullish", time: "10:48 AM", confidence: 97, source: "Sweep" },
  { id: 11, ticker: "AAPL",  type: "PUT",  strike: 185,  expiry: "Jun 7",  premium: 520_000,   contracts: 1100, sentiment: "bearish", time: "10:55 AM", confidence: 62, source: "Block" },
  { id: 12, ticker: "NFLX",  type: "CALL", strike: 1050, expiry: "Jul 18", premium: 730_000,   contracts: 480,  sentiment: "bullish", time: "11:03 AM", confidence: 74, source: "Dark Pool" },
];

const LIVE_SIGNALS: Omit<FlowSignal, "id">[] = [
  { ticker: "AMD",   type: "CALL", strike: 180,  expiry: "Jun 20", premium: 1_120_000, contracts: 2200, sentiment: "bullish", time: "11:12 AM", confidence: 89, source: "Sweep" },
  { ticker: "COIN",  type: "CALL", strike: 260,  expiry: "Jun 27", premium: 890_000,   contracts: 1400, sentiment: "bullish", time: "11:19 AM", confidence: 81, source: "Block" },
  { ticker: "GLD",   type: "PUT",  strike: 220,  expiry: "Jun 14", premium: 650_000,   contracts: 1800, sentiment: "bearish", time: "11:27 AM", confidence: 73, source: "Dark Pool" },
  { ticker: "QQQ",   type: "PUT",  strike: 460,  expiry: "Jun 7",  premium: 2_900_000, contracts: 5100, sentiment: "bearish", time: "11:35 AM", confidence: 92, source: "Sweep" },
];

function fmt$(n: number) {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n}`;
}

function ConfBar({ v }: { v: number }) {
  const color = v >= 85 ? "#BEF264" : v >= 70 ? "#F59E0B" : "#94A3B8";
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-1.5 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${v}%`, backgroundColor: color }} />
      </div>
      <span className="text-[11px] font-mono font-semibold" style={{ color }}>{v}%</span>
    </div>
  );
}

function BigMoneyFlow() {
  const [feed, setFeed] = useState<FlowSignal[]>(SEED_FLOW);
  const [filter, setFilter] = useState<"all" | "bullish" | "bearish">("all");
  const [autoOn, setAutoOn] = useState(false);
  const [threshold, setThreshold] = useState(80);
  const [deploySize, setDeploySize] = useState(1000);
  const [deployLog, setDeployLog] = useState<{ id: number; ticker: string; type: string; size: number; at: string }[]>([]);
  const nextId = useRef(SEED_FLOW.length + 1);
  const liveIdx = useRef(0);

  // Simulate incoming live signals every 18s
  useEffect(() => {
    const t = setInterval(() => {
      const sig = LIVE_SIGNALS[liveIdx.current % LIVE_SIGNALS.length];
      liveIdx.current++;
      const newSignal: FlowSignal = { ...sig, id: nextId.current++ };
      setFeed((prev) => [newSignal, ...prev.slice(0, 29)]);

      if (autoOn && newSignal.confidence >= threshold) {
        setDeployLog((prev) => [
          { id: newSignal.id, ticker: newSignal.ticker, type: newSignal.type, size: deploySize, at: newSignal.time },
          ...prev,
        ]);
        setFeed((prev) => prev.map((s) => s.id === newSignal.id ? { ...s, deployed: true } : s));
        toast.success(`Auto-deployed $${deploySize.toLocaleString()} → ${newSignal.ticker} ${newSignal.type} (${newSignal.confidence}% confidence)`);
      }
    }, 18_000);
    return () => clearInterval(t);
  }, [autoOn, threshold, deploySize]);

  const manualDeploy = (sig: FlowSignal) => {
    if (sig.deployed) return;
    setFeed((prev) => prev.map((s) => s.id === sig.id ? { ...s, deployed: true } : s));
    setDeployLog((prev) => [{ id: sig.id, ticker: sig.ticker, type: sig.type, size: deploySize, at: sig.time }, ...prev]);
    toast.success(`Deployed $${deploySize.toLocaleString()} → ${sig.ticker} ${sig.type}`);
  };

  const visible = feed.filter((s) => filter === "all" || s.sentiment === filter);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-[var(--accent-positive)]" />
          <span className="font-bold text-[var(--text-primary)] text-sm">Big Money Flow</span>
          <span className="flex items-center gap-1 text-[10px] text-[var(--accent-positive)] bg-[var(--accent-positive)]/10 px-2 py-0.5 rounded-full font-semibold">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-positive)] animate-pulse" />
            Live
          </span>
        </div>
        <div className="flex items-center gap-1 bg-[var(--bg-elevated-2)] rounded-lg p-0.5">
          {(["all", "bullish", "bearish"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                "px-3 py-1 rounded-md text-xs font-semibold capitalize transition-colors",
                filter === f
                  ? f === "bullish" ? "bg-[var(--accent-positive)]/20 text-[var(--accent-positive)]"
                    : f === "bearish" ? "bg-[var(--accent-negative)]/20 text-[var(--accent-negative)]"
                    : "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                  : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
              )}
            >
              {f === "bullish" ? "▲ Bullish" : f === "bearish" ? "▼ Bearish" : "All"}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_280px] gap-4">
        {/* Flow feed */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--border-emphasis)]/60 text-[var(--text-tertiary)]">
                  <th className="px-3 py-2 text-left font-semibold uppercase tracking-wider">Ticker</th>
                  <th className="px-3 py-2 text-left font-semibold uppercase tracking-wider">Contract</th>
                  <th className="px-3 py-2 text-left font-semibold uppercase tracking-wider">Premium</th>
                  <th className="px-3 py-2 text-left font-semibold uppercase tracking-wider">Contracts</th>
                  <th className="px-3 py-2 text-left font-semibold uppercase tracking-wider">Source</th>
                  <th className="px-3 py-2 text-left font-semibold uppercase tracking-wider">Confidence</th>
                  <th className="px-3 py-2 text-left font-semibold uppercase tracking-wider">Time</th>
                  <th className="px-3 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {visible.map((s) => {
                  const isBull = s.sentiment === "bullish";
                  return (
                    <tr key={s.id} className={cn(
                      "border-b border-[var(--border-emphasis)]/40 transition-colors",
                      s.deployed ? "opacity-50" : "hover:bg-white/3",
                      s.id === feed[0]?.id && !s.deployed && "bg-[var(--accent-positive)]/5"
                    )}>
                      <td className="px-3 py-2.5">
                        <span className="font-bold font-mono text-[var(--text-primary)]">{s.ticker}</span>
                        {s.id === feed[0]?.id && (
                          <span className="ml-1.5 text-[9px] bg-[var(--accent-positive)]/20 text-[var(--accent-positive)] px-1 py-0.5 rounded font-bold">NEW</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <span className={cn("font-bold font-mono px-1.5 py-0.5 rounded text-[11px]",
                          isBull ? "text-[var(--accent-positive)] bg-[var(--accent-positive)]/10" : "text-[var(--accent-negative)] bg-[var(--accent-negative)]/10"
                        )}>
                          {s.type}
                        </span>
                        <span className="ml-1.5 text-[var(--text-secondary)] font-mono">${s.strike} · {s.expiry}</span>
                      </td>
                      <td className="px-3 py-2.5 font-mono font-bold text-[var(--text-primary)]">{fmt$(s.premium)}</td>
                      <td className="px-3 py-2.5 font-mono text-[var(--text-secondary)]">{s.contracts.toLocaleString()}</td>
                      <td className="px-3 py-2.5">
                        <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-semibold",
                          s.source === "Sweep"     ? "bg-purple-500/15 text-purple-400" :
                          s.source === "Block"     ? "bg-blue-500/15 text-blue-400" :
                          "bg-zinc-500/15 text-zinc-400"
                        )}>
                          {s.source}
                        </span>
                      </td>
                      <td className="px-3 py-2.5"><ConfBar v={s.confidence} /></td>
                      <td className="px-3 py-2.5 text-[var(--text-tertiary)] font-mono">{s.time}</td>
                      <td className="px-3 py-2.5">
                        {s.deployed ? (
                          <span className="text-[10px] text-[var(--text-tertiary)]">Deployed</span>
                        ) : (
                          <button
                            onClick={() => manualDeploy(s)}
                            className="text-[10px] font-bold text-[var(--accent-positive)] hover:text-white bg-[var(--accent-positive)]/10 hover:bg-[var(--accent-positive)] px-2 py-1 rounded transition-colors"
                          >
                            Deploy
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Auto-Deploy panel */}
        <div className="space-y-3">
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Zap size={14} className={autoOn ? "text-[var(--accent-positive)]" : "text-[var(--text-tertiary)]"} />
                <span className="text-sm font-bold text-[var(--text-primary)]">Auto-Deploy</span>
              </div>
              <button
                onClick={() => {
                  const next = !autoOn;
                  setAutoOn(next);
                  toast[next ? "success" : "info"](next ? "Auto-Deploy enabled — watching for signals…" : "Auto-Deploy paused");
                }}
                className={cn(
                  "flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-lg transition-colors",
                  autoOn
                    ? "bg-[var(--accent-positive)] text-[var(--bg-base)]"
                    : "bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                )}
              >
                {autoOn ? <><Pause size={11} /> Live</> : <><Play size={11} /> Start</>}
              </button>
            </div>

            {autoOn && (
              <div className="flex items-center gap-2 text-[11px] bg-[var(--accent-positive)]/8 border border-[var(--accent-positive)]/20 rounded-lg px-3 py-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-positive)] animate-pulse shrink-0" />
                <span className="text-[var(--accent-positive)]">Watching for signals ≥{threshold}% confidence</span>
              </div>
            )}

            <div className="space-y-3">
              <div>
                <div className="flex justify-between text-[11px] mb-1.5">
                  <span className="text-[var(--text-tertiary)]">Confidence threshold</span>
                  <span className="text-[var(--text-primary)] font-mono font-bold">{threshold}%</span>
                </div>
                <input
                  type="range" min={60} max={95} step={5} value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                  className="w-full accent-[#BEF264] h-1.5 rounded-full cursor-pointer"
                />
                <div className="flex justify-between text-[9px] text-[var(--text-tertiary)] mt-0.5">
                  <span>60% (aggressive)</span><span>95% (cautious)</span>
                </div>
              </div>

              <div>
                <div className="text-[11px] text-[var(--text-tertiary)] mb-1.5">Deploy size per signal</div>
                <div className="flex gap-1 flex-wrap">
                  {[500, 1000, 2500, 5000].map((v) => (
                    <button
                      key={v}
                      onClick={() => setDeploySize(v)}
                      className={cn(
                        "text-[11px] font-mono font-bold px-2 py-1 rounded-lg border transition-colors",
                        deploySize === v
                          ? "border-[var(--accent-positive)] text-[var(--accent-positive)] bg-[var(--accent-positive)]/10"
                          : "border-[var(--border-emphasis)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
                      )}
                    >
                      ${v.toLocaleString()}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="border-t border-[var(--border-subtle)] pt-3 space-y-1">
              <div className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-2">Deploy logic</div>
              {[
                { label: "Min confidence",  val: `≥${threshold}%` },
                { label: "Signal types",    val: "Sweeps + Blocks" },
                { label: "Position size",   val: `$${deploySize.toLocaleString()}` },
                { label: "Risk control",    val: "10% stop auto-set" },
              ].map(({ label, val }) => (
                <div key={label} className="flex justify-between text-[11px]">
                  <span className="text-[var(--text-tertiary)]">{label}</span>
                  <span className="text-[var(--text-secondary)] font-mono">{val}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Deploy log */}
          {deployLog.length > 0 && (
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
              <div className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-3">Deployed Today</div>
              <div className="space-y-2">
                {deployLog.slice(0, 5).map((d) => (
                  <div key={d.id} className="flex items-center justify-between text-[11px]">
                    <div className="flex items-center gap-1.5">
                      <DollarSign size={10} className="text-[var(--accent-positive)]" />
                      <span className="font-mono font-bold text-[var(--text-primary)]">{d.ticker}</span>
                      <span className={cn("px-1 py-0.5 rounded text-[9px] font-bold",
                        d.type === "CALL" ? "text-[var(--accent-positive)] bg-[var(--accent-positive)]/10" : "text-[var(--accent-negative)] bg-[var(--accent-negative)]/10"
                      )}>{d.type}</span>
                    </div>
                    <div className="text-right">
                      <div className="text-[var(--text-primary)] font-mono">${d.size.toLocaleString()}</div>
                      <div className="text-[var(--text-tertiary)] text-[9px]">{d.at}</div>
                    </div>
                  </div>
                ))}
              </div>
              {deployLog.length > 0 && (
                <div className="mt-3 pt-3 border-t border-[var(--border-subtle)] flex justify-between text-[11px]">
                  <span className="text-[var(--text-tertiary)]">Total deployed</span>
                  <span className="font-mono font-bold text-[var(--text-primary)]">${(deployLog.reduce((s, d) => s + d.size, 0)).toLocaleString()}</span>
                </div>
              )}
            </div>
          )}

          <div className="flex items-start gap-2 px-1">
            <AlertTriangle size={11} className="text-[var(--text-tertiary)] shrink-0 mt-0.5" />
            <p className="text-[10px] text-[var(--text-tertiary)] leading-relaxed">
              Auto-Deploy executes paper positions only. Options flow data is simulated. Always verify signals independently before live trading.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function OptionsLab() {
  const [symbol, setSymbol] = useState("AAPL");
  const [inputVal, setInputVal] = useState("AAPL");
  const [expiration, setExpiration] = useState<string | undefined>(undefined);
  const [legs, setLegs] = useState<OptionsLeg[]>([]);
  const [activeTab, setActiveTab] = useState<"calls" | "puts" | "all">("all");
  const [mainTab, setMainTab] = useState<"chain" | "flow">("chain");
  const [aiOpen, setAiOpen] = useState(false);

  const { data: expirations = [] } = useQuery({
    queryKey: ["options-expirations"],
    queryFn: getExpirations,
    staleTime: 1000 * 60 * 60,
  });

  const { data: chain, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["options-chain", symbol, expiration],
    queryFn: () => getOptionsChain(symbol, expiration),
    staleTime: 1000 * 60 * 2,
    enabled: !!symbol,
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const s = inputVal.trim().toUpperCase();
    if (s) setSymbol(s);
  };

  const addLeg = useCallback((contract: OptionContract, side: "buy" | "sell") => {
    setLegs((prev) => {
      const existing = prev.findIndex(
        (l) => l.contract.symbol === contract.symbol && l.side === side
      );
      if (existing >= 0) return prev; // already in builder
      return [...prev, { contract, side, qty: 1 }];
    });
  }, []);

  const removeLeg = useCallback((idx: number) => {
    setLegs((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const toggleSide = useCallback((idx: number) => {
    setLegs((prev) =>
      prev.map((l, i) => i === idx ? { ...l, side: l.side === "buy" ? "sell" : "buy" } : l)
    );
  }, []);

  const setQty = useCallback((idx: number, qty: number) => {
    setLegs((prev) =>
      prev.map((l, i) => i === idx ? { ...l, qty } : l)
    );
  }, []);

  const calls = chain?.calls ?? [];
  const puts = chain?.puts ?? [];
  const visibleCalls = activeTab === "puts" ? [] : calls;
  const visiblePuts = activeTab === "calls" ? [] : puts;

  return (
    <div className="space-y-4 pb-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)]">Options Lab</h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Build and analyze options strategies</p>
        </div>
        <div className="flex items-center gap-2">
          {/* Main tab switcher */}
          <div className="flex items-center gap-0.5 bg-[var(--bg-elevated-2)] rounded-lg p-0.5">
            <button
              onClick={() => setMainTab("chain")}
              className={cn("text-xs font-semibold px-3 py-1.5 rounded-md transition-colors", mainTab === "chain" ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]")}
            >
              Chain
            </button>
            <button
              onClick={() => setMainTab("flow")}
              className={cn("flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-md transition-colors", mainTab === "flow" ? "bg-[var(--accent-positive)]/20 text-[var(--accent-positive)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]")}
            >
              <Zap size={11} /> Big Money
            </button>
          </div>
          {chain?.source === "synthetic" && mainTab === "chain" && (
            <span className="text-[10px] px-2 py-1 rounded-full bg-amber-950 text-amber-400 border border-amber-900 font-medium">
              Synthetic B-S pricing
            </span>
          )}
          <button
            onClick={() => setAiOpen(true)}
            className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
          >
            <Bot size={12} /> Ask AI
          </button>
        </div>
      </div>

      {/* Symbol + expiration bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <form onSubmit={handleSearch} className="flex items-center gap-2">
          <input
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value.toUpperCase())}
            placeholder="Symbol"
            className="bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-sm px-3 py-2 rounded-lg w-28 placeholder-zinc-600 focus:outline-none focus:border-zinc-600 uppercase font-mono"
          />
          <button
            type="submit"
            className="bg-[var(--accent-positive)] text-[var(--text-primary)] font-semibold text-sm px-4 py-2 rounded-lg hover:brightness-110 transition-colors"
          >
            Load
          </button>
        </form>

        {/* Quick symbols */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {DEFAULT_SYMBOLS.map((s) => (
            <button
              key={s}
              onClick={() => { setSymbol(s); setInputVal(s); }}
              className={`text-xs font-mono px-2 py-1 rounded-md transition-colors ${
                symbol === s
                  ? "bg-white text-black font-bold"
                  : "bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[#334155]"
              }`}
            >
              {s}
            </button>
          ))}
        </div>

        {/* Expiration picker */}
        {expirations.length > 0 && (
          <div className="relative ml-auto">
            <select
              value={expiration ?? ""}
              onChange={(e) => setExpiration(e.target.value || undefined)}
              className="appearance-none bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] text-[var(--text-secondary)] text-sm px-3 py-2 pr-8 rounded-lg focus:outline-none focus:border-zinc-600 cursor-pointer"
            >
              <option value="">Next expiry</option>
              {expirations.map((e) => (
                <option key={e} value={e}>{e}</option>
              ))}
            </select>
            <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] pointer-events-none" />
          </div>
        )}

        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
          title="Refresh chain"
        >
          <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
        </button>
      </div>

      {mainTab === "flow" && <BigMoneyFlow />}

      {/* Main layout: chain + builder side-by-side */}
      {mainTab === "chain" && <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-4">
        {/* Chain panel */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
          {/* Chain header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)]">
            <div className="flex items-center gap-3">
              <span className="text-[var(--text-primary)] font-bold text-sm font-mono">{symbol}</span>
              {chain && (
                <span className="text-[var(--text-tertiary)] text-xs">
                  Underlying: <span className="text-[var(--text-primary)] font-mono">${chain.underlyingPrice.toFixed(2)}</span>
                </span>
              )}
            </div>
            <div className="flex items-center gap-1 bg-[var(--bg-elevated-2)] rounded-lg p-0.5">
              {(["all", "calls", "puts"] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`text-xs px-2.5 py-1 rounded-md font-medium capitalize transition-colors ${
                    activeTab === tab ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]" : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>
          </div>

          {isLoading ? (
            <div className="p-8 text-center text-[var(--text-tertiary)] text-sm animate-pulse">
              Loading chain…
            </div>
          ) : !chain ? (
            <div className="p-8 text-center text-[var(--text-tertiary)] text-sm">
              Enter a symbol to load the options chain
            </div>
          ) : (
            <OptionsChain
              calls={visibleCalls}
              puts={visiblePuts}
              underlyingPrice={chain.underlyingPrice}
              legs={legs}
              onAddLeg={addLeg}
            />
          )}
        </div>

        {/* Builder + chart panel */}
        <div className="space-y-4">
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
            <SpreadBuilder
              legs={legs}
              onRemoveLeg={removeLeg}
              onToggleSide={toggleSide}
              onSetQty={setQty}
            />
            {legs.length > 0 && (
              <button
                onClick={() => setLegs([])}
                className="mt-3 flex items-center gap-1 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-xs transition-colors"
              >
                <X size={12} /> Clear all legs
              </button>
            )}
          </div>

          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
            <div className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider mb-3">
              P&amp;L at Expiration
            </div>
            <PLChart
              legs={legs}
              underlyingPrice={chain?.underlyingPrice ?? 150}
            />
            {legs.length > 0 && (
              <div className="mt-2 flex items-center gap-4 text-[10px]">
                <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#22C55E] inline-block rounded" /> Profit</span>
                <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#EF4444] inline-block rounded" /> Loss</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-400 inline-block" /> Breakeven</span>
                <span className="flex items-center gap-1"><span className="w-3 h-0.5 border-t border-dashed border-amber-700 inline-block" /> Current price</span>
              </div>
            )}
          </div>

          {/* Greeks summary */}
          {legs.length > 0 && (
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
              <div className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider mb-3">
                Position Greeks
              </div>
              <div className="grid grid-cols-4 gap-2">
                {(["delta", "gamma", "theta", "vega"] as const).map((greek) => {
                  const total = legs.reduce((sum, leg) => {
                    const g = leg.contract[greek];
                    const mult = leg.side === "buy" ? 1 : -1;
                    return sum + g * mult * leg.qty * 100;
                  }, 0);
                  return (
                    <div key={greek} className="text-center">
                      <div className="text-[10px] text-[var(--text-tertiary)] capitalize mb-0.5">{greek}</div>
                      <div className={`text-sm font-bold font-mono ${
                        total > 0 ? "text-[var(--accent-positive)]" : total < 0 ? "text-[var(--accent-negative)]" : "text-[var(--text-secondary)]"
                      }`}>
                        {total > 0 ? "+" : ""}{total.toFixed(2)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>}

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title={`Ask BMG about ${symbol} Options`}
        context={`Options Lab — analyzing ${symbol} options chain`}
        suggestedQuestions={[
          `What's the implied volatility telling us about ${symbol}?`,
          "Explain the P&L profile of this spread",
          "What's the max profit and max loss here?",
          "How does theta decay affect this position over time?",
          "What's the breakeven price at expiration?",
        ]}
      />
    </div>
  );
}

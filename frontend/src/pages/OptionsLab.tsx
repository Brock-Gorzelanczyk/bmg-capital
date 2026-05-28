import { useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, RefreshCw, X } from "lucide-react";
import { getOptionsChain, getExpirations } from "@/api/options";
import OptionsChain from "@/components/options/OptionsChain";
import SpreadBuilder from "@/components/options/SpreadBuilder";
import PLChart from "@/components/options/PLChart";
import type { OptionContract, OptionsLeg } from "@/types/options";

const DEFAULT_SYMBOLS = ["AAPL", "TSLA", "SPY", "QQQ", "NVDA", "AMZN", "MSFT", "META"];

export default function OptionsLab() {
  const [symbol, setSymbol] = useState("AAPL");
  const [inputVal, setInputVal] = useState("AAPL");
  const [expiration, setExpiration] = useState<string | undefined>(undefined);
  const [legs, setLegs] = useState<OptionsLeg[]>([]);
  const [activeTab, setActiveTab] = useState<"calls" | "puts" | "all">("all");

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
        {chain?.source === "synthetic" && (
          <span className="text-[10px] px-2 py-1 rounded-full bg-amber-950 text-amber-400 border border-amber-900 font-medium">
            Synthetic B-S pricing
          </span>
        )}
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

      {/* Main layout: chain + builder side-by-side */}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-4">
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
      </div>
    </div>
  );
}

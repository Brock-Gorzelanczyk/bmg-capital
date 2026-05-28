import { useState, useEffect, useRef } from "react";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface IndicatorDef {
  key: string;
  label: string;
  params: string;
  color: string;
  category: string;
}

const ALL_INDICATORS: IndicatorDef[] = [
  // Moving Averages
  { key: "SMA_20",  label: "Simple Moving Average",        params: "20",     color: "#f59e0b", category: "Moving Averages" },
  { key: "SMA_50",  label: "Simple Moving Average",        params: "50",     color: "#3b82f6", category: "Moving Averages" },
  { key: "SMA_200", label: "Simple Moving Average",        params: "200",    color: "#8b5cf6", category: "Moving Averages" },
  { key: "EMA_20",  label: "Exponential Moving Average",   params: "20",     color: "#fbbf24", category: "Moving Averages" },
  { key: "EMA_50",  label: "Exponential Moving Average",   params: "50",     color: "#60a5fa", category: "Moving Averages" },
  { key: "EMA_200", label: "Exponential Moving Average",   params: "200",    color: "#a78bfa", category: "Moving Averages" },
  { key: "DEMA_20", label: "Double Exponential Moving Avg",params: "20",     color: "#f472b6", category: "Moving Averages" },
  { key: "VWAP",    label: "Volume Weighted Average Price", params: "",       color: "#06b6d4", category: "Moving Averages" },
  // Trend
  { key: "ADX",      label: "Average Directional Index",   params: "14",     color: "#fbbf24", category: "Trend" },
  { key: "ICHIMOKU", label: "Ichimoku Cloud",              params: "",       color: "#26a69a", category: "Trend" },
  { key: "PSAR",     label: "Parabolic SAR",               params: "",       color: "#9c27b0", category: "Trend" },
  // Oscillators
  { key: "RSI_14", label: "Relative Strength Index",       params: "14",     color: "#22c55e", category: "Oscillators" },
  { key: "MACD",   label: "MACD",                          params: "12,26,9",color: "#ec4899", category: "Oscillators" },
  { key: "STOCH",  label: "Stochastic",                    params: "14,3,3", color: "#f97316", category: "Oscillators" },
  { key: "WILLR",  label: "Williams %R",                   params: "14",     color: "#14b8a6", category: "Oscillators" },
  { key: "CCI",    label: "CCI",                           params: "20",     color: "#e879f9", category: "Oscillators" },
  { key: "ROC",    label: "Rate of Change",                params: "12",     color: "#fb923c", category: "Oscillators" },
  // Volatility
  { key: "BB_20",    label: "Bollinger Bands",             params: "20,2",   color: "#94a3b8", category: "Volatility" },
  { key: "ATR",      label: "Average True Range",          params: "14",     color: "#64748b", category: "Volatility" },
  { key: "DONCHIAN", label: "Donchian Channel",            params: "",       color: "#607d8b", category: "Volatility" },
  { key: "KELTNER",  label: "Keltner Channel",             params: "",       color: "#ff9800", category: "Volatility" },
  // Volume
  { key: "OBV", label: "On Balance Volume",                params: "",       color: "#fbbf24", category: "Volume" },
  { key: "CMF", label: "Chaikin Money Flow",               params: "20",     color: "#06b6d4", category: "Volume" },
  { key: "MFI", label: "Money Flow Index",                 params: "14",     color: "#a78bfa", category: "Volume" },
];

const CATEGORIES = ["Moving Averages", "Trend", "Oscillators", "Volatility", "Volume"];

interface Props {
  active: Set<string>;
  onChange: (s: Set<string>) => void;
  onClose: () => void;
}

export default function IndicatorsModal({ active, onChange, onClose }: Props) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 50);
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const toggle = (key: string) => {
    const next = new Set(active);
    if (next.has(key)) next.delete(key); else next.add(key);
    onChange(next);
  };

  const filtered = query
    ? ALL_INDICATORS.filter((i) =>
        i.label.toLowerCase().includes(query.toLowerCase()) ||
        i.key.toLowerCase().includes(query.toLowerCase())
      )
    : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-[#111] border border-[#1f1f1f] rounded-lg shadow-2xl w-[480px] max-h-[70vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[#1f1f1f]">
          <Search size={15} className="text-[#555] shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search indicators..."
            className="flex-1 bg-transparent text-[#d4d4d4] text-sm placeholder-[#555] focus:outline-none"
          />
          <button onClick={onClose} className="text-[#555] hover:text-[#d4d4d4]">
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-2 py-2">
          {filtered ? (
            filtered.length === 0 ? (
              <p className="text-center text-[#555] text-sm py-8">No indicators found</p>
            ) : (
              <div className="space-y-0.5">
                {filtered.map((ind) => (
                  <IndicatorRow key={ind.key} ind={ind} active={active.has(ind.key)} onToggle={() => toggle(ind.key)} />
                ))}
              </div>
            )
          ) : (
            CATEGORIES.map((cat) => {
              const items = ALL_INDICATORS.filter((i) => i.category === cat);
              return (
                <div key={cat} className="mb-3">
                  <p className="text-[10px] text-[#555] uppercase tracking-widest px-2 mb-1">{cat}</p>
                  <div className="space-y-0.5">
                    {items.map((ind) => (
                      <IndicatorRow key={ind.key} ind={ind} active={active.has(ind.key)} onToggle={() => toggle(ind.key)} />
                    ))}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Active count */}
        <div className="border-t border-[#1f1f1f] px-4 py-2 flex items-center justify-between">
          <span className="text-xs text-[#555]">{active.size} active</span>
          {active.size > 0 && (
            <button onClick={() => onChange(new Set())} className="text-xs text-[#ef5350] hover:text-red-400">
              Clear all
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function IndicatorRow({ ind, active, onToggle }: { ind: IndicatorDef; active: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      className={cn(
        "w-full flex items-center gap-3 px-3 py-2 rounded hover:bg-[#1f1f1f] transition-colors text-left",
        active && "bg-[#1f1f1f]"
      )}
    >
      <span
        className="w-2.5 h-2.5 rounded-full shrink-0"
        style={{ backgroundColor: ind.color }}
      />
      <div className="flex-1 min-w-0">
        <span className="text-sm text-[#d4d4d4]">{ind.label}</span>
        {ind.params && (
          <span className="text-xs text-[#555] ml-1.5">({ind.params})</span>
        )}
      </div>
      <span
        className={cn(
          "text-xs font-medium px-2 py-0.5 rounded border transition-colors",
          active
            ? "border-white/20 text-[var(--text-primary)]"
            : "border-[#1f1f1f] text-[#555]"
        )}
      >
        {active ? "On" : "Add"}
      </span>
    </button>
  );
}

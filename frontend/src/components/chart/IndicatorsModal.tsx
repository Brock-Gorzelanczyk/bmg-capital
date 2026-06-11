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
  { key: "SMA_20",      label: "Simple Moving Average",          params: "20",      color: "#f59e0b", category: "Moving Averages" },
  { key: "SMA_50",      label: "Simple Moving Average",          params: "50",      color: "#3b82f6", category: "Moving Averages" },
  { key: "SMA_200",     label: "Simple Moving Average",          params: "200",     color: "#8b5cf6", category: "Moving Averages" },
  { key: "EMA_20",      label: "Exponential Moving Average",     params: "20",      color: "#fbbf24", category: "Moving Averages" },
  { key: "EMA_50",      label: "Exponential Moving Average",     params: "50",      color: "#60a5fa", category: "Moving Averages" },
  { key: "EMA_200",     label: "Exponential Moving Average",     params: "200",     color: "#a78bfa", category: "Moving Averages" },
  { key: "DEMA_20",     label: "Double Exponential Moving Avg",  params: "20",      color: "#f472b6", category: "Moving Averages" },
  { key: "VWAP",        label: "Volume Weighted Average Price",  params: "",        color: "#06b6d4", category: "Moving Averages" },
  // Other MAs (new)
  { key: "WMA_10",      label: "Weighted Moving Average",        params: "10",      color: "#34d399", category: "Other MAs" },
  { key: "WMA_20",      label: "Weighted Moving Average",        params: "20",      color: "#10b981", category: "Other MAs" },
  { key: "WMA_50",      label: "Weighted Moving Average",        params: "50",      color: "#059669", category: "Other MAs" },
  { key: "KAMA_10",     label: "Kaufman Adaptive MA",            params: "10",      color: "#f87171", category: "Other MAs" },
  { key: "TEMA_20",     label: "Triple Exponential Moving Avg",  params: "20",      color: "#fb923c", category: "Other MAs" },
  { key: "HMA_20",      label: "Hull Moving Average",            params: "20",      color: "#facc15", category: "Other MAs" },
  { key: "TRIX_15",     label: "TRIX",                           params: "15",      color: "#a3e635", category: "Other MAs" },
  // Trend
  { key: "ADX",         label: "Average Directional Index",      params: "14",      color: "#fbbf24", category: "Trend" },
  { key: "ICHIMOKU",    label: "Ichimoku Cloud",                 params: "",        color: "#26a69a", category: "Trend" },
  { key: "PSAR",        label: "Parabolic SAR",                  params: "",        color: "#9c27b0", category: "Trend" },
  { key: "AROON",       label: "Aroon",                          params: "25",      color: "#22d3ee", category: "Trend" },
  { key: "DPO",         label: "Detrended Price Oscillator",     params: "20",      color: "#818cf8", category: "Trend" },
  { key: "MASS",        label: "Mass Index",                     params: "9,25",    color: "#c084fc", category: "Trend" },
  { key: "KST",         label: "Know Sure Thing",                params: "",        color: "#fb7185", category: "Trend" },
  { key: "VORTEX",      label: "Vortex Indicator",               params: "14",      color: "#4ade80", category: "Trend" },
  { key: "STC",         label: "Schaff Trend Cycle",             params: "",        color: "#38bdf8", category: "Trend" },
  // Oscillators
  { key: "RSI_14",      label: "Relative Strength Index",        params: "14",      color: "#4ade80", category: "Oscillators" },
  { key: "MACD",        label: "MACD",                           params: "12,26,9", color: "#ec4899", category: "Oscillators" },
  { key: "STOCH",       label: "Stochastic",                     params: "14,3,3",  color: "#f97316", category: "Oscillators" },
  { key: "WILLR",       label: "Williams %R",                    params: "14",      color: "#14b8a6", category: "Oscillators" },
  { key: "CCI",         label: "CCI",                            params: "20",      color: "#e879f9", category: "Oscillators" },
  { key: "ROC",         label: "Rate of Change",                 params: "12",      color: "#fb923c", category: "Oscillators" },
  { key: "AO",          label: "Awesome Oscillator",             params: "",        color: "#4ade80", category: "Oscillators" },
  { key: "UO",          label: "Ultimate Oscillator",            params: "",        color: "#60a5fa", category: "Oscillators" },
  { key: "PPO",         label: "Percentage Price Oscillator",    params: "",        color: "#f472b6", category: "Oscillators" },
  { key: "TSI",         label: "True Strength Index",            params: "",        color: "#a78bfa", category: "Oscillators" },
  { key: "CMO",         label: "Chande Momentum Oscillator",     params: "14",      color: "#fde047", category: "Oscillators" },
  { key: "FISHER",      label: "Fisher Transform",               params: "9",       color: "#34d399", category: "Oscillators" },
  { key: "COPPOCK",     label: "Coppock Curve",                  params: "",        color: "#f87171", category: "Oscillators" },
  // Volatility
  { key: "BB_20",       label: "Bollinger Bands",                params: "20,2",    color: "#71717A", category: "Volatility" },
  { key: "ATR",         label: "Average True Range",             params: "14",      color: "#52525B", category: "Volatility" },
  { key: "DONCHIAN",    label: "Donchian Channel",               params: "",        color: "#607d8b", category: "Volatility" },
  { key: "KELTNER",     label: "Keltner Channel",                params: "",        color: "#ff9800", category: "Volatility" },
  { key: "UI",          label: "Ulcer Index",                    params: "14",      color: "#94a3b8", category: "Volatility" },
  { key: "BBWIDTH",     label: "Bollinger Band Width",           params: "20",      color: "#7dd3fc", category: "Volatility" },
  { key: "BBP",         label: "Bollinger %B",                   params: "20",      color: "#86efac", category: "Volatility" },
  { key: "NATR",        label: "Normalized ATR",                 params: "14",      color: "#d4d4d8", category: "Volatility" },
  { key: "HV",          label: "Historical Volatility",          params: "20",      color: "#fca5a5", category: "Volatility" },
  { key: "RVI_VOL",     label: "Relative Volatility Index",      params: "14",      color: "#c4b5fd", category: "Volatility" },
  // Volume
  { key: "OBV",         label: "On Balance Volume",              params: "",        color: "#fbbf24", category: "Volume" },
  { key: "CMF",         label: "Chaikin Money Flow",             params: "20",      color: "#06b6d4", category: "Volume" },
  { key: "MFI",         label: "Money Flow Index",               params: "14",      color: "#a78bfa", category: "Volume" },
  { key: "ADI",         label: "Accumulation/Distribution",      params: "",        color: "#4ade80", category: "Volume" },
  { key: "EOM",         label: "Ease of Movement",               params: "",        color: "#38bdf8", category: "Volume" },
  { key: "FI",          label: "Force Index",                    params: "13",      color: "#f87171", category: "Volume" },
  { key: "NVI",         label: "Negative Volume Index",          params: "",        color: "#d946ef", category: "Volume" },
  { key: "PVI",         label: "Positive Volume Index",          params: "",        color: "#22c55e", category: "Volume" },
  { key: "VWAP_BANDS",  label: "VWAP Bands",                     params: "±1σ",     color: "#67e8f9", category: "Volume" },
  // Statistics
  { key: "ZSCORE",      label: "Z-Score",                        params: "20",      color: "#fb923c", category: "Statistics" },
  { key: "LINREG",      label: "Linear Regression",              params: "14",      color: "#e2e8f0", category: "Statistics" },
  { key: "LINREG_SLOPE",label: "Linear Regression Slope",        params: "14",      color: "#94a3b8", category: "Statistics" },
  { key: "MOMENTUM_10", label: "Momentum",                       params: "10",      color: "#fde68a", category: "Statistics" },
];

const CATEGORIES = ["Moving Averages", "Other MAs", "Trend", "Oscillators", "Volatility", "Volume", "Statistics"];

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
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-xl shadow-2xl w-[480px] max-h-[70vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border-subtle)]">
          <Search size={15} className="text-[var(--text-tertiary)] shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search indicators..."
            className="flex-1 bg-transparent text-[var(--text-primary)] text-sm placeholder:text-[var(--text-tertiary)] focus:outline-none"
          />
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)]">
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-2 py-2">
          {filtered ? (
            filtered.length === 0 ? (
              <p className="text-center text-[var(--text-tertiary)] text-sm py-8">No indicators found</p>
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
                  <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-widest px-2 mb-1">{cat}</p>
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
        <div className="border-t border-[var(--border-subtle)] px-4 py-2 flex items-center justify-between">
          <span className="text-xs text-[var(--text-tertiary)]">{active.size} active</span>
          {active.size > 0 && (
            <button onClick={() => onChange(new Set())} className="text-xs text-[var(--accent-negative)] hover:opacity-80">
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
        "w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--bg-elevated-2)] transition-colors text-left",
        active && "bg-[var(--bg-elevated-2)]"
      )}
    >
      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: ind.color }} />
      <div className="flex-1 min-w-0">
        <span className="text-sm text-[var(--text-primary)]">{ind.label}</span>
        {ind.params && (
          <span className="text-xs text-[var(--text-tertiary)] ml-1.5">({ind.params})</span>
        )}
      </div>
      <span className={cn(
        "text-xs font-medium px-2 py-0.5 rounded border transition-colors",
        active
          ? "border-[var(--accent-positive)]/30 text-[var(--accent-positive)] bg-[var(--accent-positive-bg)]"
          : "border-[var(--border-subtle)] text-[var(--text-tertiary)]"
      )}>
        {active ? "On" : "Add"}
      </span>
    </button>
  );
}

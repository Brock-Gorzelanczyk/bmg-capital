import { cn } from "@/lib/utils";

const OVERLAY_INDICATORS = [
  { key: "SMA_20", label: "SMA 20", color: "#f59e0b" },
  { key: "SMA_50", label: "SMA 50", color: "#3b82f6" },
  { key: "SMA_200", label: "SMA 200", color: "#8b5cf6" },
  { key: "EMA_20", label: "EMA 20", color: "#fbbf24" },
  { key: "EMA_50", label: "EMA 50", color: "#60a5fa" },
  { key: "EMA_200", label: "EMA 200", color: "#a78bfa" },
  { key: "VWAP", label: "VWAP", color: "#06b6d4" },
  { key: "BB_20", label: "BB", color: "#94a3b8" },
];

const OSCILLATOR_INDICATORS = [
  { key: "RSI_14", label: "RSI", color: "#22c55e" },
  { key: "MACD", label: "MACD", color: "#ec4899" },
  { key: "STOCH", label: "Stoch", color: "#f97316" },
  { key: "WILLR", label: "W%R", color: "#14b8a6" },
  { key: "CCI", label: "CCI", color: "#e879f9" },
  { key: "OBV", label: "OBV", color: "#fbbf24" },
];

interface Props {
  active: Set<string>;
  onChange: (active: Set<string>) => void;
}

function IndicatorButton({ indicatorKey, label, color, active, onClick }: {
  indicatorKey: string;
  label: string;
  color: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-2 py-1 text-xs rounded border transition-colors",
        active
          ? "border-transparent text-[var(--text-primary)]"
          : "bg-zinc-950 border-zinc-800 text-zinc-500 hover:text-zinc-300 hover:border-zinc-600"
      )}
      style={active ? { backgroundColor: color + "33", borderColor: color, color } : {}}
    >
      {label}
    </button>
  );
}

export default function IndicatorToggle({ active, onChange }: Props) {
  const toggle = (key: string) => {
    const next = new Set(active);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  };

  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 items-center">
      <div className="flex flex-wrap gap-1">
        {OVERLAY_INDICATORS.map(({ key, label, color }) => (
          <IndicatorButton key={key} indicatorKey={key} label={label} color={color} active={active.has(key)} onClick={() => toggle(key)} />
        ))}
      </div>
      <div className="w-px h-4 bg-zinc-800 hidden sm:block" />
      <div className="flex flex-wrap gap-1">
        {OSCILLATOR_INDICATORS.map(({ key, label, color }) => (
          <IndicatorButton key={key} indicatorKey={key} label={label} color={color} active={active.has(key)} onClick={() => toggle(key)} />
        ))}
      </div>
    </div>
  );
}

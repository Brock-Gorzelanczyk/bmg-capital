import { cn } from "@/lib/utils";
import { formatCurrency, formatVolume } from "@/lib/utils";

export type Period = "1D" | "5D" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "3Y" | "5Y" | "10Y" | "15Y" | "All";

export interface PeriodConfig {
  timeframe: string;
  getStart: () => string | undefined;
}

export const PERIOD_CONFIGS: Record<Period, PeriodConfig> = {
  "1D":  { timeframe: "5Min",   getStart: () => new Date().toISOString().slice(0, 10) },
  "5D":  { timeframe: "15Min",  getStart: () => { const d = new Date(); d.setDate(d.getDate() - 5); return d.toISOString().slice(0, 10); } },
  "1M":  { timeframe: "1Hour",  getStart: () => { const d = new Date(); d.setMonth(d.getMonth() - 1); return d.toISOString().slice(0, 10); } },
  "3M":  { timeframe: "1Day",   getStart: () => { const d = new Date(); d.setMonth(d.getMonth() - 3); return d.toISOString().slice(0, 10); } },
  "6M":  { timeframe: "1Day",   getStart: () => { const d = new Date(); d.setMonth(d.getMonth() - 6); return d.toISOString().slice(0, 10); } },
  "YTD": { timeframe: "1Day",   getStart: () => `${new Date().getFullYear()}-01-01` },
  "1Y":  { timeframe: "1Day",   getStart: () => { const d = new Date(); d.setFullYear(d.getFullYear() - 1); return d.toISOString().slice(0, 10); } },
  "3Y":  { timeframe: "1Week",  getStart: () => { const d = new Date(); d.setFullYear(d.getFullYear() - 3); return d.toISOString().slice(0, 10); } },
  "5Y":  { timeframe: "1Week",  getStart: () => { const d = new Date(); d.setFullYear(d.getFullYear() - 5); return d.toISOString().slice(0, 10); } },
  "10Y": { timeframe: "1Week",  getStart: () => { const d = new Date(); d.setFullYear(d.getFullYear() - 10); return d.toISOString().slice(0, 10); } },
  "15Y": { timeframe: "1Week",  getStart: () => { const d = new Date(); d.setFullYear(d.getFullYear() - 15); return d.toISOString().slice(0, 10); } },
  "All": { timeframe: "1Month", getStart: () => undefined },
};

const PERIODS: Period[] = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "10Y", "15Y", "All"];

const TF_LABEL: Record<string, string> = {
  "5Min": "5m", "15Min": "15m", "1Hour": "1H", "1Day": "D", "1Week": "W",
};

interface Props {
  period: Period;
  onPeriodChange: (p: Period) => void;
  symbol: string;
  displayPrice?: number;
  displayVolume?: number;
  drawingCount?: number;
}

export default function TvBottomBar({
  period, onPeriodChange, symbol, displayPrice, displayVolume, drawingCount,
}: Props) {
  const tfLabel = TF_LABEL[PERIOD_CONFIGS[period].timeframe] ?? PERIOD_CONFIGS[period].timeframe;

  return (
    <div className="h-8 border-t border-[#2a2e39] bg-[#131722] flex items-center shrink-0 select-none overflow-hidden">
      {/* Scrollable period buttons */}
      <div className="flex items-center gap-0.5 px-2 overflow-x-auto scrollbar-none flex-shrink-0" style={{ scrollbarWidth: "none" }}>
        {PERIODS.map((p) => (
          <button
            key={p}
            onClick={() => onPeriodChange(p)}
            className={cn(
              "h-5 px-1.5 rounded text-[11px] font-medium transition-colors whitespace-nowrap shrink-0",
              period === p
                ? "bg-[#2962ff] text-[var(--text-primary)]"
                : "text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#1e222d]"
            )}
          >
            {p}
          </button>
        ))}
      </div>
      <div className="w-px h-4 bg-[#2a2e39] mx-1.5 shrink-0" />
      <span className="text-[10px] text-[#4a4e5b] font-mono shrink-0">{tfLabel}</span>
      <div className="flex-1 min-w-0" />
      <div className="flex items-center gap-2 px-2 shrink-0">
        <span className="text-[10px] text-[#4a4e5b]">{symbol}</span>
        {displayPrice != null && (
          <span className="text-[10px] text-[#787b86]">{formatCurrency(displayPrice)}</span>
        )}
        {displayVolume != null && (
          <span className="text-[10px] text-[#4a4e5b] hidden sm:inline">Vol {formatVolume(displayVolume)}</span>
        )}
        {drawingCount != null && drawingCount > 0 && (
          <span className="text-[10px] text-[#4a4e5b] hidden sm:inline">
            {drawingCount} drawing{drawingCount !== 1 ? "s" : ""}
          </span>
        )}
      </div>
    </div>
  );
}

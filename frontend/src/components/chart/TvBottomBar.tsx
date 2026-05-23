import { cn } from "@/lib/utils";
import { formatCurrency, formatVolume } from "@/lib/utils";

export type Period = "1D" | "5D" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "5Y" | "All";

export interface PeriodConfig {
  timeframe: string;
  getStart: () => string | undefined;
}

export const PERIOD_CONFIGS: Record<Period, PeriodConfig> = {
  "1D":  { timeframe: "5Min",  getStart: () => new Date().toISOString().slice(0, 10) },
  "5D":  { timeframe: "15Min", getStart: () => { const d = new Date(); d.setDate(d.getDate() - 5); return d.toISOString().slice(0, 10); } },
  "1M":  { timeframe: "1Hour", getStart: () => { const d = new Date(); d.setMonth(d.getMonth() - 1); return d.toISOString().slice(0, 10); } },
  "3M":  { timeframe: "1Day",  getStart: () => { const d = new Date(); d.setMonth(d.getMonth() - 3); return d.toISOString().slice(0, 10); } },
  "6M":  { timeframe: "1Day",  getStart: () => { const d = new Date(); d.setMonth(d.getMonth() - 6); return d.toISOString().slice(0, 10); } },
  "YTD": { timeframe: "1Day",  getStart: () => `${new Date().getFullYear()}-01-01` },
  "1Y":  { timeframe: "1Day",  getStart: () => { const d = new Date(); d.setFullYear(d.getFullYear() - 1); return d.toISOString().slice(0, 10); } },
  "5Y":  { timeframe: "1Week", getStart: () => { const d = new Date(); d.setFullYear(d.getFullYear() - 5); return d.toISOString().slice(0, 10); } },
  "All": { timeframe: "1Week", getStart: () => undefined },
};

const PERIODS: Period[] = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "All"];

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
    <div className="h-8 border-t border-[#2a2e39] bg-[#131722] flex items-center px-3 gap-0.5 shrink-0 select-none">
      {PERIODS.map((p) => (
        <button
          key={p}
          onClick={() => onPeriodChange(p)}
          className={cn(
            "h-5 px-2 rounded text-[11px] font-medium transition-colors",
            period === p
              ? "bg-[#2962ff] text-white"
              : "text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#1e222d]"
          )}
        >
          {p}
        </button>
      ))}
      <div className="w-px h-4 bg-[#2a2e39] mx-2" />
      <span className="text-[10px] text-[#4a4e5b] font-mono">{tfLabel}</span>
      <div className="flex-1" />
      <span className="text-[10px] text-[#4a4e5b]">{symbol}</span>
      {displayPrice != null && (
        <span className="text-[10px] text-[#787b86] ml-3">{formatCurrency(displayPrice)}</span>
      )}
      {displayVolume != null && (
        <span className="text-[10px] text-[#4a4e5b] ml-2">Vol {formatVolume(displayVolume)}</span>
      )}
      {drawingCount != null && drawingCount > 0 && (
        <span className="text-[10px] text-[#4a4e5b] ml-3">
          {drawingCount} drawing{drawingCount !== 1 ? "s" : ""}
        </span>
      )}
    </div>
  );
}

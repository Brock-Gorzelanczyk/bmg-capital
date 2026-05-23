import { cn } from "@/lib/utils";

const TIMEFRAMES = ["1Min", "5Min", "15Min", "1Hour", "4Hour", "1Day", "1Week"];

interface Props {
  value: string;
  onChange: (tf: string) => void;
}

export default function TimeframeSelector({ value, onChange }: Props) {
  return (
    <div className="flex gap-1">
      {TIMEFRAMES.map((tf) => (
        <button
          key={tf}
          onClick={() => onChange(tf)}
          className={cn(
            "px-2 py-1 text-xs rounded font-medium transition-colors",
            value === tf
              ? "bg-white text-black font-semibold"
              : "bg-transparent border border-zinc-800 text-zinc-500 hover:border-zinc-500 hover:text-white"
          )}
        >
          {tf}
        </button>
      ))}
    </div>
  );
}

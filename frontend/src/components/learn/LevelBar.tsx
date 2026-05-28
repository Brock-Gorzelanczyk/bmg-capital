import { xpProgressInLevel } from "@/types/learn";
import { cn } from "@/lib/utils";

interface Props {
  xp: number;
  className?: string;
  compact?: boolean;
}

export default function LevelBar({ xp, className, compact }: Props) {
  const { level, pct, needed, floor } = xpProgressInLevel(xp);

  if (compact) {
    return (
      <div className={cn("flex items-center gap-2", className)}>
        <span className="text-xs font-bold text-[var(--text-primary)]">Lv {level}</span>
        <div className="flex-1 h-1.5 bg-[#334155] rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400 rounded-full transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-[10px] text-[var(--text-tertiary)]">{needed} XP</span>
      </div>
    );
  }

  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-[var(--text-primary)]">Level {level}</span>
        <span className="text-xs text-[var(--text-secondary)]">{xp.toLocaleString()} XP · {needed.toLocaleString()} to next</span>
      </div>
      <div className="h-2 bg-[#334155] rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400 rounded-full transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

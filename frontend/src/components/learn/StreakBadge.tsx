import { Flame } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  streak: number;
  className?: string;
  size?: "sm" | "md";
}

export default function StreakBadge({ streak, className, size = "md" }: Props) {
  const hot = streak >= 3;

  if (size === "sm") {
    return (
      <div className={cn("flex items-center gap-1", className)}>
        <Flame
          size={13}
          className={hot ? "text-orange-400" : "text-[var(--text-tertiary)]"}
          fill={hot ? "#fb923c" : "none"}
        />
        <span className={cn("text-xs font-semibold", hot ? "text-orange-400" : "text-[var(--text-tertiary)]")}>
          {streak}
        </span>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-sm font-semibold",
        hot
          ? "bg-orange-500/10 border-orange-500/20 text-orange-400"
          : "bg-[var(--bg-elevated-2)] border-[var(--border-emphasis)] text-[var(--text-tertiary)]",
        className
      )}
    >
      <Flame
        size={15}
        className={hot ? "text-orange-400" : "text-[var(--text-tertiary)]"}
        fill={hot ? "#fb923c" : "none"}
      />
      <span>{streak} day{streak !== 1 ? "s" : ""}</span>
    </div>
  );
}

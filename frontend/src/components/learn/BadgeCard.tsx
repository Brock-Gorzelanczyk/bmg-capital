import { BADGE_META } from "@/types/learn";
import { cn } from "@/lib/utils";

interface Props {
  badgeId: string;
  earned?: boolean;
  earnedAt?: string;
  size?: "sm" | "md";
}

export default function BadgeCard({ badgeId, earned = true, earnedAt, size = "md" }: Props) {
  const meta = BADGE_META[badgeId];
  if (!meta) return null;

  if (size === "sm") {
    return (
      <div
        title={`${meta.label}: ${meta.description}${earnedAt ? ` · Earned ${new Date(earnedAt).toLocaleDateString()}` : ""}`}
        className={cn(
          "w-10 h-10 rounded-xl flex items-center justify-center text-xl border transition-opacity",
          earned ? "bg-[var(--bg-elevated-2)] border-[var(--border-emphasis)]" : "bg-[var(--bg-elevated)] border-[var(--border-subtle)] opacity-40"
        )}
      >
        {meta.icon}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex items-center gap-3 p-3 rounded-xl border",
        earned ? "bg-[var(--bg-elevated-2)] border-[var(--border-emphasis)]" : "bg-[var(--bg-elevated)] border-[var(--border-subtle)] opacity-50"
      )}
    >
      <div className="w-10 h-10 rounded-xl bg-[#020617] flex items-center justify-center text-xl shrink-0">
        {meta.icon}
      </div>
      <div className="min-w-0">
        <p className={cn("text-sm font-semibold truncate", earned ? "text-[var(--text-primary)]" : "text-[var(--text-tertiary)]")}>
          {meta.label}
        </p>
        <p className="text-xs text-[var(--text-tertiary)] truncate">{meta.description}</p>
        {earned && earnedAt && (
          <p className="text-[10px] text-[var(--text-tertiary)] mt-0.5">
            {new Date(earnedAt).toLocaleDateString()}
          </p>
        )}
      </div>
    </div>
  );
}

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
          earned ? "bg-[#1E293B] border-[#334155]" : "bg-[#0F172A] border-[#1E293B] opacity-40"
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
        earned ? "bg-[#1E293B] border-[#334155]" : "bg-[#0F172A] border-[#1E293B] opacity-50"
      )}
    >
      <div className="w-10 h-10 rounded-xl bg-[#020617] flex items-center justify-center text-xl shrink-0">
        {meta.icon}
      </div>
      <div className="min-w-0">
        <p className={cn("text-sm font-semibold truncate", earned ? "text-white" : "text-[#475569]")}>
          {meta.label}
        </p>
        <p className="text-xs text-[#475569] truncate">{meta.description}</p>
        {earned && earnedAt && (
          <p className="text-[10px] text-[#475569] mt-0.5">
            {new Date(earnedAt).toLocaleDateString()}
          </p>
        )}
      </div>
    </div>
  );
}

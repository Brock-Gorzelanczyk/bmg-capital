import type { BotSnap } from "@/api/portfolioSnapshot";

export interface BotBadge {
  variant: "green" | "amber" | "gray";
  text: string;
  subtitle?: string;
}

export function botStatusBadge(bot: Pick<BotSnap, "status">): BotBadge {
  switch (bot.status) {
    case "admin_locked":
    case "disabled":
      return { variant: "amber", text: "DISABLED", subtitle: "frozen · historical" };
    case "paused":
      return { variant: "gray", text: "PAUSED" };
    case "active":
      return { variant: "green", text: "ACTIVE" };
    default:
      return { variant: "gray", text: "UNKNOWN" };
  }
}

// CSS classes for each variant (Tailwind)
export const BADGE_CLASSES: Record<BotBadge["variant"], string> = {
  green: "bg-lime-500/15 text-lime-400 border-lime-500/30",
  amber: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  gray:  "bg-zinc-800 text-zinc-500 border-zinc-700",
};

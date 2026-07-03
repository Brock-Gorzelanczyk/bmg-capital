/**
 * Regime label pretty-print + color helpers.
 *
 * Backend emits snake_case regime tags (e.g. "bull_trending"). Anywhere
 * these leak to the UI without formatting looks like a dev forgot a
 * mapping step — item #9 from Brock's 2026-07-03 audit.
 */

export interface RegimeStyle {
  label: string;
  emoji: string;
  color: string; // Tailwind color class for the label text
  bg: string;    // Tailwind bg class for a pill
}

const REGIME_MAP: Record<string, RegimeStyle> = {
  bull_trending: {
    label: "Bull Trending",
    emoji: "🟢",
    color: "text-[#4ade80]",
    bg: "bg-[#4ade80]/10 border border-[#4ade80]/30",
  },
  bear_trending: {
    label: "Bear Trending",
    emoji: "🔴",
    color: "text-[#f87171]",
    bg: "bg-[#f87171]/10 border border-[#f87171]/30",
  },
  choppy: {
    label: "Choppy / Range",
    emoji: "🟡",
    color: "text-[#facc15]",
    bg: "bg-[#facc15]/10 border border-[#facc15]/30",
  },
  range_bound: {
    label: "Range Bound",
    emoji: "🟡",
    color: "text-[#facc15]",
    bg: "bg-[#facc15]/10 border border-[#facc15]/30",
  },
  high_volatility: {
    label: "High Volatility",
    emoji: "🟠",
    color: "text-[#fb923c]",
    bg: "bg-[#fb923c]/10 border border-[#fb923c]/30",
  },
  low_vol: {
    label: "Low Volatility",
    emoji: "🔵",
    color: "text-[#60a5fa]",
    bg: "bg-[#60a5fa]/10 border border-[#60a5fa]/30",
  },
  crisis: {
    label: "Crisis",
    emoji: "🚨",
    color: "text-[#f87171]",
    bg: "bg-[#f87171]/20 border border-[#f87171]/50",
  },
  any: {
    label: "Any Regime",
    emoji: "⚪",
    color: "text-t-muted",
    bg: "bg-t-bg1 border border-t-dim",
  },
  unknown: {
    label: "Unknown",
    emoji: "⚫",
    color: "text-t-muted",
    bg: "bg-t-bg1 border border-t-dim",
  },
};

export function regimeStyle(raw: string | null | undefined): RegimeStyle {
  if (!raw) return REGIME_MAP.unknown;
  const key = raw.toLowerCase().trim();
  if (REGIME_MAP[key]) return REGIME_MAP[key];
  // Best-effort title-case fallback for unknown values.
  const words = key.split(/[_-]/).map((w) => (w ? w[0].toUpperCase() + w.slice(1) : ""));
  return {
    label: words.join(" ") || raw,
    emoji: "⚫",
    color: "text-t-muted",
    bg: "bg-t-bg1 border border-t-dim",
  };
}

/** Convenience — just the label. */
export function regimeLabel(raw: string | null | undefined): string {
  return regimeStyle(raw).label;
}

import { cn } from "@/lib/utils";

type BadgeVariant =
  | "active"
  | "paused"
  | "disabled"
  | "candidate"    // T0
  | "probation"    // T1
  | "production"   // T2
  | "core"         // T3
  | "stock"
  | "crypto"
  | "quant"
  | "options"
  | "multi"
  | "live"
  | "paper"
  | "default";

interface BadgeProps {
  variant?: BadgeVariant;
  children?: React.ReactNode;
  className?: string;
  size?: "xs" | "sm";
}

const VARIANT_STYLES: Record<BadgeVariant, string> = {
  active:     "text-t-green border-t-mid bg-t-green/10",
  paused:     "text-t-mid2 border-t-dim bg-t-bg2",
  disabled:   "text-t-muted border-t-dim/50 bg-t-bg1",
  candidate:  "text-t-amber border-amber-500/30 bg-amber-500/10",
  probation:  "text-yellow-400 border-yellow-500/30 bg-yellow-500/10",
  production: "text-blue-400 border-blue-500/30 bg-blue-500/10",
  core:       "text-t-green border-t-mid bg-t-green/10",
  stock:      "text-sky-400 border-sky-500/30 bg-sky-500/10",
  crypto:     "text-orange-400 border-orange-500/30 bg-orange-500/10",
  quant:      "text-violet-400 border-violet-500/30 bg-violet-500/10",
  options:    "text-pink-400 border-pink-500/30 bg-pink-500/10",
  multi:      "text-t-cyan border-cyan-500/30 bg-cyan-500/10",
  live:       "text-t-green border-t-mid bg-t-green/10",
  paper:      "text-t-amber border-amber-500/30 bg-amber-500/10",
  default:    "text-t-mid2 border-t-dim bg-t-bg2",
};

const LABELS: Partial<Record<BadgeVariant, string>> = {
  active:     "ACTIVE",
  paused:     "PAUSED",
  disabled:   "DISABLED",
  candidate:  "T0 CANDIDATE",
  probation:  "T1 PROBATION",
  production: "T2 PRODUCTION",
  core:       "T3 CORE",
  stock:      "STOCK",
  crypto:     "CRYPTO",
  quant:      "QUANT",
  options:    "OPTIONS",
  multi:      "MULTI",
  live:       "LIVE",
  paper:      "PAPER",
};

export function Badge({ variant = "default", children, className, size = "xs" }: BadgeProps) {
  const text = children ?? LABELS[variant] ?? String(variant).toUpperCase();
  return (
    <span
      className={cn(
        "inline-flex items-center font-mono-t font-bold border rounded-full",
        size === "xs" ? "text-[9px] px-1.5 py-0.5 tracking-wide" : "text-[11px] px-2 py-0.5 tracking-widest",
        VARIANT_STYLES[variant],
        className,
      )}
    >
      {text}
    </span>
  );
}

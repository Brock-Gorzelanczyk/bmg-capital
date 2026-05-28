import { cn } from "@/lib/utils";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "destructive";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const variantCls: Record<Variant, string> = {
  primary:
    "bg-[var(--accent-positive)] text-[#0a0a0a] font-semibold hover:brightness-110 active:brightness-95 shadow-sm",
  secondary:
    "bg-[var(--bg-elevated-2)] text-[var(--text-primary)] border border-[var(--border-emphasis)] hover:bg-[#52525B] active:bg-[var(--bg-elevated-2)]",
  ghost:
    "bg-transparent text-[var(--text-secondary)] hover:bg-[var(--bg-elevated-2)] hover:text-[var(--text-primary)] active:bg-[var(--bg-elevated)]",
  destructive:
    "bg-[var(--accent-negative-bg)] text-[var(--accent-negative)] border border-[var(--accent-negative)]/20 hover:bg-[var(--accent-negative)]/20 active:bg-[var(--accent-negative-bg)]",
};

const sizeCls: Record<Size, string> = {
  sm: "h-7 px-3 text-xs gap-1.5",
  md: "h-9 px-4 text-sm gap-2",
  lg: "h-11 px-5 text-base gap-2.5",
};

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  disabled,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center rounded-lg font-medium",
        "transition-all duration-[150ms]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-positive)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-base)]",
        "disabled:opacity-40 disabled:pointer-events-none",
        "active:scale-[0.97]",
        variantCls[variant],
        sizeCls[size],
        className
      )}
      {...props}
    >
      {loading ? (
        <span className="h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
      ) : (
        children
      )}
    </button>
  );
}

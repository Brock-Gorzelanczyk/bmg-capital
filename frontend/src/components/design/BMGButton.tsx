import { cn } from "@/lib/utils";
import type { ButtonHTMLAttributes } from "react";

type BMGVariant = "primary" | "secondary" | "destructive";
type BMGSize = "sm" | "md" | "lg";

interface BMGButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: BMGVariant;
  size?: BMGSize;
  loading?: boolean;
}

const variantCls: Record<BMGVariant, string> = {
  primary: [
    "border border-[var(--bmg-green)]/40 text-[var(--bmg-green)]",
    "hover:border-[var(--bmg-green)] hover:bg-[var(--bmg-green)]/10",
    "hover:shadow-[0_0_12px_var(--bmg-green-glow)]",
  ].join(" "),
  secondary: [
    "border border-[var(--bmg-text-muted)]/40 text-[var(--bmg-text-muted)]",
    "hover:border-[var(--bmg-text-muted)] hover:text-[var(--bmg-text)]",
  ].join(" "),
  destructive: [
    "border border-[var(--bmg-red)]/40 text-[var(--bmg-red)]",
    "hover:border-[var(--bmg-red)] hover:bg-[var(--bmg-red)]/10",
    "hover:shadow-[0_0_12px_var(--bmg-red-glow)]",
  ].join(" "),
};

const sizeCls: Record<BMGSize, string> = {
  sm: "h-7 px-3 text-[10px] tracking-[0.12em]",
  md: "h-9 px-4 text-xs tracking-[0.18em]",
  lg: "h-11 px-5 text-sm tracking-[0.2em]",
};

export function BMGButton({
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  className,
  children,
  ...props
}: BMGButtonProps) {
  return (
    <button
      disabled={disabled || loading}
      className={cn(
        "relative overflow-hidden inline-flex items-center justify-center",
        "font-mono uppercase rounded bg-transparent",
        "transition-all duration-300",
        "disabled:opacity-40 disabled:pointer-events-none",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--bmg-green)]/60",
        variantCls[variant],
        sizeCls[size],
        className
      )}
      {...props}
    >
      {variant === "primary" && (
        <span
          aria-hidden
          className="absolute inset-y-0 w-12 bg-gradient-to-r from-transparent via-[var(--bmg-green)]/20 to-transparent pointer-events-none"
          style={{ animation: "bmg-scan-btn 2.4s linear infinite" }}
        />
      )}
      {loading ? (
        <span className="h-3.5 w-3.5 rounded-full border-2 border-current border-t-transparent animate-spin" />
      ) : (
        children
      )}
    </button>
  );
}

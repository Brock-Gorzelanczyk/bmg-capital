/**
 * GlowButton — terminal-style button.
 * Variants: primary (green border, fill on hover), secondary, danger.
 * Replaces ad-hoc button styles across the app.
 */
import { cn } from "@/lib/utils";
import { forwardRef } from "react";

type GlowButtonVariant = "primary" | "secondary" | "danger" | "ghost";
type GlowButtonSize = "xs" | "sm" | "md" | "lg";

interface GlowButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: GlowButtonVariant;
  size?: GlowButtonSize;
  loading?: boolean;
  children: React.ReactNode;
}

const VARIANT: Record<GlowButtonVariant, string> = {
  primary: [
    "border-t-hot text-t-green",
    "hover:bg-t-green hover:text-t-bg0",
    "active:bg-t-green/80",
    "shadow-none hover:shadow-[0_0_18px_rgba(74,222,128,0.35)]",
  ].join(" "),
  secondary: [
    "border-t-mid text-t-mid2",
    "hover:border-t-hot hover:text-t-green",
    "active:bg-t-bg2",
  ].join(" "),
  danger: [
    "border-t-red text-t-red",
    "hover:bg-t-red hover:text-t-bg0",
    "active:bg-t-red/80",
    "shadow-none hover:shadow-[0_0_18px_rgba(248,113,113,0.35)]",
  ].join(" "),
  ghost: [
    "border-transparent text-t-mid2",
    "hover:text-t-hi hover:border-t-dim",
  ].join(" "),
};

const SIZE: Record<GlowButtonSize, string> = {
  xs: "h-6 px-2 text-[10px] tracking-widest",
  sm: "h-7 px-3 text-[11px] tracking-widest",
  md: "h-9 px-4 text-xs tracking-widest",
  lg: "h-11 px-6 text-sm tracking-widest",
};

export const GlowButton = forwardRef<HTMLButtonElement, GlowButtonProps>(
  ({ variant = "primary", size = "md", loading, children, className, disabled, ...props }, ref) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-1.5",
        "font-mono-t font-semibold uppercase",
        "border rounded-[4px]",
        "transition-all duration-150",
        "disabled:opacity-40 disabled:cursor-not-allowed",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...props}
    >
      {loading ? (
        <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
        </svg>
      ) : children}
    </button>
  ),
);
GlowButton.displayName = "GlowButton";

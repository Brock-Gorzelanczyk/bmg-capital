import { cn } from "@/lib/utils";
import type { HTMLAttributes } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "compact" | "flush";
  glow?: boolean;
}

export function Card({ variant = "default", glow = false, className, children, ...props }: CardProps) {
  return (
    <div
      className={cn(
        "relative rounded-xl border bg-[var(--bg-elevated)] shadow-card",
        "border-[var(--border-subtle)]",
        variant === "default" && "p-5",
        variant === "compact" && "p-3",
        variant === "flush" && "p-0 overflow-hidden",
        glow && "card-glow",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("flex items-center justify-between mb-4", className)} {...props}>
      {children}
    </div>
  );
}

export function CardTitle({ className, children, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn("text-sm font-semibold text-[var(--text-primary)] tracking-tight", className)}
      {...props}
    >
      {children}
    </h3>
  );
}

export function CardLabel({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)] mb-3",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

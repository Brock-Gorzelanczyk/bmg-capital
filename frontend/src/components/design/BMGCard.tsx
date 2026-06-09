import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

type Padding = "none" | "sm" | "md" | "lg";

interface BMGCardProps {
  children: ReactNode;
  className?: string;
  glow?: boolean;
  padding?: Padding;
}

const padCls: Record<Padding, string> = {
  none: "",
  sm: "p-3",
  md: "p-5",
  lg: "p-7",
};

export function BMGCard({
  children,
  className,
  glow = false,
  padding = "md",
}: BMGCardProps) {
  return (
    <div
      className={cn(
        "relative rounded-xl border",
        "bg-[var(--bmg-bg-card)] border-[var(--bmg-green-border)]",
        glow && "shadow-[0_0_20px_var(--bmg-green-glow)]",
        padCls[padding],
        className
      )}
    >
      {children}
    </div>
  );
}

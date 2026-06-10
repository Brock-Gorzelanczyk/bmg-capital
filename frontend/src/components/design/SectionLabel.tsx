import { cn } from "@/lib/utils";
import type { ElementType, ReactNode } from "react";

interface SectionLabelProps {
  children: ReactNode;
  className?: string;
  as?: ElementType;
  noPrefix?: boolean;
}

export function SectionLabel({
  children,
  className,
  as: Tag = "span",
  noPrefix = false,
}: SectionLabelProps) {
  const alreadyPrefixed = typeof children === "string" && children.startsWith("//");
  const showPrefix = !noPrefix && !alreadyPrefixed;
  return (
    <Tag
      className={cn(
        "font-mono text-[10px] tracking-[0.18em] uppercase",
        "text-[var(--bmg-text-label)]",
        className
      )}
    >
      {showPrefix && "// "}{children}
    </Tag>
  );
}

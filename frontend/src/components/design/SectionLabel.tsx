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
  const text = String(children);
  const label = noPrefix || text.startsWith("//") ? text : `// ${text}`;
  return (
    <Tag
      className={cn(
        "font-mono text-[10px] tracking-[0.18em] uppercase",
        "text-[var(--bmg-text-label)]",
        className
      )}
    >
      {label}
    </Tag>
  );
}

import { HelpCircle } from "lucide-react";
import { type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { defineTerm } from "@/lib/glossary";

interface TooltipProps {
  text: string;
  children: ReactNode;
  className?: string;
  /** Tooltip placement: 'top' (default) or 'bottom'. */
  side?: "top" | "bottom";
}

/** Pure-CSS hover tooltip. No popper, no portal — sits adjacent to the trigger.
 *
 *  Wraps any element. On hover the absolutely-positioned tooltip fades in.
 *  Uses Tailwind group-hover so the trigger doesn't need any state. */
export function Tooltip({ text, children, className, side = "top" }: TooltipProps) {
  return (
    <span className={cn("relative inline-flex group", className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute left-1/2 -translate-x-1/2 z-50",
          "opacity-0 group-hover:opacity-100 transition-opacity duration-150",
          "bg-t-bg2 border border-t-dim text-t-hi text-[11px] leading-snug",
          "px-2.5 py-1.5 rounded shadow-lg w-64 text-left",
          side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
        )}
      >
        {text}
      </span>
    </span>
  );
}

/** Small ⓘ icon next to a label that hovers to show the glossary definition
 *  for `term`. Use inline next to a metric: `Win Rate <HelpIcon term="win_rate" />`. */
export function HelpIcon({ term, size = 11 }: { term: string; size?: number }) {
  return (
    <Tooltip text={defineTerm(term)}>
      <HelpCircle
        size={size}
        className="inline text-t-muted/60 hover:text-t-mid2 transition-colors ml-1 cursor-help"
        aria-label={`Definition: ${term}`}
      />
    </Tooltip>
  );
}

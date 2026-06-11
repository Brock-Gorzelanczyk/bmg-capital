/**
 * CornerFrame — corner-bracket decoration wrapper.
 * Wraps the single most-important element on a page.
 * Identical to BracketFrame but uses terminal design tokens.
 */
import { cn } from "@/lib/utils";

interface CornerFrameProps {
  children: React.ReactNode;
  className?: string;
  bracketSize?: number;
  glow?: boolean;
}

export function CornerFrame({
  children,
  className,
  bracketSize = 14,
  glow = false,
}: CornerFrameProps) {
  const b = bracketSize;
  const corner = "absolute border-t-hot";
  return (
    <div
      className={cn("relative", glow && "drop-shadow-[0_0_18px_rgba(74,222,128,0.25)]", className)}
    >
      {/* top-left */}
      <span
        className={cn(corner, "top-0 left-0 border-t border-l")}
        style={{ width: b, height: b }}
      />
      {/* top-right */}
      <span
        className={cn(corner, "top-0 right-0 border-t border-r")}
        style={{ width: b, height: b }}
      />
      {/* bottom-left */}
      <span
        className={cn(corner, "bottom-0 left-0 border-b border-l")}
        style={{ width: b, height: b }}
      />
      {/* bottom-right */}
      <span
        className={cn(corner, "bottom-0 right-0 border-b border-r")}
        style={{ width: b, height: b }}
      />
      {children}
    </div>
  );
}

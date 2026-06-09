import { cn } from "@/lib/utils";
import type { CSSProperties, ReactNode } from "react";

interface BracketFrameProps {
  children: ReactNode;
  className?: string;
  glow?: boolean;
  bracketSize?: number;
}

export function BracketFrame({
  children,
  className,
  glow = false,
  bracketSize = 16,
}: BracketFrameProps) {
  const bracketStyle: CSSProperties = {
    width: bracketSize,
    height: bracketSize,
    position: "absolute",
    pointerEvents: "none",
  };
  const containerStyle: CSSProperties = glow
    ? { boxShadow: "0 0 20px var(--bmg-green-glow)" }
    : undefined!;

  return (
    <div className={cn("relative", className)} style={containerStyle}>
      {/* top-left */}
      <span
        style={{ ...bracketStyle, top: 0, left: 0, borderTop: "1.5px solid var(--bmg-green)", borderLeft: "1.5px solid var(--bmg-green)" }}
      />
      {/* top-right */}
      <span
        style={{ ...bracketStyle, top: 0, right: 0, borderTop: "1.5px solid var(--bmg-green)", borderRight: "1.5px solid var(--bmg-green)" }}
      />
      {/* bottom-left */}
      <span
        style={{ ...bracketStyle, bottom: 0, left: 0, borderBottom: "1.5px solid var(--bmg-green)", borderLeft: "1.5px solid var(--bmg-green)" }}
      />
      {/* bottom-right */}
      <span
        style={{ ...bracketStyle, bottom: 0, right: 0, borderBottom: "1.5px solid var(--bmg-green)", borderRight: "1.5px solid var(--bmg-green)" }}
      />
      {children}
    </div>
  );
}

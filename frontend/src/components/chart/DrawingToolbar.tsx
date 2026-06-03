import {
  Crosshair,
  Minus,
  TrendingUp,
  TrendingDown,
  Square,
  GitBranch,
  Type,
  AlignJustify,
  MoveUpRight,
  Ruler,
  Magnet,
  Eye,
  Trash2,
  MoveVertical,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { DrawingTool } from "@/types/chart";

const TOOLS: { tool: DrawingTool; Icon: React.ElementType; label: string }[] = [
  { tool: "cursor",   Icon: Crosshair,    label: "Cursor" },
  { tool: "trendline",Icon: TrendingUp,   label: "Trend Line" },
  { tool: "hline",    Icon: Minus,        label: "Horizontal Line" },
  { tool: "vline",    Icon: MoveVertical, label: "Vertical Line" },
  { tool: "channel",  Icon: AlignJustify, label: "Parallel Channel" },
  { tool: "fib",      Icon: GitBranch,    label: "Fibonacci Retracement" },
  { tool: "rect",     Icon: Square,       label: "Rectangle" },
  { tool: "text",     Icon: Type,         label: "Text" },
  { tool: "arrow",    Icon: MoveUpRight,  label: "Arrow" },
  { tool: "longpos",  Icon: TrendingUp,   label: "Long Position" },
  { tool: "shortpos", Icon: TrendingDown, label: "Short Position" },
];

interface Props {
  activeTool: DrawingTool;
  onChange: (tool: DrawingTool) => void;
  onClearAll: () => void;
}

export default function DrawingToolbar({ activeTool, onChange, onClearAll }: Props) {
  return (
    <div className="w-10 flex flex-col items-center pt-2 gap-0.5 border-r border-[var(--border-subtle)] bg-[var(--bg-elevated)] shrink-0">
      {TOOLS.map(({ tool, Icon, label }) => (
        <button
          key={tool}
          title={label}
          onClick={() => onChange(tool)}
          className={cn(
            "w-8 h-8 flex items-center justify-center rounded transition-colors",
            activeTool === tool
              ? "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)]"
              : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)]"
          )}
        >
          <Icon size={15} />
        </button>
      ))}

      <div className="w-6 border-t border-[var(--border-subtle)] my-1" />

      {/* Non-interactive helpers — visual parity with TradingView */}
      <button
        title="Ruler (measure)"
        disabled
        className="w-8 h-8 flex items-center justify-center rounded text-[var(--border-emphasis)] cursor-not-allowed"
      >
        <Ruler size={15} />
      </button>
      <button
        title="Snap to price (magnet)"
        disabled
        className="w-8 h-8 flex items-center justify-center rounded text-[var(--border-emphasis)] cursor-not-allowed"
      >
        <Magnet size={15} />
      </button>
      <button
        title="Show / hide all drawings"
        disabled
        className="w-8 h-8 flex items-center justify-center rounded text-[var(--border-emphasis)] cursor-not-allowed"
      >
        <Eye size={15} />
      </button>

      <div className="w-6 border-t border-[var(--border-subtle)] my-1" />

      <button
        title="Clear all drawings"
        onClick={onClearAll}
        className="w-8 h-8 flex items-center justify-center rounded text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] hover:bg-[var(--accent-negative-bg)] transition-colors"
      >
        <Trash2 size={15} />
      </button>
    </div>
  );
}

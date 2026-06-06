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
  { tool: "text",     Icon: Type,         label: "Text Label" },
  { tool: "arrow",    Icon: MoveUpRight,  label: "Arrow" },
  { tool: "longpos",  Icon: TrendingUp,   label: "Long Position" },
  { tool: "shortpos", Icon: TrendingDown, label: "Short Position" },
];

interface Props {
  activeTool: DrawingTool;
  onChange: (tool: DrawingTool) => void;
  onClearAll: () => void;
}

function ToolButton({
  icon: Icon,
  label,
  active = false,
  disabled = false,
  danger = false,
  onClick,
}: {
  icon: React.ElementType;
  label: string;
  active?: boolean;
  disabled?: boolean;
  danger?: boolean;
  onClick?: () => void;
}) {
  return (
    <div className="relative group/tooltip">
      <button
        onClick={onClick}
        disabled={disabled}
        className={cn(
          "w-8 h-8 flex items-center justify-center rounded transition-colors",
          disabled && "cursor-not-allowed text-[var(--border-emphasis)]",
          !disabled && danger && "text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] hover:bg-[var(--accent-negative-bg)]",
          !disabled && !danger && active && "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)]",
          !disabled && !danger && !active && "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)]",
        )}
      >
        <Icon size={15} />
      </button>

      {/* Tooltip — appears to the right, instant on hover */}
      <div
        className={cn(
          "pointer-events-none absolute left-full top-1/2 -translate-y-1/2 ml-2 z-50",
          "opacity-0 group-hover/tooltip:opacity-100 transition-opacity duration-100",
          "flex items-center gap-1",
        )}
      >
        {/* Arrow */}
        <div className="w-0 h-0 border-t-[5px] border-t-transparent border-b-[5px] border-b-transparent border-r-[6px] border-r-[#1e293b]" />
        {/* Label */}
        <div className="bg-[#1e293b] text-[var(--text-primary)] text-[11px] font-medium px-2 py-1 rounded whitespace-nowrap shadow-lg border border-[var(--border-subtle)]">
          {label}
        </div>
      </div>
    </div>
  );
}

export default function DrawingToolbar({ activeTool, onChange, onClearAll }: Props) {
  return (
    <div className="w-10 flex flex-col items-center pt-2 gap-0.5 border-r border-[var(--border-subtle)] bg-[var(--bg-elevated)] shrink-0">
      {TOOLS.map(({ tool, Icon, label }) => (
        <ToolButton
          key={tool}
          icon={Icon}
          label={label}
          active={activeTool === tool}
          onClick={() => onChange(tool)}
        />
      ))}

      <div className="w-6 border-t border-[var(--border-subtle)] my-1" />

      <ToolButton icon={Ruler}  label="Ruler (measure)"         disabled />
      <ToolButton icon={Magnet} label="Snap to Price (magnet)"  disabled />
      <ToolButton icon={Eye}    label="Show / Hide All Drawings" disabled />

      <div className="w-6 border-t border-[var(--border-subtle)] my-1" />

      <ToolButton icon={Trash2} label="Clear All Drawings" danger onClick={onClearAll} />
    </div>
  );
}

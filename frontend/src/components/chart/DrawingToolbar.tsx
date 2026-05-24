import { MousePointer2, TrendingUp, Minus, Square, GitBranch, Type, Eraser } from "lucide-react";
import { cn } from "@/lib/utils";
import type { DrawingTool } from "@/types/chart";

const TOOLS: { tool: DrawingTool; Icon: React.ElementType; label: string; functional: boolean }[] = [
  { tool: "cursor", Icon: MousePointer2, label: "Cursor", functional: true },
  { tool: "hline", Icon: Minus, label: "Horizontal Line", functional: true },
  { tool: "trendline", Icon: TrendingUp, label: "Trend Line", functional: true },
  { tool: "rect", Icon: Square, label: "Rectangle", functional: true },
  { tool: "fib", Icon: GitBranch, label: "Fibonacci", functional: true },
  { tool: "text", Icon: Type, label: "Text", functional: true },
];

interface Props {
  activeTool: DrawingTool;
  onChange: (tool: DrawingTool) => void;
  onClearAll: () => void;
}

export default function DrawingToolbar({ activeTool, onChange, onClearAll }: Props) {
  return (
    <div className="w-10 flex flex-col items-center pt-2 gap-0.5 border-r border-[#1f1f1f] bg-[#0a0a0a] shrink-0">
      {TOOLS.map(({ tool, Icon, label, functional }) => (
        <button
          key={tool}
          title={label + (!functional ? " (coming soon)" : "")}
          onClick={() => functional && onChange(tool)}
          className={cn(
            "w-8 h-8 flex items-center justify-center rounded transition-colors",
            activeTool === tool
              ? "bg-white/10 text-white"
              : functional
                ? "text-[#555] hover:text-[#d4d4d4] hover:bg-white/5"
                : "text-[#2a2a2a] cursor-not-allowed"
          )}
        >
          <Icon size={16} />
        </button>
      ))}

      <div className="w-6 border-t border-[#1f1f1f] my-1" />

      <button
        title="Clear all drawings"
        onClick={onClearAll}
        className="w-8 h-8 flex items-center justify-center rounded text-[#555] hover:text-[#ef5350] hover:bg-white/5 transition-colors"
      >
        <Eraser size={16} />
      </button>
    </div>
  );
}

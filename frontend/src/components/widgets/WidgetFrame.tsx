import React from "react";
import { GripVertical, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface WidgetFrameProps {
  title: string;
  instanceId: string;
  editMode: boolean;
  onRemove: () => void;
  children: React.ReactNode;
  className?: string;
  noPadding?: boolean;
}

export default function WidgetFrame({
  title,
  instanceId: _instanceId,
  editMode,
  onRemove,
  children,
  className,
  noPadding,
}: WidgetFrameProps) {
  return (
    <div
      className={cn(
        "flex flex-col h-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden transition-colors",
        editMode && "border-[var(--border-emphasis)] ring-1 ring-[var(--border-emphasis)]/30",
        className
      )}
    >
      {/* Drag handle header — only visible in edit mode */}
      {editMode && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-[var(--bg-elevated-2)] border-b border-[var(--border-subtle)] shrink-0">
          <div className="widget-drag-handle flex items-center gap-1.5 cursor-grab active:cursor-grabbing text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors">
            <GripVertical size={13} />
            <span className="text-[10px] font-semibold uppercase tracking-wider">{title}</span>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); onRemove(); }}
            className="text-[var(--text-tertiary)] hover:text-[var(--accent-negative)] transition-colors p-0.5 rounded cursor-pointer"
          >
            <X size={13} />
          </button>
        </div>
      )}

      {/* Widget content */}
      <div className={cn("flex-1 min-h-0 overflow-auto", !noPadding && "p-4")}>
        {children}
      </div>
    </div>
  );
}

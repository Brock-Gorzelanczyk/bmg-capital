import { useState } from "react";
import { X, Lock, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { WIDGET_REGISTRY, WIDGET_CATEGORIES, CATEGORY_COLORS, type WidgetCategory } from "@/lib/widgetRegistry";
import { useTierStore } from "@/store/tierStore";

interface Props {
  workspaceId: string;
  existingWidgetIds: string[];
  onAdd: (widgetId: string) => void;
  onClose: () => void;
}

export default function WidgetLibraryModal({ workspaceId: _workspaceId, existingWidgetIds, onAdd, onClose }: Props) {
  const [category, setCategory] = useState<WidgetCategory | "All">("All");
  const tier = useTierStore((s) => s.tier);

  const widgets = Object.values(WIDGET_REGISTRY).filter((w) => {
    if (category !== "All" && w.category !== category) return false;
    return true;
  });

  const canUse = (widgetId: string) => {
    const w = WIDGET_REGISTRY[widgetId];
    if (!w) return false;
    if (w.tierRequired === "free") return true;
    if (w.tierRequired === "plus") return tier === "plus" || tier === "premium";
    if (w.tierRequired === "premium") return tier === "premium";
    return false;
  };

  const alreadyAdded = (widgetId: string) => existingWidgetIds.includes(widgetId);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-2xl w-full max-w-2xl max-h-[80vh] flex flex-col shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-subtle)] shrink-0">
          <div>
            <h2 className="text-base font-semibold text-[var(--text-primary)]">Widget Library</h2>
            <p className="text-xs text-[var(--text-tertiary)] mt-0.5">{Object.keys(WIDGET_REGISTRY).length} widgets available</p>
          </div>
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors p-1 rounded cursor-pointer"><X size={18} /></button>
        </div>

        {/* Category filter */}
        <div className="flex gap-1.5 px-5 py-3 border-b border-[var(--border-subtle)] shrink-0 overflow-x-auto">
          {(["All", ...WIDGET_CATEGORIES] as (WidgetCategory | "All")[]).map((cat) => (
            <button
              key={cat}
              onClick={() => setCategory(cat)}
              className={cn(
                "px-3 py-1 rounded-full text-xs font-semibold whitespace-nowrap transition-all cursor-pointer",
                category === cat
                  ? "bg-[var(--accent-positive)] text-[#0a0a0a]"
                  : "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              )}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Widget grid */}
        <div className="flex-1 overflow-y-auto p-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {widgets.map((w) => {
              const usable = canUse(w.id);
              const added = alreadyAdded(w.id);
              const Icon = w.icon;
              const catColor = CATEGORY_COLORS[w.category];
              return (
                <button
                  key={w.id}
                  onClick={() => { if (usable && !w.comingSoon && !added) { onAdd(w.id); } }}
                  disabled={!usable || w.comingSoon || added}
                  className={cn(
                    "relative flex items-start gap-3 p-4 rounded-xl border text-left transition-all cursor-pointer group",
                    added
                      ? "bg-[var(--accent-positive)]/5 border-[var(--accent-positive)]/30"
                      : usable && !w.comingSoon
                      ? "bg-[var(--bg-elevated)] border-[var(--border-subtle)] hover:border-[var(--border-emphasis)] hover:bg-[var(--bg-elevated-2)]"
                      : "bg-[var(--bg-elevated)]/50 border-[var(--border-subtle)] opacity-60 cursor-not-allowed"
                  )}
                >
                  <div className={cn("p-2 rounded-lg shrink-0", catColor)}>
                    <Icon size={16} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-sm font-semibold text-[var(--text-primary)]">{w.name}</span>
                      {w.comingSoon && <span className="text-[9px] font-bold uppercase tracking-wider text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)] px-1.5 py-0.5 rounded-full">Soon</span>}
                      {!usable && <span className="text-[9px] font-bold uppercase tracking-wider text-[#F59E0B] bg-[#F59E0B]/10 px-1.5 py-0.5 rounded-full flex items-center gap-0.5"><Lock size={8} /> {w.tierRequired}</span>}
                    </div>
                    <p className="text-xs text-[var(--text-tertiary)] mt-0.5 line-clamp-2">{w.description}</p>
                    <div className={cn("text-[9px] font-semibold px-1.5 py-0.5 rounded-full w-fit mt-1.5", catColor)}>{w.category}</div>
                  </div>
                  {added && <Check size={14} className="text-[var(--accent-positive)] shrink-0 mt-0.5" />}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

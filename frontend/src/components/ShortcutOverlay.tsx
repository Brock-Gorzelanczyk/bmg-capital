import { useEffect } from "react";
import { cn } from "@/lib/utils";

interface ShortcutOverlayProps {
  isOpen: boolean;
  onClose: () => void;
}

interface ShortcutRow {
  key: string;
  description: string;
}

const SHORTCUTS: ShortcutRow[] = [
  { key: "⌘K / Ctrl+K", description: "Open Co-Pilot" },
  { key: "1 – 6", description: "Switch bot (Day / Swing / LT × Stock & Crypto)" },
  { key: "P", description: "Pause current bot" },
  { key: "/", description: "Focus activity search" },
  { key: "Esc", description: "Back to Command Center" },
  { key: "?", description: "Show / hide this overlay" },
];

export default function ShortcutOverlay({ isOpen, onClose }: ShortcutOverlayProps) {
  useEffect(() => {
    if (!isOpen) return;
    function handler(e: KeyboardEvent) {
      if (e.key === "Escape" || e.key === "?") {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative bg-slate-900/95 backdrop-blur border border-slate-700 rounded-2xl p-6 w-full max-w-sm shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-white font-semibold text-base mb-4">Keyboard Shortcuts</h3>
        <div className="space-y-2">
          {SHORTCUTS.map((s) => (
            <div
              key={s.key}
              className="flex items-center justify-between gap-4"
            >
              <kbd
                className={cn(
                  "inline-flex items-center px-2 py-0.5 rounded text-xs font-mono",
                  "bg-slate-800 border border-slate-600 text-teal-400 whitespace-nowrap"
                )}
              >
                {s.key}
              </kbd>
              <span className="text-zinc-400 text-sm text-right">{s.description}</span>
            </div>
          ))}
        </div>
        <p className="text-zinc-600 text-xs mt-4 text-center">Press ? or Esc to close</p>
      </div>
    </div>
  );
}

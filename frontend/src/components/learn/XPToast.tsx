import { useEffect, useState } from "react";
import { Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { BADGE_META } from "@/types/learn";

interface Props {
  xp: number;
  newBadges?: string[];
  onDone?: () => void;
}

export default function XPToast({ xp, newBadges = [], onDone }: Props) {
  const [visible, setVisible] = useState(true);
  const [phase, setPhase] = useState<"in" | "hold" | "out">("in");

  useEffect(() => {
    const t1 = setTimeout(() => setPhase("hold"), 50);
    const t2 = setTimeout(() => setPhase("out"), 2800);
    const t3 = setTimeout(() => {
      setVisible(false);
      onDone?.();
    }, 3300);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
  }, []);

  if (!visible) return null;

  return (
    <div
      className={cn(
        "fixed bottom-20 right-6 z-50 space-y-2 transition-all duration-300",
        phase === "in" && "opacity-0 translate-y-4",
        phase === "hold" && "opacity-100 translate-y-0",
        phase === "out" && "opacity-0 -translate-y-2"
      )}
    >
      <div className="flex items-center gap-2 bg-[#22C55E]/15 border border-emerald-500/30 text-[#22C55E] rounded-xl px-4 py-2.5 shadow-lg backdrop-blur-sm">
        <Zap size={16} className="fill-emerald-400" />
        <span className="font-bold text-sm">+{xp} XP</span>
      </div>
      {newBadges.map((b) => {
        const meta = BADGE_META[b];
        if (!meta) return null;
        return (
          <div
            key={b}
            className="flex items-center gap-2 bg-amber-500/15 border border-amber-500/30 text-amber-400 rounded-xl px-4 py-2.5 shadow-lg backdrop-blur-sm"
          >
            <span className="text-base">{meta.icon}</span>
            <div>
              <p className="text-xs font-bold leading-none">{meta.label}</p>
              <p className="text-[10px] text-amber-500/70 leading-none mt-0.5">{meta.description}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

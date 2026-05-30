import { cn } from "@/lib/utils";

export type ReadingLevel = "pro" | "investor" | "beginner" | "eli5";

const LEVELS: { id: ReadingLevel; label: string; desc: string }[] = [
  { id: "pro",       label: "Pro",      desc: "Full technical detail" },
  { id: "investor",  label: "Investor", desc: "Key insights" },
  { id: "beginner",  label: "Beginner", desc: "Plain language" },
  { id: "eli5",      label: "ELI5",     desc: "Simple terms" },
];

interface Props {
  level: ReadingLevel;
  onChange: (level: ReadingLevel) => void;
  className?: string;
}

export default function ReadingLevelSlider({ level, onChange, className }: Props) {
  return (
    <div className={cn("flex items-center gap-1", className)}>
      <span className="text-[10px] text-[var(--text-tertiary)] mr-1 shrink-0">Reading level:</span>
      {LEVELS.map((l) => (
        <button
          key={l.id}
          onClick={() => onChange(l.id)}
          title={l.desc}
          className={cn(
            "px-2 py-0.5 rounded text-[10px] font-medium transition-all border",
            level === l.id
              ? "bg-[var(--accent-positive)]/15 text-[var(--accent-positive)] border-[var(--accent-positive)]/30"
              : "bg-transparent text-[var(--text-tertiary)] border-transparent hover:text-[var(--text-secondary)] hover:border-[var(--border-subtle)]"
          )}
        >
          {l.label}
        </button>
      ))}
    </div>
  );
}

import { useState } from "react";
import { CheckCircle2, XCircle, ChevronRight } from "lucide-react";
import type { QuizQuestion } from "@/types/learn";
import { shuffleQuizQuestion } from "@/types/learn";
import { cn } from "@/lib/utils";

interface Props {
  questions: QuizQuestion[];
  lessonId: string;
  onComplete: (score: number) => void;
}

export default function QuizBlock({ questions, lessonId, onComplete }: Props) {
  // Deterministic shuffle seeded by lessonId hash
  const seed = lessonId.split("").reduce((acc, c) => acc + c.charCodeAt(0), 0);
  const shuffled = questions.map((q, i) => shuffleQuizQuestion(q, seed + i));

  const [idx, setIdx] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [correct, setCorrect] = useState(0);
  const [done, setDone] = useState(false);

  const q = shuffled[idx];

  const handleSelect = (optIdx: number) => {
    if (revealed) return;
    setSelected(optIdx);
    setRevealed(true);
    if (optIdx === q.answer) setCorrect((c) => c + 1);
  };

  const handleNext = () => {
    if (idx + 1 >= shuffled.length) {
      setDone(true);
      onComplete(correct / shuffled.length);
    } else {
      setIdx((i) => i + 1);
      setSelected(null);
      setRevealed(false);
    }
  };

  if (done) {
    const pct = Math.round((correct / shuffled.length) * 100);
    return (
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-xl p-6 text-center space-y-3">
        <div className={cn("text-4xl font-black", pct === 100 ? "text-[var(--accent-positive)]" : pct >= 67 ? "text-amber-400" : "text-[var(--accent-negative)]")}>
          {pct}%
        </div>
        <p className="text-[var(--text-secondary)] text-sm">
          {correct} / {shuffled.length} correct
        </p>
        <p className="text-[var(--text-tertiary)] text-xs">
          {pct === 100 ? "Perfect! 💯" : pct >= 67 ? "Well done — review any you missed above." : "Quiz saved. Review the lesson and try again to improve your score."}
        </p>
      </div>
    );
  }

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">
          Question {idx + 1} of {shuffled.length}
        </span>
        <div className="flex gap-1">
          {shuffled.map((_, i) => (
            <div
              key={i}
              className={cn(
                "w-1.5 h-1.5 rounded-full",
                i < idx ? "bg-[#22C55E]" : i === idx ? "bg-white" : "bg-[var(--bg-elevated-2)]"
              )}
            />
          ))}
        </div>
      </div>

      <p className="text-[var(--text-primary)] font-medium leading-snug">{q.question}</p>

      <div className="space-y-2">
        {q.options.map((opt, i) => {
          const isSelected = selected === i;
          const isCorrect = i === q.answer;
          let variant = "border-[var(--border-emphasis)] text-[var(--text-secondary)] hover:border-[var(--border-emphasis)] hover:text-[var(--text-primary)]";
          if (revealed && isCorrect) variant = "border-emerald-500 bg-[var(--accent-positive-bg)] text-emerald-300";
          else if (revealed && isSelected && !isCorrect) variant = "border-red-500 bg-[var(--accent-negative-bg)] text-red-300";

          return (
            <button
              key={i}
              onClick={() => handleSelect(i)}
              disabled={revealed}
              className={cn(
                "w-full text-left px-4 py-3 rounded-lg border text-sm transition-colors flex items-center justify-between gap-3",
                variant,
                !revealed && "cursor-pointer"
              )}
            >
              <span>{opt}</span>
              {revealed && isCorrect && <CheckCircle2 size={16} className="text-[var(--accent-positive)] shrink-0" />}
              {revealed && isSelected && !isCorrect && <XCircle size={16} className="text-[var(--accent-negative)] shrink-0" />}
            </button>
          );
        })}
      </div>

      {revealed && (
        <div className="space-y-3">
          {q.explanation && (
            <p className="text-[var(--text-tertiary)] text-xs leading-relaxed border-l-2 border-[var(--border-emphasis)] pl-3">
              {q.explanation}
            </p>
          )}
          <button
            onClick={handleNext}
            className="flex items-center gap-1.5 text-sm font-semibold text-[var(--text-primary)] hover:text-[var(--accent-positive)] transition-colors"
          >
            {idx + 1 >= shuffled.length ? "See results" : "Next question"}
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

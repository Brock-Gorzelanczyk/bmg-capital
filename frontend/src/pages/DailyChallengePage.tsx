import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Calendar, CheckCircle, XCircle, Copy, Check } from "lucide-react";
import {
  getTodayChallenge,
  submitChallengeAttempt,
  getStreak,
  logActivity,
} from "@/api/engagement";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/utils";

// ── Type label map ────────────────────────────────────────────────────────────

const CHALLENGE_TYPE_LABELS: Record<string, string> = {
  chart_pattern:   "Chart Pattern",
  predict_close:   "Predict the Close",
  earnings_beat:   "Earnings Beat",
  "10k_translation": "10-K Translation",
  strategy_fit:    "Strategy Fit",
  risk_check:      "Risk Check",
  greek_check:     "Greek Check",
};

const DIFFICULTY_DOT: Record<string, string> = {
  beginner:     "bg-[#22C55E]",
  intermediate: "bg-[#F59E0B]",
  advanced:     "bg-[#EF4444]",
};

const DIFFICULTY_LABEL: Record<string, string> = {
  beginner:     "Beginner",
  intermediate: "Intermediate",
  advanced:     "Advanced",
};

// ── Floating XP animation ─────────────────────────────────────────────────────

function XpFloat({ xp, show }: { xp: number; show: boolean }) {
  return (
    <span
      className={cn(
        "absolute top-0 right-0 font-mono font-bold text-sm text-[#22C55E] pointer-events-none select-none transition-all duration-700",
        show ? "opacity-100 -translate-y-6" : "opacity-0 translate-y-0"
      )}
    >
      +{xp} XP
    </span>
  );
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

function ChallengeSkeleton() {
  return (
    <div className="space-y-4 p-4">
      <Skeleton height={24} className="w-48" />
      <Skeleton height={18} className="w-32" />
      <div className="mt-6 space-y-2">
        <Skeleton height={20} />
        <Skeleton height={20} className="w-5/6" />
      </div>
      <div className="mt-6 space-y-3">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} height={48} />
        ))}
      </div>
      <Skeleton height={44} className="mt-4" />
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type Phase = "loading" | "idle" | "selected" | "submitted" | "already_answered";

export default function DailyChallengePage() {
  const qc = useQueryClient();

  const { data: challenge, isLoading } = useQuery({
    queryKey: ["engagement-challenge-today"],
    queryFn: getTodayChallenge,
    staleTime: 60_000,
  });

  const { data: streakData } = useQuery({
    queryKey: ["engagement-streak"],
    queryFn: getStreak,
    staleTime: 60_000,
  });

  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [result, setResult] = useState<{
    correct: boolean;
    explanation: string;
    xp_earned: number;
    new_streak: number;
    share_emoji: string;
    correct_idx: number;
    chosen_idx: number;
  } | null>(null);
  const [showXp, setShowXp] = useState(false);
  const [copied, setCopied] = useState(false);

  // Sync phase from loaded challenge
  useEffect(() => {
    if (isLoading) {
      setPhase("loading");
      return;
    }
    if (!challenge) return;
    if (challenge.already_answered && challenge.result) {
      setPhase("already_answered");
      setSelectedIdx(challenge.result.choice_idx);
      setResult({
        correct: challenge.result.correct,
        explanation: challenge.result.explanation,
        xp_earned: 0,
        new_streak: streakData?.current_streak ?? 0,
        share_emoji: challenge.result.share_emoji,
        correct_idx: challenge.result.correct ? challenge.result.choice_idx : -1,
        chosen_idx: challenge.result.choice_idx,
      });
    } else {
      setPhase("idle");
    }
  }, [isLoading, challenge]);

  const submitMutation = useMutation({
    mutationFn: ({ challenge_id, choice_idx }: { challenge_id: number; choice_idx: number }) =>
      submitChallengeAttempt(challenge_id, choice_idx),
    onSuccess: (data) => {
      // figure out correct index: if correct, selected is correct; otherwise need server to tell us
      // The API returns correct boolean; we'll highlight selected as wrong and won't know correct from API
      // We'll do best-effort: if correct, selected_idx is correct_idx
      const chosen = selectedIdx ?? 0;
      setResult({
        correct: data.correct,
        explanation: data.explanation,
        xp_earned: data.xp_earned,
        new_streak: data.new_streak,
        share_emoji: data.share_emoji,
        correct_idx: data.correct ? chosen : -1,
        chosen_idx: chosen,
      });
      setPhase("submitted");
      if (data.correct) {
        setShowXp(true);
        setTimeout(() => setShowXp(false), 1200);
      }
      // Invalidate challenge so badge dot updates
      qc.invalidateQueries({ queryKey: ["engagement-challenge-today"] });
      // Log activity
      logActivity("challenge").catch(() => {});
    },
  });

  const handleSubmit = () => {
    if (selectedIdx === null || !challenge) return;
    setPhase("submitted"); // optimistic — will be overwritten by mutation
    submitMutation.mutate({ challenge_id: challenge.challenge_id, choice_idx: selectedIdx });
  };

  const handleSelect = (idx: number) => {
    if (phase === "submitted" || phase === "already_answered") return;
    setSelectedIdx(idx);
    setPhase("selected");
  };

  const buildShareText = () => {
    if (!challenge || !result) return "";
    const typeLabel = CHALLENGE_TYPE_LABELS[challenge.challenge_type] ?? challenge.challenge_type;
    return [
      "BMG Capital Daily Challenge",
      result.share_emoji,
      `${typeLabel} · ${DIFFICULTY_LABEL[challenge.difficulty] ?? challenge.difficulty}`,
      "bmgcapital.com/challenge",
    ].join("\n");
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(buildShareText()).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  // ── Render ──────────────────────────────────────────────────────────────────

  if (phase === "loading") {
    return (
      <div className="max-w-xl mx-auto">
        <ChallengeSkeleton />
      </div>
    );
  }

  if (!challenge) {
    return (
      <div className="max-w-xl mx-auto flex flex-col items-center justify-center gap-3 py-24 text-[var(--text-tertiary)]">
        <Calendar size={32} />
        <p className="text-sm">No challenge today — check back tomorrow.</p>
      </div>
    );
  }

  const isAnswered = phase === "submitted" || phase === "already_answered";
  const typeLabel = CHALLENGE_TYPE_LABELS[challenge.challenge_type] ?? challenge.challenge_type;
  const streak = streakData?.current_streak ?? 0;
  const freezes = streakData?.freezes_remaining ?? 0;

  const getChoiceClass = (idx: number) => {
    if (!isAnswered) {
      if (selectedIdx === idx) {
        return "bg-blue-500/10 border-blue-500 text-[var(--text-primary)]";
      }
      return "bg-[var(--bg-elevated-2)] border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[var(--border-subtle)] hover:bg-[var(--bg-elevated-2)]";
    }
    // Answered states
    if (!result) return "bg-[var(--bg-elevated-2)] border-[var(--border-subtle)] text-[var(--text-secondary)]";

    // Show correct answer in green if we know it
    if (result.correct && result.chosen_idx === idx) {
      return "bg-green-500/10 border-green-500 text-[var(--text-primary)]";
    }
    // Wrong choice by user
    if (!result.correct && result.chosen_idx === idx) {
      return "bg-red-500/10 border-red-500 text-[var(--text-primary)]";
    }
    // Known correct answer (when result.correct_idx >= 0 and != chosen)
    if (result.correct_idx >= 0 && result.correct_idx === idx && !result.correct) {
      return "bg-green-500/10 border-green-500 text-[var(--text-primary)]";
    }
    return "bg-[var(--bg-elevated-2)] border-[var(--border-subtle)] text-[var(--text-secondary)] opacity-50";
  };

  return (
    <div className="max-w-xl mx-auto space-y-4 pb-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg">🧠</span>
          <h1 className="text-base font-semibold text-[var(--text-primary)]">Daily Challenge</h1>
        </div>
        <div className="flex items-center gap-2">
          {streak > 0 && (
            <span className="text-sm font-mono font-semibold text-[var(--text-primary)]">
              🔥 {streak}
            </span>
          )}
          {streak > 0 && freezes > 0 && (
            <span className="text-[10px] text-[var(--text-tertiary)]">
              ❄️ {freezes} left
            </span>
          )}
        </div>
      </div>

      {/* Type + difficulty badge row */}
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-[var(--text-secondary)] bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] px-2 py-0.5 rounded-full">
          {typeLabel}
        </span>
        <span className="text-xs text-[var(--text-tertiary)]">·</span>
        <span className="text-xs text-[var(--text-tertiary)]">{challenge.category}</span>
        <span className="text-xs text-[var(--text-tertiary)]">·</span>
        <div className="flex items-center gap-1">
          <span className={cn("w-1.5 h-1.5 rounded-full", DIFFICULTY_DOT[challenge.difficulty] ?? "bg-gray-500")} />
          <span className="text-xs text-[var(--text-tertiary)]">
            {DIFFICULTY_LABEL[challenge.difficulty] ?? challenge.difficulty}
          </span>
        </div>
      </div>

      <div className="border-t border-[var(--border-subtle)]" />

      {/* Question card */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
        <p className="text-sm text-[var(--text-primary)] leading-relaxed">
          {challenge.question}
        </p>
      </div>

      {/* Choices */}
      <div className="space-y-2">
        {challenge.options.map((option, idx) => (
          <button
            key={idx}
            onClick={() => handleSelect(idx)}
            disabled={isAnswered}
            className={cn(
              "w-full text-left px-4 py-3 rounded-xl border text-sm transition-all duration-150",
              "flex items-center gap-3",
              getChoiceClass(idx),
              !isAnswered && "cursor-pointer",
              isAnswered && "cursor-default"
            )}
          >
            {/* Radio indicator */}
            <span
              className={cn(
                "w-4 h-4 rounded-full border-2 flex-shrink-0 flex items-center justify-center",
                selectedIdx === idx && !isAnswered
                  ? "border-blue-500 bg-blue-500"
                  : isAnswered && result?.chosen_idx === idx && result.correct
                  ? "border-green-500 bg-green-500"
                  : isAnswered && result?.chosen_idx === idx && !result.correct
                  ? "border-red-500 bg-red-500"
                  : isAnswered && result?.correct_idx === idx && !result.correct
                  ? "border-green-500 bg-green-500"
                  : "border-[var(--border-subtle)]"
              )}
            >
              {selectedIdx === idx && !isAnswered && (
                <span className="w-1.5 h-1.5 rounded-full bg-white" />
              )}
            </span>
            <span className="flex-1">{option}</span>
          </button>
        ))}
      </div>

      {/* Submit button */}
      {!isAnswered && (
        <button
          onClick={handleSubmit}
          disabled={selectedIdx === null || submitMutation.isPending}
          className={cn(
            "w-full py-3 rounded-xl text-sm font-semibold transition-all duration-150",
            selectedIdx !== null && !submitMutation.isPending
              ? "bg-[#3B82F6] text-white hover:bg-blue-600 cursor-pointer"
              : "bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] cursor-not-allowed"
          )}
        >
          {submitMutation.isPending ? "Submitting…" : "Submit Answer"}
        </button>
      )}

      {/* Result panel */}
      {isAnswered && result && (
        <div
          className={cn(
            "relative bg-[var(--bg-elevated)] border rounded-xl p-4 space-y-3 transition-all duration-300",
            result.correct ? "border-green-500/40" : "border-red-500/40"
          )}
        >
          {/* XP Float */}
          {result.xp_earned > 0 && <XpFloat xp={result.xp_earned} show={showXp} />}

          {/* Result header */}
          <div className="flex items-center gap-2">
            {result.correct ? (
              <>
                <CheckCircle size={18} className="text-[#22C55E]" />
                <span className="text-sm font-semibold text-[#22C55E]">
                  Correct!
                  {result.xp_earned > 0 && (
                    <span className="ml-1.5 font-mono">+{result.xp_earned} XP</span>
                  )}
                </span>
              </>
            ) : (
              <>
                <XCircle size={18} className="text-[#EF4444]" />
                <span className="text-sm font-semibold text-[#EF4444]">Not quite</span>
              </>
            )}
          </div>

          {/* Explanation */}
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            {result.explanation}
          </p>

          {/* Share emoji */}
          {result.share_emoji && (
            <div className="font-mono text-lg tracking-widest bg-[var(--bg-elevated-2)] rounded-lg px-4 py-2 text-center">
              {result.share_emoji}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex gap-2 pt-1">
            <button
              onClick={handleCopy}
              className="flex-1 flex items-center justify-center gap-2 py-2 rounded-lg border border-[var(--border-subtle)] text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-subtle)] transition-colors cursor-pointer"
            >
              {copied ? (
                <>
                  <Check size={13} className="text-[#22C55E]" />
                  Copied!
                </>
              ) : (
                <>
                  <Copy size={13} />
                  Share Result
                </>
              )}
            </button>
            <div className="flex-1 flex items-center justify-center gap-2 py-2 rounded-lg border border-[var(--border-subtle)] text-xs text-[var(--text-tertiary)]">
              <Calendar size={13} />
              Tomorrow's preview soon
            </div>
          </div>
        </div>
      )}

      {/* Already answered notice */}
      {phase === "already_answered" && (
        <p className="text-xs text-[var(--text-tertiary)] text-center">
          You already answered today's challenge. Come back tomorrow!
        </p>
      )}
    </div>
  );
}

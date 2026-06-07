import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { GraduationCap, Clock, ChevronRight, ChevronLeft, AlertTriangle, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import client from "@/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Eligibility {
  eligible: boolean;
  reason: string | null;
  attempts_used: number;
  next_attempt_available_at: string | null;
  cooldown_seconds: number;
}

interface AttemptStart {
  attempt_id: number;
  question_count: number;
  time_limit_seconds: number;
  started_at: string;
}

interface Question {
  id: number;
  index: number;
  body: string;
  question_type: string;
  options: string[] | null;
  chart_image_url: string | null;
  already_answered: boolean;
  time_remaining_seconds: number;
  total_questions: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTime(secs: number): string {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return [h, m, s].map((v) => String(v).padStart(2, "0")).join(":");
}

// ── Eligibility / Honor Code Phase ───────────────────────────────────────────

function EligibilityGate({
  eligibility,
  onStart,
}: {
  eligibility: Eligibility;
  onStart: (honorName: string) => void;
}) {
  const [agreed, setAgreed] = useState(false);
  const [honorName, setHonorName] = useState("");

  if (!eligibility.eligible) {
    const nextDate = eligibility.next_attempt_available_at
      ? new Date(eligibility.next_attempt_available_at).toLocaleDateString(undefined, {
          month: "long",
          day: "numeric",
          year: "numeric",
        })
      : null;

    return (
      <div className="max-w-lg mx-auto mt-16 text-center space-y-4">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-amber-500/10 mb-2">
          <AlertTriangle size={28} className="text-amber-400" />
        </div>
        <h1 className="text-xl font-bold text-white">Not Eligible Yet</h1>
        <p className="text-zinc-400 text-sm leading-relaxed">{eligibility.reason}</p>
        {nextDate && (
          <p className="text-zinc-500 text-xs">
            Next attempt available: <span className="text-zinc-300">{nextDate}</span>
          </p>
        )}
        {eligibility.attempts_used > 0 && (
          <p className="text-zinc-500 text-xs">
            Attempts used in last 90 days:{" "}
            <span className="text-zinc-300">
              {eligibility.attempts_used} / 3
            </span>
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto space-y-8">
      {/* Header */}
      <div className="text-center space-y-2">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-lime-500/10 mb-2">
          <GraduationCap size={28} className="text-lime-400" />
        </div>
        <h1 className="text-2xl font-bold text-white">BMG Capital Learning Center Exam</h1>
        <p className="text-zinc-400 text-sm">
          Demonstrate mastery of the IMCP curriculum to earn your certificate.
        </p>
      </div>

      {/* Exam details */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Questions", value: "150" },
          { label: "Time Limit", value: "4 hours" },
          { label: "Passing Score", value: "90%" },
          { label: "Max Attempts", value: "3 per 90 days" },
        ].map(({ label, value }) => (
          <div key={label} className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 text-center">
            <p className="text-xs text-zinc-500 mb-1">{label}</p>
            <p className="text-sm font-semibold text-white">{value}</p>
          </div>
        ))}
      </div>

      {/* Cooldown note */}
      {eligibility.attempts_used > 0 && (
        <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4 text-sm text-amber-300">
          <span className="font-semibold">Note:</span> You have used{" "}
          {eligibility.attempts_used} of 3 attempts in the last 90 days. A 14-day cooldown
          applies between attempts.
        </div>
      )}

      {/* Honor code */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 space-y-5">
        <h2 className="text-sm font-semibold text-white">Honor Code Agreement</h2>
        <ul className="text-xs text-zinc-400 space-y-2 leading-relaxed">
          <li className="flex gap-2">
            <span className="text-lime-400 shrink-0">•</span>
            I will complete this exam without outside assistance, notes, or internet searches.
          </li>
          <li className="flex gap-2">
            <span className="text-lime-400 shrink-0">•</span>
            I understand that switching tabs or windows during the exam may result in disqualification after 3 violations.
          </li>
          <li className="flex gap-2">
            <span className="text-lime-400 shrink-0">•</span>
            I will not share exam questions or answers with others.
          </li>
          <li className="flex gap-2">
            <span className="text-lime-400 shrink-0">•</span>
            I understand a score of 90% or higher is required to pass.
          </li>
        </ul>

        <div>
          <label className="block text-xs text-zinc-400 mb-2">
            Type your full name to confirm
          </label>
          <input
            type="text"
            value={honorName}
            onChange={(e) => setHonorName(e.target.value)}
            placeholder="Your full name"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-lime-500 transition-colors"
          />
        </div>

        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
            className="mt-0.5 accent-lime-400 w-4 h-4 shrink-0"
          />
          <span className="text-xs text-zinc-400 leading-relaxed">
            I agree to the Honor Code and understand the exam rules stated above.
          </span>
        </label>

        <button
          disabled={!agreed || honorName.trim().length < 2}
          onClick={() => onStart(honorName.trim())}
          className={cn(
            "w-full py-3 rounded-xl text-sm font-semibold transition-all",
            agreed && honorName.trim().length >= 2
              ? "bg-lime-500 hover:bg-lime-400 text-black"
              : "bg-zinc-800 text-zinc-500 cursor-not-allowed"
          )}
        >
          Begin Exam
        </button>
      </div>
    </div>
  );
}

// ── Exam UI ───────────────────────────────────────────────────────────────────

function ExamUI({
  attempt,
  onSubmit,
}: {
  attempt: AttemptStart;
  onSubmit: (result: unknown) => void;
}) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [timeRemaining, setTimeRemaining] = useState(attempt.time_limit_seconds);
  const [tabSwitches, setTabSwitches] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const tabSwitchRef = useRef(0);
  const navigate = useNavigate();

  // Fetch current question
  const { data: question, isLoading: qLoading } = useQuery<Question>({
    queryKey: ["exam-question", attempt.attempt_id, currentIndex],
    queryFn: async () => {
      const res = await client.get(
        `/api/exams/${attempt.attempt_id}/question/${currentIndex}`
      );
      return res.data;
    },
    staleTime: Infinity,
  });

  // Answer mutation
  const answerMutation = useMutation({
    mutationFn: async ({
      questionId,
      questionIndex,
      userAnswer,
    }: {
      questionId: number;
      questionIndex: number;
      userAnswer: string;
    }) => {
      const res = await client.post(`/api/exams/${attempt.attempt_id}/answer`, {
        question_id: questionId,
        question_index: questionIndex,
        user_answer: userAnswer,
      });
      return res.data;
    },
    onSuccess: (data) => {
      if (data.time_remaining_seconds !== undefined) {
        setTimeRemaining(data.time_remaining_seconds);
      }
    },
  });

  // Heartbeat mutation
  const heartbeatMutation = useMutation({
    mutationFn: async (tabSwitchCount: number) => {
      const res = await client.post(`/api/exams/${attempt.attempt_id}/heartbeat`, {
        tab_switches: tabSwitchCount,
      });
      return res.data;
    },
    onSuccess: (data) => {
      if (data.status === "disqualified") {
        toast.error("Exam disqualified due to excessive tab switching.");
        navigate("/learn/exam/result", {
          state: {
            passed: false,
            score_pct: 0,
            questions_correct: 0,
            questions_total: attempt.question_count,
            breakdown_by_module: [],
            certificate_id: null,
            failed_questions: [],
            disqualified: true,
          },
        });
        return;
      }
      if (data.status === "submitted") {
        onSubmit(data);
        return;
      }
      if (data.time_remaining_seconds !== undefined) {
        setTimeRemaining(data.time_remaining_seconds);
      }
      if (data.warning) {
        toast.warning(data.warning);
      }
    },
  });

  // Submit mutation
  const submitMutation = useMutation({
    mutationFn: async () => {
      const res = await client.post(`/api/exams/${attempt.attempt_id}/submit`);
      return res.data;
    },
    onSuccess: (data) => {
      onSubmit(data);
    },
    onError: () => {
      toast.error("Failed to submit exam. Please try again.");
      setSubmitting(false);
    },
  });

  // Countdown timer
  useEffect(() => {
    const interval = setInterval(() => {
      setTimeRemaining((t) => {
        if (t <= 1) {
          clearInterval(interval);
          return 0;
        }
        return t - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Heartbeat every 30 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      heartbeatMutation.mutate(tabSwitchRef.current);
    }, 30_000);
    return () => clearInterval(interval);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Anti-cheat: tab visibility
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        tabSwitchRef.current += 1;
        setTabSwitches(tabSwitchRef.current);
        heartbeatMutation.mutate(tabSwitchRef.current);
        toast.warning(
          `Tab switch detected (${tabSwitchRef.current}/3). ${
            tabSwitchRef.current >= 2
              ? "Next switch will disqualify your exam!"
              : "Do not leave the exam tab."
          }`
        );
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleAnswer = useCallback(
    (questionId: number, answer: string) => {
      if (answers[currentIndex] !== undefined) return; // already answered
      setAnswers((prev) => ({ ...prev, [currentIndex]: answer }));
      answerMutation.mutate({
        questionId,
        questionIndex: currentIndex,
        userAnswer: answer,
      });
    },
    [answers, currentIndex, answerMutation]
  );

  const answeredCount = Object.keys(answers).length;
  const allAnswered = answeredCount === attempt.question_count;
  const timerColor =
    timeRemaining < 300 ? "text-red-400" : timeRemaining < 900 ? "text-amber-400" : "text-lime-400";

  const handleSubmit = () => {
    if (!submitting) {
      setSubmitting(true);
      submitMutation.mutate();
    }
  };

  return (
    <div className="min-h-screen bg-zinc-950 flex flex-col">
      {/* Top bar */}
      <div className="sticky top-0 z-10 bg-zinc-900 border-b border-zinc-800 px-4 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <GraduationCap size={18} className="text-lime-400 shrink-0" />
          <span className="text-sm font-medium text-white hidden sm:block">
            BMG Learning Center Exam
          </span>
          <span className="text-xs text-zinc-400">
            Q {currentIndex + 1} / {attempt.question_count}
          </span>
        </div>

        <div className={cn("flex items-center gap-1.5 font-mono font-bold text-sm", timerColor)}>
          <Clock size={14} />
          {formatTime(timeRemaining)}
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs text-zinc-400">
            {answeredCount} / {attempt.question_count} answered
          </span>
          {tabSwitches > 0 && (
            <span className="text-xs text-amber-400 flex items-center gap-1">
              <AlertTriangle size={12} />
              {tabSwitches}/3
            </span>
          )}
          <button
            onClick={handleSubmit}
            disabled={submitting || submitMutation.isPending}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-semibold transition-all",
              allAnswered
                ? "bg-lime-500 hover:bg-lime-400 text-black"
                : "bg-zinc-700 hover:bg-zinc-600 text-white"
            )}
          >
            {submitting || submitMutation.isPending ? "Submitting…" : "Submit Exam"}
          </button>
        </div>
      </div>

      {/* Question area */}
      <div className="flex-1 max-w-3xl mx-auto w-full px-4 py-8">
        {qLoading ? (
          <div className="space-y-4">
            <div className="h-6 bg-zinc-800 rounded animate-pulse w-3/4" />
            <div className="h-4 bg-zinc-800 rounded animate-pulse w-full" />
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-12 bg-zinc-900 border border-zinc-800 rounded-xl animate-pulse" />
            ))}
          </div>
        ) : question ? (
          <div className="space-y-6">
            {/* Question number + body */}
            <div>
              <p className="text-xs text-zinc-500 mb-3">Question {currentIndex + 1}</p>
              <p className="text-base text-white leading-relaxed font-medium">{question.body}</p>
            </div>

            {/* Already answered notice */}
            {answers[currentIndex] !== undefined && (
              <div className="flex items-center gap-2 text-xs text-lime-400">
                <CheckCircle2 size={14} />
                Answer recorded — you cannot change it.
              </div>
            )}

            {/* Options */}
            {question.question_type === "mc" && question.options && (
              <div className="space-y-2">
                {question.options.map((opt, i) => {
                  const isSelected = answers[currentIndex] === String(i);
                  const isDisabled = answers[currentIndex] !== undefined;
                  return (
                    <button
                      key={i}
                      disabled={isDisabled}
                      onClick={() => handleAnswer(question.id, String(i))}
                      className={cn(
                        "w-full text-left px-4 py-3.5 rounded-xl border text-sm transition-all",
                        isSelected
                          ? "border-lime-500 bg-lime-500/10 text-lime-300"
                          : isDisabled
                          ? "border-zinc-800 bg-zinc-900 text-zinc-500 cursor-not-allowed"
                          : "border-zinc-800 bg-zinc-900 text-zinc-200 hover:border-zinc-600 hover:bg-zinc-800 cursor-pointer"
                      )}
                    >
                      <span className="font-semibold mr-2 text-zinc-500">
                        {String.fromCharCode(65 + i)}.
                      </span>
                      {opt}
                    </button>
                  );
                })}
              </div>
            )}

            {/* True / False */}
            {question.question_type === "tf" && (
              <div className="flex gap-3">
                {["true", "false"].map((val) => {
                  const isSelected = answers[currentIndex] === val;
                  const isDisabled = answers[currentIndex] !== undefined;
                  return (
                    <button
                      key={val}
                      disabled={isDisabled}
                      onClick={() => handleAnswer(question.id, val)}
                      className={cn(
                        "flex-1 py-3.5 rounded-xl border text-sm font-semibold transition-all capitalize",
                        isSelected
                          ? "border-lime-500 bg-lime-500/10 text-lime-300"
                          : isDisabled
                          ? "border-zinc-800 bg-zinc-900 text-zinc-500 cursor-not-allowed"
                          : "border-zinc-800 bg-zinc-900 text-zinc-200 hover:border-zinc-600 hover:bg-zinc-800 cursor-pointer"
                      )}
                    >
                      {val}
                    </button>
                  );
                })}
              </div>
            )}

            {/* Short answer */}
            {question.question_type === "sa" && (
              <div>
                {answers[currentIndex] !== undefined ? (
                  <div className="bg-zinc-900 border border-lime-500/30 rounded-xl px-4 py-3 text-sm text-lime-300">
                    {answers[currentIndex]}
                  </div>
                ) : (
                  <SAInput
                    onSubmit={(val) => handleAnswer(question.id, val)}
                  />
                )}
              </div>
            )}
          </div>
        ) : null}
      </div>

      {/* Navigation */}
      <div className="sticky bottom-0 bg-zinc-900 border-t border-zinc-800 px-4 py-3 flex items-center justify-between gap-4">
        <button
          disabled={currentIndex === 0}
          onClick={() => setCurrentIndex((i) => Math.max(0, i - 1))}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium text-zinc-300 hover:text-white hover:bg-zinc-800 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
        >
          <ChevronLeft size={15} />
          Previous
        </button>

        {/* Progress dots (mini) */}
        <div className="hidden sm:flex items-center gap-1 overflow-hidden max-w-xs flex-wrap justify-center">
          {Array.from({ length: Math.min(attempt.question_count, 40) }).map((_, i) => (
            <button
              key={i}
              onClick={() => setCurrentIndex(i)}
              className={cn(
                "w-2 h-2 rounded-full transition-all",
                i === currentIndex
                  ? "bg-lime-400 scale-125"
                  : answers[i] !== undefined
                  ? "bg-lime-700"
                  : "bg-zinc-700 hover:bg-zinc-500"
              )}
              title={`Question ${i + 1}`}
            />
          ))}
          {attempt.question_count > 40 && (
            <span className="text-[10px] text-zinc-500">+{attempt.question_count - 40}</span>
          )}
        </div>

        <button
          disabled={currentIndex === attempt.question_count - 1}
          onClick={() => setCurrentIndex((i) => Math.min(attempt.question_count - 1, i + 1))}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium text-zinc-300 hover:text-white hover:bg-zinc-800 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
        >
          Next
          <ChevronRight size={15} />
        </button>
      </div>
    </div>
  );
}

function SAInput({ onSubmit }: { onSubmit: (val: string) => void }) {
  const [val, setVal] = useState("");
  return (
    <div className="flex gap-2">
      <input
        type="text"
        value={val}
        onChange={(e) => setVal(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && val.trim()) onSubmit(val.trim());
        }}
        placeholder="Type your answer…"
        className="flex-1 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-lime-500 transition-colors"
      />
      <button
        disabled={!val.trim()}
        onClick={() => onSubmit(val.trim())}
        className="px-4 py-3 rounded-xl bg-lime-500 hover:bg-lime-400 disabled:bg-zinc-700 disabled:text-zinc-500 text-black text-sm font-semibold transition-all"
      >
        Submit
      </button>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ExamPage() {
  const navigate = useNavigate();
  const [attempt, setAttempt] = useState<AttemptStart | null>(null);

  const { data: eligibility, isLoading } = useQuery<Eligibility>({
    queryKey: ["exam-eligibility"],
    queryFn: async () => {
      const res = await client.get("/api/exams/eligibility?exam_target=learning_center");
      return res.data;
    },
    staleTime: 0,
  });

  const startMutation = useMutation({
    mutationFn: async (params: { honorName: string }) => {
      const res = await client.post("/api/exams/start", {
        exam_target: "learning_center",
        honor_code_accepted: true,
        honor_code_name: params.honorName,
      });
      return res.data as AttemptStart;
    },
    onSuccess: (data) => setAttempt(data),
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? "Failed to start exam.";
      toast.error(msg);
    },
  });

  const handleSubmitResult = (result: unknown) => {
    navigate("/learn/exam/result", { state: result });
  };

  if (isLoading) {
    return (
      <div className="max-w-2xl mx-auto mt-16 space-y-4">
        <div className="h-8 w-64 bg-zinc-800 rounded animate-pulse mx-auto" />
        <div className="h-40 bg-zinc-900 border border-zinc-800 rounded-2xl animate-pulse" />
      </div>
    );
  }

  if (attempt) {
    return <ExamUI attempt={attempt} onSubmit={handleSubmitResult} />;
  }

  return (
    <div className="max-w-2xl mx-auto py-6 px-4">
      {eligibility && (
        <EligibilityGate
          eligibility={eligibility}
          onStart={(honorName) => startMutation.mutate({ honorName })}
        />
      )}
      {startMutation.isPending && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center space-y-3">
            <div className="w-10 h-10 border-2 border-lime-400 border-t-transparent rounded-full animate-spin mx-auto" />
            <p className="text-sm text-zinc-300">Preparing your exam…</p>
          </div>
        </div>
      )}
    </div>
  );
}

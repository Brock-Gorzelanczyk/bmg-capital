import { useState } from "react";
import { cn } from "@/lib/utils";
import client from "@/api/client";

// ── Map quiz answers to API fields ─────────────────────────────────────────────

function mapExperience(val: string): string {
  if (val === "Active trader") return "advanced";
  if (val === "1–3 years") return "intermediate";
  return "beginner";
}
function mapGoal(val: string): string {
  if (val === "Learn the basics") return "learn";
  if (val === "Practice day trading") return "trade";
  return "invest";
}
function mapRisk(val: string): string {
  if (val === "Aggressive") return "aggressive";
  if (val === "Conservative") return "conservative";
  return "moderate";
}
function mapTime(val: string): string {
  if (val === "15+ hours") return "long";
  if (val === "5–15 hours") return "medium";
  return "short";
}

// ── Types ──────────────────────────────────────────────────────────────────

interface QuizAnswers {
  experience: string;
  goal: string;
  risk: string;
  time: string;
  asset: string;
}

interface WelcomeModalProps {
  onClose: () => void;
}

// ── Quiz data ──────────────────────────────────────────────────────────────

const QUESTIONS = [
  {
    id: "experience" as keyof QuizAnswers,
    question: "How would you describe your investing experience?",
    answers: ["New to investing", "Casual investor", "1–3 years", "Active trader"],
  },
  {
    id: "goal" as keyof QuizAnswers,
    question: "What's your primary goal?",
    answers: ["Learn the basics", "Build long-term wealth", "Practice day trading", "Retirement planning"],
  },
  {
    id: "risk" as keyof QuizAnswers,
    question: "What's your risk tolerance?",
    answers: ["Conservative", "Balanced", "Aggressive"],
  },
  {
    id: "time" as keyof QuizAnswers,
    question: "How much time do you spend on investing per week?",
    answers: ["Less than 1 hour", "1–5 hours", "5–15 hours", "15+ hours"],
  },
  {
    id: "asset" as keyof QuizAnswers,
    question: "Which asset class interests you most?",
    answers: ["Stocks", "Crypto", "Options", "All of them"],
  },
] as const;

// ── Bot recommendation logic ───────────────────────────────────────────────

const BOT_LABELS: Record<string, { name: string; description: string }> = {
  stock_swing: {
    name: "Stock Swing Bot",
    description:
      "Captures multi-day price moves in large-cap equities. Holds positions 2–10 days with defined risk levels.",
  },
  crypto_day: {
    name: "Crypto Day Bot",
    description:
      "Trades BTC/ETH intraday using momentum signals. High-frequency entries with tight stop-losses.",
  },
  options_income: {
    name: "Options Income Bot",
    description:
      "Trades quality equities with a dividend + growth focus to generate steady income.",
  },
};

function recommendBot(answers: Partial<QuizAnswers>): string {
  if (answers.asset === "Crypto") return "crypto_day";
  if (answers.asset === "Options") return "options_income";
  return "stock_swing";
}

// ── Progress bar ───────────────────────────────────────────────────────────

function ProgressDots({ total, current }: { total: number; current: number }) {
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          className={cn(
            "h-1.5 rounded-full transition-all duration-300",
            i < current ? "w-5 bg-lime-400" : i === current ? "w-5 bg-lime-400/70" : "w-2 bg-white/15"
          )}
        />
      ))}
    </div>
  );
}

// ── Answer chip ────────────────────────────────────────────────────────────

function AnswerChip({
  label,
  selected,
  onClick,
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "px-4 py-3 rounded-xl text-sm font-medium text-left transition-all duration-150 border",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-lime-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950",
        selected
          ? "bg-lime-400/15 border-lime-400/60 text-lime-300 shadow-[0_0_12px_rgba(74,222,128,0.15)]"
          : "bg-zinc-900 border-white/10 text-zinc-300 hover:bg-zinc-800 hover:border-white/20 hover:text-zinc-100"
      )}
    >
      {label}
    </button>
  );
}

// ── WelcomeModal ───────────────────────────────────────────────────────────

export default function WelcomeModal({ onClose }: WelcomeModalProps) {
  // "welcome" | "quiz" | "results"
  const [stage, setStage] = useState<"welcome" | "quiz" | "results">("welcome");
  const [step, setStep] = useState(0); // 0-indexed quiz step
  const [answers, setAnswers] = useState<Partial<QuizAnswers>>({});

  const currentQuestion = QUESTIONS[step];
  const selectedAnswer = currentQuestion ? answers[currentQuestion.id] : undefined;
  const totalSteps = QUESTIONS.length;
  const botKey = recommendBot(answers);
  const bot = BOT_LABELS[botKey];

  function handleSkip() {
    localStorage.setItem("bmg_onboarded", "true");
    onClose();
  }

  function handleStartQuiz() {
    setStage("quiz");
    setStep(0);
  }

  function handleSelectAnswer(answer: string) {
    setAnswers((prev) => ({ ...prev, [currentQuestion.id]: answer }));
  }

  function handleNext() {
    if (!selectedAnswer) return;
    if (step < totalSteps - 1) {
      setStep((s) => s + 1);
    } else {
      setStage("results");
    }
  }

  function handleBack() {
    if (step === 0) {
      setStage("welcome");
    } else {
      setStep((s) => s - 1);
    }
  }

  async function handleFinish() {
    localStorage.setItem("bmg_onboarded", "true");
    localStorage.setItem("bmg_quiz_answers", JSON.stringify(answers));
    // Save to backend (best-effort — don't block close on failure)
    try {
      await client.post("/api/onboarding/complete", {
        experience:     mapExperience(answers.experience ?? ""),
        goal:           mapGoal(answers.goal ?? ""),
        risk_tolerance: mapRisk(answers.risk ?? ""),
        time_horizon:   mapTime(answers.time ?? ""),
        asset_classes:  answers.asset ? [answers.asset.toLowerCase()] : [],
      });
    } catch {
      // silently ignore — localStorage is the fallback
    }
    onClose();
  }

  return (
    /* Full-screen overlay */
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
      <div
        className={cn(
          "relative w-full max-w-lg bg-zinc-950 border border-white/10 rounded-2xl shadow-2xl overflow-hidden",
          "animate-in fade-in zoom-in-95 duration-200"
        )}
      >
        {/* Top lime accent bar */}
        <div className="h-0.5 w-full bg-gradient-to-r from-lime-500/60 via-lime-400 to-lime-500/60" />

        <div className="p-8">
          {/* ── Welcome stage ── */}
          {stage === "welcome" && (
            <div className="flex flex-col items-center text-center gap-6">
              {/* Logo / brand mark */}
              <div className="flex flex-col items-center gap-2">
                <div
                  className="w-16 h-16 rounded-2xl flex items-center justify-center text-2xl font-bold text-zinc-950"
                  style={{ background: "#4ade80" }}
                >
                  B
                </div>
                <span
                  className="text-xl font-semibold tracking-tight"
                  style={{ color: "#4ade80" }}
                >
                  BMG Capital
                </span>
              </div>

              {/* Headline */}
              <div className="space-y-3">
                <h1 className="text-3xl font-bold text-zinc-50 leading-tight">
                  Welcome to BMG Capital
                </h1>
                <p className="text-zinc-400 text-sm leading-relaxed max-w-sm">
                  Eight AI bots will trade paper money on your behalf. No real money at
                  risk — this is pure simulation.
                </p>
              </div>

              {/* Stat pills */}
              <div className="flex items-center gap-3 flex-wrap justify-center">
                {[
                  { label: "8 AI Bots", sub: "always trading" },
                  { label: "$0 Risk", sub: "paper money only" },
                  { label: "24 / 7", sub: "simulation" },
                ].map(({ label, sub }) => (
                  <div
                    key={label}
                    className="flex flex-col items-center px-4 py-2.5 rounded-xl bg-zinc-900 border border-white/8"
                  >
                    <span className="text-sm font-semibold text-zinc-50">{label}</span>
                    <span className="text-[11px] text-zinc-500">{sub}</span>
                  </div>
                ))}
              </div>

              {/* CTAs */}
              <div className="flex flex-col gap-3 w-full pt-2">
                <button
                  type="button"
                  onClick={handleStartQuiz}
                  className="w-full h-11 rounded-xl font-semibold text-zinc-950 text-sm transition-all duration-150 hover:brightness-110 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-lime-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950"
                  style={{ background: "#4ade80" }}
                >
                  Take the 60-second tour
                </button>
                <button
                  type="button"
                  onClick={handleSkip}
                  className="w-full h-11 rounded-xl font-medium text-zinc-400 text-sm border border-white/10 bg-zinc-900 hover:bg-zinc-800 hover:text-zinc-200 transition-all duration-150 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-lime-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950"
                >
                  Skip to app
                </button>
              </div>
            </div>
          )}

          {/* ── Quiz stage ── */}
          {stage === "quiz" && (
            <div className="flex flex-col gap-6">
              {/* Header row */}
              <div className="flex items-center justify-between">
                <button
                  type="button"
                  onClick={handleBack}
                  className="text-zinc-500 hover:text-zinc-300 transition-colors text-sm font-medium focus-visible:outline-none"
                >
                  ← Back
                </button>
                <ProgressDots total={totalSteps} current={step} />
                <span className="text-xs text-zinc-500 tabular-nums">
                  {step + 1} / {totalSteps}
                </span>
              </div>

              {/* Question */}
              <div className="space-y-1">
                <p className="text-[11px] uppercase tracking-widest text-lime-500/80 font-semibold">
                  Question {step + 1}
                </p>
                <h2 className="text-xl font-bold text-zinc-50 leading-snug">
                  {currentQuestion.question}
                </h2>
              </div>

              {/* Answer chips */}
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                {currentQuestion.answers.map((answer) => (
                  <AnswerChip
                    key={answer}
                    label={answer}
                    selected={selectedAnswer === answer}
                    onClick={() => handleSelectAnswer(answer)}
                  />
                ))}
              </div>

              {/* Next button */}
              <button
                type="button"
                onClick={handleNext}
                disabled={!selectedAnswer}
                className={cn(
                  "w-full h-11 rounded-xl font-semibold text-sm transition-all duration-150 active:scale-[0.97]",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-lime-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950",
                  selectedAnswer
                    ? "text-zinc-950 hover:brightness-110"
                    : "opacity-40 cursor-not-allowed bg-zinc-800 text-zinc-500"
                )}
                style={selectedAnswer ? { background: "#4ade80" } : undefined}
              >
                {step < totalSteps - 1 ? "Next →" : "See my results →"}
              </button>
            </div>
          )}

          {/* ── Results stage ── */}
          {stage === "results" && (
            <div className="flex flex-col items-center text-center gap-6">
              {/* Trophy icon */}
              <div
                className="w-14 h-14 rounded-2xl flex items-center justify-center text-2xl"
                style={{ background: "rgba(74,222,128,0.15)", color: "#4ade80" }}
              >
                ✦
              </div>

              <div className="space-y-2">
                <p className="text-[11px] uppercase tracking-widest text-lime-500/80 font-semibold">
                  Your recommendation
                </p>
                <h2 className="text-2xl font-bold text-zinc-50">
                  Based on your answers, we recommend starting with:
                </h2>
              </div>

              {/* Bot card */}
              <div className="w-full rounded-xl border border-lime-400/25 bg-lime-400/5 p-5 text-left space-y-2">
                <div className="flex items-center gap-2">
                  <span
                    className="w-2 h-2 rounded-full animate-pulse"
                    style={{ background: "#4ade80" }}
                  />
                  <span className="text-lg font-bold text-lime-300">{bot.name}</span>
                </div>
                <p className="text-sm text-zinc-400 leading-relaxed">{bot.description}</p>
              </div>

              {/* Summary of answers */}
              <div className="w-full rounded-xl border border-white/8 bg-zinc-900 p-4">
                <p className="text-xs text-zinc-500 mb-3 font-medium uppercase tracking-wider">
                  Your profile
                </p>
                <div className="grid grid-cols-2 gap-y-2 gap-x-4 text-left text-xs">
                  {QUESTIONS.map((q) => (
                    <div key={q.id} className="flex flex-col gap-0.5">
                      <span className="text-zinc-600 leading-tight truncate">{q.question.split("?")[0]}?</span>
                      <span className="text-zinc-300 font-medium">{answers[q.id] ?? "—"}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* CTA */}
              <button
                type="button"
                onClick={handleFinish}
                className="w-full h-11 rounded-xl font-semibold text-zinc-950 text-sm transition-all duration-150 hover:brightness-110 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-lime-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950"
                style={{ background: "#4ade80" }}
              >
                Let's go →
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

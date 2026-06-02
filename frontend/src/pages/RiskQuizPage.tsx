import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { ArrowLeft, ChevronRight, Loader2 } from "lucide-react";
import { submitQuiz } from "@/api/robo";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Answers {
  time_horizon?: string;
  goal_type?: string;
  income_bracket?: string;
  savings_rate?: number;
  loss_tolerance?: string;
  experience?: string;
  has_emergency_fund?: boolean;
}

// ── Step helpers ──────────────────────────────────────────────────────────────

function StepHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xl font-bold text-[var(--text-primary)] text-center mb-6">{children}</h2>
  );
}

function PillButton({
  selected,
  onClick,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-4 py-3 rounded-xl border text-sm font-medium transition-all",
        selected
          ? "bg-blue-600 border-blue-500 text-white shadow-lg shadow-blue-500/20"
          : "bg-[var(--bg-elevated)] border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-blue-500/50 hover:text-[var(--text-primary)]"
      )}
    >
      {children}
    </button>
  );
}

function IconCard({
  selected,
  onClick,
  icon,
  label,
}: {
  selected: boolean;
  onClick: () => void;
  icon: string;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex flex-col items-center gap-2 py-4 px-3 rounded-xl border text-sm font-medium transition-all",
        selected
          ? "bg-blue-600/20 border-blue-500 text-blue-400"
          : "bg-[var(--bg-elevated)] border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-blue-500/40 hover:text-[var(--text-primary)]"
      )}
    >
      <span className="text-2xl">{icon}</span>
      <span className="text-xs text-center leading-tight">{label}</span>
    </button>
  );
}

// ── Steps ─────────────────────────────────────────────────────────────────────

function Step0({
  answers,
  onAnswer,
}: {
  answers: Answers;
  onAnswer: (key: keyof Answers, val: string) => void;
}) {
  const options = [
    { label: "< 2 years", value: "under_2" },
    { label: "2–5 years", value: "2_5" },
    { label: "5–10 years", value: "5_10" },
    { label: "10–20 years", value: "10_20" },
    { label: "20+ years", value: "over_20" },
  ];
  return (
    <div>
      <StepHeading>When do you need this money?</StepHeading>
      <div className="flex flex-wrap justify-center gap-3">
        {options.map((o) => (
          <PillButton
            key={o.value}
            selected={answers.time_horizon === o.value}
            onClick={() => onAnswer("time_horizon", o.value)}
          >
            {o.label}
          </PillButton>
        ))}
      </div>
    </div>
  );
}

function Step1({
  answers,
  onAnswer,
}: {
  answers: Answers;
  onAnswer: (key: keyof Answers, val: string) => void;
}) {
  const options = [
    { icon: "🏖️", label: "Retirement", value: "retirement" },
    { icon: "🏠", label: "House", value: "house" },
    { icon: "🎓", label: "Education", value: "education" },
    { icon: "🛡️", label: "Emergency", value: "emergency" },
    { icon: "📈", label: "Wealth-Building", value: "wealth" },
    { icon: "💰", label: "Income", value: "income" },
  ];
  return (
    <div>
      <StepHeading>What's this account for?</StepHeading>
      <div className="grid grid-cols-3 gap-3">
        {options.map((o) => (
          <IconCard
            key={o.value}
            icon={o.icon}
            label={o.label}
            selected={answers.goal_type === o.value}
            onClick={() => onAnswer("goal_type", o.value)}
          />
        ))}
      </div>
    </div>
  );
}

function Step2({
  answers,
  onAnswer,
  onSlider,
}: {
  answers: Answers;
  onAnswer: (key: keyof Answers, val: string) => void;
  onSlider: (key: keyof Answers, val: number) => void;
}) {
  const brackets = [
    { label: "< $50k", value: "under_50k" },
    { label: "$50–100k", value: "50_100k" },
    { label: "$100–200k", value: "100_200k" },
    { label: "$200–500k", value: "200_500k" },
    { label: "$500k+", value: "over_500k" },
  ];
  const savings = answers.savings_rate ?? 10;
  return (
    <div className="space-y-6">
      <StepHeading>Income & savings</StepHeading>
      <div className="space-y-2">
        <label className="text-sm font-medium text-[var(--text-secondary)]">Annual income bracket</label>
        <select
          value={answers.income_bracket ?? ""}
          onChange={(e) => onAnswer("income_bracket", e.target.value)}
          className="w-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-blue-500 transition-colors"
        >
          <option value="" disabled>Select income range…</option>
          {brackets.map((b) => (
            <option key={b.value} value={b.value}>{b.label}</option>
          ))}
        </select>
      </div>
      <div className="space-y-3">
        <p className="text-sm text-[var(--text-secondary)] text-center">
          You save{" "}
          <span className="font-bold text-[var(--text-primary)]">{savings}%</span>{" "}
          of your income monthly
        </p>
        <input
          type="range"
          min={0}
          max={50}
          step={5}
          value={savings}
          onChange={(e) => onSlider("savings_rate", Number(e.target.value))}
          className="w-full accent-blue-500 cursor-pointer"
        />
        <div className="flex justify-between text-xs text-[var(--text-tertiary)]">
          <span>0%</span>
          <span>50%</span>
        </div>
      </div>
    </div>
  );
}

function Step3({
  answers,
  onAnswer,
}: {
  answers: Answers;
  onAnswer: (key: keyof Answers, val: string) => void;
}) {
  const options = [
    { icon: "😰", label: "Sell everything", value: "sell_all" },
    { icon: "😟", label: "Sell some", value: "sell_some" },
    { icon: "😐", label: "Hold tight", value: "hold" },
    { icon: "😀", label: "Buy more", value: "buy_more" },
  ];
  return (
    <div>
      <StepHeading>
        If your $10,000 dropped to $7,000 in a single month, you would:
      </StepHeading>
      <div className="grid grid-cols-2 gap-3">
        {options.map((o) => (
          <button
            key={o.value}
            onClick={() => onAnswer("loss_tolerance", o.value)}
            className={cn(
              "flex flex-col items-center gap-3 py-6 rounded-xl border text-sm font-medium transition-all",
              answers.loss_tolerance === o.value
                ? "bg-blue-600/20 border-blue-500 text-blue-400"
                : "bg-[var(--bg-elevated)] border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-blue-500/40"
            )}
          >
            <span className="text-3xl">{o.icon}</span>
            <span>{o.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function Step4({
  answers,
  onAnswer,
}: {
  answers: Answers;
  onAnswer: (key: keyof Answers, val: string) => void;
}) {
  const options = [
    { icon: "📚", label: "Just starting", value: "beginner" },
    { icon: "📊", label: "Some experience", value: "intermediate" },
    { icon: "💼", label: "Experienced", value: "experienced" },
    { icon: "🏦", label: "Professional", value: "professional" },
  ];
  return (
    <div>
      <StepHeading>How experienced are you with investing?</StepHeading>
      <div className="grid grid-cols-2 gap-3">
        {options.map((o) => (
          <IconCard
            key={o.value}
            icon={o.icon}
            label={o.label}
            selected={answers.experience === o.value}
            onClick={() => onAnswer("experience", o.value)}
          />
        ))}
      </div>
    </div>
  );
}

function Step5({
  answers,
  onAnswer,
}: {
  answers: Answers;
  onAnswer: (key: keyof Answers, val: boolean) => void;
}) {
  return (
    <div>
      <StepHeading>
        Can you cover 6 months of expenses without touching this account?
      </StepHeading>
      <div className="flex gap-4 justify-center">
        {[
          { icon: "✅", label: "Yes", val: true },
          { icon: "❌", label: "No", val: false },
        ].map(({ icon, label, val }) => (
          <button
            key={label}
            onClick={() => onAnswer("has_emergency_fund", val)}
            className={cn(
              "flex flex-col items-center gap-3 py-8 px-12 rounded-xl border text-sm font-semibold transition-all",
              answers.has_emergency_fund === val
                ? "bg-blue-600/20 border-blue-500 text-blue-400"
                : "bg-[var(--bg-elevated)] border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-blue-500/40"
            )}
          >
            <span className="text-3xl">{icon}</span>
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Result Card ───────────────────────────────────────────────────────────────

function ResultCard({
  result,
  onNavigate,
}: {
  result: { risk_score: number; target_allocation: Record<string, number>; portfolio_type: string };
  onNavigate: () => void;
}) {
  const alloc = result.target_allocation;
  const equity = alloc.equity ?? 0;
  const bonds = alloc.bonds ?? 0;
  const cash = alloc.cash ?? 0;

  function Bar({ pct, color }: { pct: number; color: string }) {
    return (
      <div className="h-2 rounded-full bg-[var(--border-subtle)] overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
    );
  }

  return (
    <div className="text-center space-y-6">
      <div>
        <p className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-widest mb-1">
          Your Risk Profile
        </p>
        <h2 className="text-2xl font-bold text-[var(--text-primary)]">
          {result.portfolio_type.replace(/_/g, " ").toUpperCase()}
        </h2>
        <p className="text-sm text-[var(--text-tertiary)] mt-1">
          Score:{" "}
          <span className="text-[var(--text-primary)] font-semibold">
            {result.risk_score.toFixed(1)} / 10.0
          </span>
        </p>
      </div>

      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-3 text-left">
        <p className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-2">
          Suggested Portfolio
        </p>
        {[
          { label: "Stocks", pct: equity, color: "#3B82F6" },
          { label: "Bonds", pct: bonds, color: "#22C55E" },
          { label: "Cash", pct: cash, color: "#64748B" },
        ].map(({ label, pct, color }) => (
          <div key={label} className="space-y-1">
            <div className="flex justify-between text-sm">
              <span className="text-[var(--text-secondary)]">{label}</span>
              <span className="font-semibold text-[var(--text-primary)]">{pct}%</span>
            </div>
            <Bar pct={pct} color={color} />
          </div>
        ))}
      </div>

      <button
        onClick={onNavigate}
        className="flex items-center gap-2 mx-auto px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-semibold transition-colors"
      >
        View Your Portfolio
        <ChevronRight size={18} />
      </button>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const TOTAL_STEPS = 6;

export default function RiskQuizPage() {
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = useState(0);
  const [direction, setDirection] = useState<"forward" | "back">("forward");
  const [animating, setAnimating] = useState(false);
  const [answers, setAnswers] = useState<Answers>({});
  const [calculating, setCalculating] = useState(false);
  const [result, setResult] = useState<{
    risk_score: number;
    target_allocation: Record<string, number>;
    portfolio_type: string;
    message: string;
  } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const mutation = useMutation({
    mutationFn: submitQuiz,
    onSuccess: (data) => {
      setResult(data);
      setCalculating(false);
    },
    onError: () => {
      toast.error("Failed to calculate risk profile. Please try again.");
      setCalculating(false);
    },
  });

  // Animate step transitions
  function goStep(nextStep: number, dir: "forward" | "back") {
    if (animating) return;
    setDirection(dir);
    setAnimating(true);
    setTimeout(() => {
      setCurrentStep(nextStep);
      setAnimating(false);
    }, 300);
  }

  function handleAnswer<K extends keyof Answers>(key: K, val: Answers[K]) {
    setAnswers((prev) => ({ ...prev, [key]: val }));
    // Auto-advance after a short delay for tap-feel
    setTimeout(() => {
      if (currentStep < TOTAL_STEPS - 1) {
        goStep(currentStep + 1, "forward");
      }
    }, 180);
  }

  function handleSlider(key: keyof Answers, val: number) {
    setAnswers((prev) => ({ ...prev, [key]: val }));
  }

  function handleBack() {
    if (currentStep > 0) goStep(currentStep - 1, "back");
  }

  function handleSubmit() {
    if (answers.has_emergency_fund === undefined) return;
    setCalculating(true);
    setTimeout(() => {
      mutation.mutate(answers);
    }, 1000);
  }

  // Auto-submit after step 5 answer is set
  useEffect(() => {
    if (currentStep === 5 && answers.has_emergency_fund !== undefined && !result && !calculating) {
      handleSubmit();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answers.has_emergency_fund, currentStep]);

  const progressPct = (currentStep / TOTAL_STEPS) * 100;

  const slideStyle: React.CSSProperties = {
    transform: animating
      ? direction === "forward"
        ? "translateX(-40px)"
        : "translateX(40px)"
      : "translateX(0)",
    opacity: animating ? 0 : 1,
    transition: "transform 300ms ease, opacity 300ms ease",
  };

  return (
    <div className="min-h-screen bg-[var(--bg-base,#0f172a)] flex flex-col">
      {/* Progress bar */}
      <div className="h-1 bg-[var(--border-subtle)] w-full">
        <div
          className="h-full bg-blue-500 transition-all duration-500"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Top nav */}
      <div className="flex items-center px-4 pt-4 pb-2 max-w-lg mx-auto w-full">
        {currentStep > 0 && !result && !calculating && (
          <button
            onClick={handleBack}
            className="flex items-center gap-1 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-sm transition-colors"
          >
            <ArrowLeft size={16} />
            Back
          </button>
        )}
        <span className="ml-auto text-xs text-[var(--text-tertiary)]">
          {result ? "Done" : `${currentStep + 1} of ${TOTAL_STEPS}`}
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 flex items-center justify-center px-4 py-8">
        <div className="w-full max-w-lg" ref={containerRef}>
          {calculating ? (
            <div className="flex flex-col items-center gap-4 py-16">
              <Loader2 size={40} className="text-blue-400 animate-spin" />
              <p className="text-[var(--text-secondary)] font-medium">
                Calculating your profile…
              </p>
            </div>
          ) : result ? (
            <div style={slideStyle}>
              <ResultCard result={result} onNavigate={() => navigate("/robo")} />
            </div>
          ) : (
            <div style={slideStyle}>
              {currentStep === 0 && (
                <Step0 answers={answers} onAnswer={handleAnswer} />
              )}
              {currentStep === 1 && (
                <Step1 answers={answers} onAnswer={handleAnswer} />
              )}
              {currentStep === 2 && (
                <Step2
                  answers={answers}
                  onAnswer={handleAnswer}
                  onSlider={handleSlider}
                />
              )}
              {currentStep === 3 && (
                <Step3 answers={answers} onAnswer={handleAnswer} />
              )}
              {currentStep === 4 && (
                <Step4 answers={answers} onAnswer={handleAnswer} />
              )}
              {currentStep === 5 && (
                <Step5
                  answers={answers}
                  onAnswer={(key, val) => handleAnswer(key, val)}
                />
              )}

              {/* Manual next for step 2 (slider) */}
              {currentStep === 2 && (
                <div className="flex justify-end mt-6">
                  <button
                    onClick={() => goStep(3, "forward")}
                    disabled={!answers.income_bracket}
                    className={cn(
                      "flex items-center gap-1 px-5 py-2.5 rounded-xl text-sm font-semibold transition-colors",
                      answers.income_bracket
                        ? "bg-blue-600 hover:bg-blue-500 text-white"
                        : "bg-[var(--border-subtle)] text-[var(--text-tertiary)] cursor-not-allowed"
                    )}
                  >
                    Continue <ChevronRight size={16} />
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

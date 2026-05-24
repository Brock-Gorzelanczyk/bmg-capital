import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight, Landmark, Star } from "lucide-react";
import { cn } from "@/lib/utils";
import client from "@/api/client";
import { seedDemo } from "@/api/paper";

interface OnboardingData {
  goal: string;
  experience: string;
  risk_tolerance: string;
  time_horizon: string;
}

const TOTAL_STEPS = 6;

function Progress({ step }: { step: number }) {
  return (
    <div className="flex items-center gap-1.5 mb-8">
      {Array.from({ length: TOTAL_STEPS }, (_, i) => (
        <div
          key={i}
          className={cn(
            "h-1 rounded-full flex-1 transition-all duration-300",
            i < step ? "bg-white" : i === step ? "bg-zinc-500" : "bg-zinc-800"
          )}
        />
      ))}
    </div>
  );
}

interface OptionCardProps {
  label: string;
  description?: string;
  emoji?: string;
  selected: boolean;
  onClick: () => void;
}

function OptionCard({ label, description, emoji, selected, onClick }: OptionCardProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left px-5 py-4 rounded-2xl border transition-all duration-150 group",
        selected
          ? "border-white bg-white/10 text-white"
          : "border-zinc-800 bg-zinc-950 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200"
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {emoji && <span className="text-2xl">{emoji}</span>}
          <div>
            <div className={cn("font-semibold text-sm", selected ? "text-white" : "text-zinc-300")}>{label}</div>
            {description && <div className="text-xs text-zinc-600 mt-0.5">{description}</div>}
          </div>
        </div>
        {selected && <CheckCircle2 size={18} className="text-white shrink-0" />}
      </div>
    </button>
  );
}

export default function Onboarding() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [data, setData] = useState<OnboardingData>({
    goal: "",
    experience: "",
    risk_tolerance: "",
    time_horizon: "",
  });

  const completeMut = useMutation({
    mutationFn: (body: OnboardingData) =>
      client.post("/api/onboarding/complete", body).then((r) => r.data),
    onSuccess: () => {
      localStorage.setItem("bmg_onboarded", "1");
      setStep(5); // welcome screen
    },
  });

  const canAdvance = () => {
    if (step === 1) return !!data.goal;
    if (step === 2) return !!data.experience;
    if (step === 3) return !!data.risk_tolerance;
    if (step === 4) return !!data.time_horizon;
    return true;
  };

  const advance = () => {
    if (step === 4) {
      completeMut.mutate(data);
      return;
    }
    setStep((s) => s + 1);
  };

  return (
    <div className="min-h-screen bg-[#020617] flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        {step > 0 && step < 5 && <Progress step={step} />}

        {/* Step 0 — Welcome */}
        {step === 0 && (
          <div className="text-center space-y-6">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[#3B82F6] to-[#8B5CF6] flex items-center justify-center mx-auto text-2xl font-bold text-white shadow-lg shadow-blue-500/20">B</div>
            <div>
              <h1 className="text-3xl font-bold text-[#F8FAFC] mb-2">Welcome to BMG Capital</h1>
              <p className="text-[#475569] text-base">Let's personalize your experience. It takes 60 seconds.</p>
            </div>
            <button
              onClick={() => setStep(1)}
              className="w-full bg-[#3B82F6] hover:bg-[#2563EB] active:scale-[0.98] text-white font-bold py-3.5 rounded-2xl transition-all shadow-lg shadow-blue-900/30 flex items-center justify-center gap-2"
            >
              Get started <ChevronRight size={18} />
            </button>
            <button
              onClick={async () => {
                try {
                  await seedDemo();
                } catch (err) {
                  console.error("Demo seed failed:", err);
                  // Don't block onboarding for this
                }
                localStorage.setItem("bmg_onboarded", "1");
                navigate("/");
              }}
              className="flex items-center justify-center gap-2 text-[#94A3B8] hover:text-[#F8FAFC] text-sm transition-colors"
            >
              <span className="w-2 h-2 rounded-full bg-[#22C55E] animate-pulse" />
              Skip — load demo data
            </button>
          </div>
        )}

        {/* Step 1 — Goal */}
        {step === 1 && (
          <div className="space-y-5">
            <div>
              <p className="text-zinc-500 text-sm mb-1">Step 1 of 4</p>
              <h2 className="text-2xl font-bold text-white">What brings you here?</h2>
            </div>
            <div className="space-y-2">
              {[
                { value: "invest", label: "Long-term investing", description: "Build wealth over years with a buy-and-hold mindset", emoji: "🌱" },
                { value: "trade", label: "Active trading", description: "Capitalize on short-term price moves and signals", emoji: "⚡" },
                { value: "learn", label: "Learning the markets", description: "Build financial knowledge from the ground up", emoji: "📚" },
                { value: "all", label: "All of the above", description: "A little bit of everything", emoji: "🎯" },
              ].map((opt) => (
                <OptionCard
                  key={opt.value}
                  label={opt.label}
                  description={opt.description}
                  emoji={opt.emoji}
                  selected={data.goal === opt.value}
                  onClick={() => setData((d) => ({ ...d, goal: opt.value }))}
                />
              ))}
            </div>
          </div>
        )}

        {/* Step 2 — Experience */}
        {step === 2 && (
          <div className="space-y-5">
            <div>
              <p className="text-zinc-500 text-sm mb-1">Step 2 of 4</p>
              <h2 className="text-2xl font-bold text-white">How much experience do you have?</h2>
            </div>
            <div className="space-y-2">
              {[
                { value: "beginner", label: "Beginner", description: "Just starting out, learning the basics", emoji: "🌱" },
                { value: "intermediate", label: "Intermediate", description: "Familiar with stocks, options, and basic analysis", emoji: "📈" },
                { value: "advanced", label: "Advanced", description: "Experienced with complex strategies and derivatives", emoji: "🏆" },
              ].map((opt) => (
                <OptionCard
                  key={opt.value}
                  label={opt.label}
                  description={opt.description}
                  emoji={opt.emoji}
                  selected={data.experience === opt.value}
                  onClick={() => setData((d) => ({ ...d, experience: opt.value }))}
                />
              ))}
            </div>
          </div>
        )}

        {/* Step 3 — Risk */}
        {step === 3 && (
          <div className="space-y-5">
            <div>
              <p className="text-zinc-500 text-sm mb-1">Step 3 of 4</p>
              <h2 className="text-2xl font-bold text-white">What's your risk tolerance?</h2>
              <p className="text-zinc-600 text-sm mt-1">How comfortable are you with potential losses?</p>
            </div>
            <div className="space-y-2">
              {[
                { value: "conservative", label: "Conservative", description: "Prioritize capital preservation, minimal volatility", emoji: "🛡️" },
                { value: "moderate", label: "Moderate", description: "Balance growth and safety, accept some fluctuation", emoji: "⚖️" },
                { value: "aggressive", label: "Aggressive", description: "Maximize returns, comfortable with significant swings", emoji: "🚀" },
              ].map((opt) => (
                <OptionCard
                  key={opt.value}
                  label={opt.label}
                  description={opt.description}
                  emoji={opt.emoji}
                  selected={data.risk_tolerance === opt.value}
                  onClick={() => setData((d) => ({ ...d, risk_tolerance: opt.value }))}
                />
              ))}
            </div>
          </div>
        )}

        {/* Step 4 — Time horizon */}
        {step === 4 && (
          <div className="space-y-5">
            <div>
              <p className="text-zinc-500 text-sm mb-1">Step 4 of 4</p>
              <h2 className="text-2xl font-bold text-white">What's your time horizon?</h2>
              <p className="text-zinc-600 text-sm mt-1">How long do you plan to keep money invested?</p>
            </div>
            <div className="space-y-2">
              {[
                { value: "short", label: "Less than 1 year", description: "Short-term opportunities and quick gains", emoji: "⏱️" },
                { value: "medium", label: "1–5 years", description: "Medium-term growth with some flexibility", emoji: "📅" },
                { value: "long", label: "5–10 years", description: "Patient investing through market cycles", emoji: "🗓️" },
                { value: "very_long", label: "10+ years", description: "Long-term wealth building for retirement or goals", emoji: "🌅" },
              ].map((opt) => (
                <OptionCard
                  key={opt.value}
                  label={opt.label}
                  description={opt.description}
                  emoji={opt.emoji}
                  selected={data.time_horizon === opt.value}
                  onClick={() => setData((d) => ({ ...d, time_horizon: opt.value }))}
                />
              ))}
            </div>
          </div>
        )}

        {/* Step 5 — Done */}
        {step === 5 && (
          <div className="text-center space-y-6">
            <div className="w-16 h-16 bg-emerald-500 rounded-full flex items-center justify-center mx-auto">
              <CheckCircle2 size={32} className="text-white" />
            </div>
            <div>
              <h2 className="text-3xl font-bold text-white mb-2">You're all set!</h2>
              <p className="text-zinc-500">Your profile has been saved. We've personalized your experience based on your answers.</p>
            </div>
            <div className="bg-amber-950/40 border border-amber-800 rounded-2xl p-4 flex items-center gap-3">
              <Star size={20} className="text-amber-400 shrink-0" />
              <div className="text-left">
                <div className="text-amber-400 font-semibold text-sm">+100 XP Welcome Bonus</div>
                <div className="text-zinc-500 text-xs">Added to your learning progress</div>
              </div>
            </div>
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 flex items-center gap-3 opacity-60">
              <Landmark size={20} className="text-zinc-400 shrink-0" />
              <div className="text-left">
                <div className="text-zinc-300 font-semibold text-sm">Bank Link</div>
                <div className="text-zinc-600 text-xs">Coming soon — you'll be notified when ACH deposits are available</div>
              </div>
            </div>
            <button
              onClick={() => navigate("/")}
              className="w-full bg-white text-black font-bold py-3.5 rounded-2xl hover:bg-zinc-200 transition-colors"
            >
              Go to Dashboard
            </button>
          </div>
        )}

        {/* Navigation */}
        {step > 0 && step < 5 && (
          <div className="flex items-center justify-between mt-6">
            <button
              onClick={() => setStep((s) => s - 1)}
              className="text-zinc-600 text-sm hover:text-zinc-400 transition-colors"
            >
              ← Back
            </button>
            <button
              onClick={advance}
              disabled={!canAdvance() || completeMut.isPending}
              className={cn(
                "flex items-center gap-2 px-6 py-2.5 rounded-xl font-semibold text-sm transition-all",
                canAdvance() && !completeMut.isPending
                  ? "bg-white text-black hover:bg-zinc-200"
                  : "bg-zinc-800 text-zinc-600 cursor-not-allowed"
              )}
            >
              {step === 4 ? (completeMut.isPending ? "Saving…" : "Finish") : "Continue"}
              {step < 4 && <ChevronRight size={16} />}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

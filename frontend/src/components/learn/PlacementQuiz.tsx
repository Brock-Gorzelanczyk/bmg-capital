import { useState } from "react";
import { ChevronRight, GraduationCap } from "lucide-react";
import { TRACKS } from "@/data/curriculum";
import { cn } from "@/lib/utils";

interface Props {
  onComplete: (trackId: string) => void;
}

const QUESTIONS: { id: string; question: string; options: { label: string; score: Record<string, number> }[] }[] = [
  {
    id: "q1",
    question: "How would you describe your investing experience?",
    options: [
      { label: "I'm brand new — haven't bought a stock yet", score: { "investing-fundamentals": 3, "taxes": 2 } },
      { label: "I've bought a few stocks but don't have a strategy", score: { "investing-fundamentals": 2, "technical-analysis": 1 } },
      { label: "I've been investing for 1–3 years with a basic strategy", score: { "technical-analysis": 2, "fundamental-analysis": 2 } },
      { label: "I'm experienced — looking to sharpen specific skills", score: { "technical-analysis": 1, "fundamental-analysis": 1, "options-basics": 2, "behavioral-finance": 1 } },
    ],
  },
  {
    id: "q2",
    question: "What's your primary goal right now?",
    options: [
      { label: "Understand the basics — what is a stock, how do markets work", score: { "investing-fundamentals": 3 } },
      { label: "Learn to read charts and time entries/exits better", score: { "technical-analysis": 3, "behavioral-finance": 1 } },
      { label: "Evaluate companies using financial statements", score: { "fundamental-analysis": 3 } },
      { label: "Learn options strategies for income or hedging", score: { "options-basics": 3 } },
    ],
  },
  {
    id: "q3",
    question: "What do you find most confusing about investing?",
    options: [
      { label: "All of it — I don't know where to start", score: { "investing-fundamentals": 3 } },
      { label: "Why stocks move up and down day-to-day", score: { "technical-analysis": 2, "macro": 1 } },
      { label: "How to tell if a company is actually good", score: { "fundamental-analysis": 3 } },
      { label: "Managing risk and not losing money in bear markets", score: { "portfolio-risk": 3, "behavioral-finance": 2 } },
    ],
  },
  {
    id: "q4",
    question: "How much time can you dedicate to learning each week?",
    options: [
      { label: "5–10 minutes — short lessons only", score: { "investing-fundamentals": 2, "taxes": 1 } },
      { label: "15–30 minutes — a couple of solid lessons", score: { "technical-analysis": 1, "fundamental-analysis": 1 } },
      { label: "30–60 minutes — I'm committed", score: { "technical-analysis": 2, "fundamental-analysis": 2, "options-basics": 1 } },
      { label: "As much as it takes — I'm serious about this", score: { "technical-analysis": 2, "fundamental-analysis": 2, "options-basics": 2 } },
    ],
  },
  {
    id: "q5",
    question: "What type of investor do you want to become?",
    options: [
      { label: "Long-term passive investor (buy and hold index funds)", score: { "investing-fundamentals": 2, "portfolio-risk": 2, "taxes": 2 } },
      { label: "Stock picker — find great companies before the crowd", score: { "fundamental-analysis": 3, "macro": 1 } },
      { label: "Technical trader — use charts to time the market", score: { "technical-analysis": 3, "behavioral-finance": 1 } },
      { label: "Options trader — generate income and manage risk", score: { "options-basics": 3, "portfolio-risk": 2 } },
    ],
  },
];

const TRACK_COLORS: Record<string, string> = {
  "investing-fundamentals": "emerald",
  "technical-analysis": "blue",
  "fundamental-analysis": "violet",
  "options-basics": "amber",
  "portfolio-risk": "rose",
  "behavioral-finance": "purple",
  "taxes": "teal",
  "crypto": "orange",
  "macro": "cyan",
};

export default function PlacementQuiz({ onComplete }: Props) {
  const [step, setStep] = useState(0);
  const [scores, setScores] = useState<Record<string, number>>({});
  const [showResult, setShowResult] = useState(false);
  const [recommended, setRecommended] = useState<string | null>(null);

  const q = QUESTIONS[step];

  const handleSelect = (optScore: Record<string, number>) => {
    const updated = { ...scores };
    for (const [k, v] of Object.entries(optScore)) {
      updated[k] = (updated[k] ?? 0) + v;
    }
    setScores(updated);

    if (step + 1 >= QUESTIONS.length) {
      const best = Object.entries(updated).sort(([, a], [, b]) => b - a)[0]?.[0] ?? "investing-fundamentals";
      setRecommended(best);
      setShowResult(true);
    } else {
      setStep((s) => s + 1);
    }
  };

  const track = TRACKS.find((t) => t.id === recommended);

  if (showResult && track) {
    return (
      <div className="max-w-lg mx-auto text-center space-y-6 py-8">
        <div className="text-5xl">{track.icon}</div>
        <div>
          <p className="text-zinc-500 text-sm mb-2">We recommend starting with</p>
          <h2 className="text-2xl font-bold text-white">{track.title}</h2>
          <p className="text-zinc-400 text-sm mt-2 leading-relaxed">{track.description}</p>
        </div>
        <div className="flex gap-3 justify-center">
          <button
            onClick={() => onComplete(track.id)}
            className="bg-white text-black font-semibold px-6 py-2.5 rounded-lg hover:bg-zinc-200 transition-colors flex items-center gap-2"
          >
            Start this track <ChevronRight size={16} />
          </button>
          <button
            onClick={() => setShowResult(false)}
            className="text-zinc-500 hover:text-white text-sm transition-colors"
          >
            Browse all tracks
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-lg mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <GraduationCap size={20} className="text-emerald-400" />
        <div>
          <h2 className="text-white font-semibold">Quick Placement</h2>
          <p className="text-zinc-500 text-xs">Question {step + 1} of {QUESTIONS.length}</p>
        </div>
        <div className="ml-auto flex gap-1">
          {QUESTIONS.map((_, i) => (
            <div key={i} className={cn("w-6 h-1 rounded-full", i <= step ? "bg-emerald-500" : "bg-zinc-800")} />
          ))}
        </div>
      </div>

      <p className="text-lg font-medium text-white leading-snug">{q.question}</p>

      <div className="space-y-2">
        {q.options.map((opt, i) => (
          <button
            key={i}
            onClick={() => handleSelect(opt.score)}
            className="w-full text-left px-4 py-3.5 rounded-xl border border-zinc-800 text-zinc-300 text-sm hover:border-emerald-500/50 hover:text-white hover:bg-emerald-500/5 transition-all"
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

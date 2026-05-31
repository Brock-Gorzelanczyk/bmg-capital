import { useState } from "react";
import { BarChart2, Zap, BookOpen, Bitcoin } from "lucide-react";
import type { DemoPersona } from "@/lib/demoMode";
import { useDemoStore } from "@/lib/demo/demoStore";

interface PersonaCard {
  id: DemoPersona;
  label: string;
  description: string;
  icon: React.ReactNode;
  accent: string;
  border: string;
  bg: string;
  iconBg: string;
}

const CARDS: PersonaCard[] = [
  {
    id: "long_term",
    label: "Long-Term Investor",
    description: "Balanced portfolio, dividends, retirement track",
    icon: <BarChart2 size={22} />,
    accent: "text-[#22C55E]",
    border: "border-[#22C55E]/30",
    bg: "bg-[#22C55E]/6",
    iconBg: "bg-[#22C55E]/12 text-[#22C55E]",
  },
  {
    id: "active_trader",
    label: "Active Trader",
    description: "87 trades, 3 strategies running, 3.2% day gain",
    icon: <Zap size={22} />,
    accent: "text-[#3B82F6]",
    border: "border-[#3B82F6]/30",
    bg: "bg-[#3B82F6]/6",
    iconBg: "bg-[#3B82F6]/12 text-[#3B82F6]",
  },
  {
    id: "crypto",
    label: "Crypto Enthusiast",
    description: "BTC, ETH, SOL + 5 DeFi positions",
    icon: <Bitcoin size={22} />,
    accent: "text-[#F97316]",
    border: "border-[#F97316]/30",
    bg: "bg-[#F97316]/6",
    iconBg: "bg-[#F97316]/12 text-[#F97316]",
  },
  {
    id: "beginner",
    label: "Beginner Learner",
    description: "Learning Center, 12-day streak, paper trading",
    icon: <BookOpen size={22} />,
    accent: "text-[#A855F7]",
    border: "border-[#A855F7]/30",
    bg: "bg-[#A855F7]/6",
    iconBg: "bg-[#A855F7]/12 text-[#A855F7]",
  },
];

interface PersonaSelectorProps {
  onComplete: () => void;
}

export default function PersonaSelector({ onComplete }: PersonaSelectorProps) {
  const [selected, setSelected] = useState<DemoPersona>("long_term");

  function handleStart() {
    useDemoStore.getState().setPersona(selected);
    onComplete();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm px-4">
      <div className="w-full max-w-2xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl shadow-2xl p-6 md:p-8">
        {/* Header */}
        <div className="flex flex-col items-center text-center mb-7">
          <div className="w-10 h-10 bg-white rounded-xl flex items-center justify-center text-sm font-bold text-black mb-4">
            B
          </div>
          <h1 className="text-xl font-semibold text-[var(--text-primary)] mb-1">
            Welcome to BMG Capital Demo
          </h1>
          <p className="text-sm text-[var(--text-secondary)] max-w-md">
            Choose a persona to explore the platform with realistic pre-loaded data. No real money, no sign-up required.
          </p>
        </div>

        {/* Persona cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-6">
          {CARDS.map((card) => {
            const isActive = selected === card.id;
            return (
              <button
                key={card.id}
                onClick={() => setSelected(card.id)}
                className={[
                  "flex items-start gap-3 p-4 rounded-xl border text-left transition-all duration-150 cursor-pointer",
                  isActive
                    ? `${card.border} ${card.bg}`
                    : "border-[var(--border-subtle)] bg-[var(--bg-base)] hover:border-[var(--border-emphasis)]",
                ].join(" ")}
              >
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 ${card.iconBg}`}>
                  {card.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <div className={`text-sm font-medium mb-0.5 ${isActive ? card.accent : "text-[var(--text-primary)]"}`}>
                    {card.label}
                  </div>
                  <div className="text-xs text-[var(--text-tertiary)] leading-snug">
                    {card.description}
                  </div>
                </div>
                {/* Selection indicator */}
                <div className={[
                  "w-4 h-4 rounded-full border-2 shrink-0 mt-0.5 transition-all duration-150",
                  isActive ? `border-current bg-current ${card.accent}` : "border-[var(--border-emphasis)]",
                ].join(" ")} />
              </button>
            );
          })}
        </div>

        {/* Start button */}
        <button
          onClick={handleStart}
          className="w-full h-11 bg-[#3B82F6] hover:bg-[#2563EB] text-white rounded-xl font-medium text-sm transition-colors duration-150 cursor-pointer"
        >
          Start Demo
        </button>

        <p className="text-center text-xs text-[var(--text-tertiary)] mt-3">
          You can switch personas at any time from the top bar.
        </p>
      </div>
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Lock, Flame } from "lucide-react";
import { getMilestones, getStreak } from "@/api/portfolio";
import type { Milestone } from "@/api/portfolio";
import { cn } from "@/lib/utils";

// ── Confetti ──────────────────────────────────────────────────────────────────

const CONFETTI_COLORS = ["#3B82F6", "#22C55E", "#F59E0B", "#EF4444", "#8B5CF6", "#F97316", "#EC4899"];

interface ConfettiDot {
  id: number;
  x: number;
  y: number;
  color: string;
  size: number;
  delay: number;
  duration: number;
}

function Confetti({ active }: { active: boolean }) {
  const dots: ConfettiDot[] = Array.from({ length: 40 }, (_, i) => ({
    id: i,
    x: Math.random() * 100,
    y: Math.random() * 100,
    color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
    size: 4 + Math.random() * 6,
    delay: Math.random() * 800,
    duration: 1000 + Math.random() * 1000,
  }));

  if (!active) return null;

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden rounded-xl z-10">
      {dots.map((dot) => (
        <span
          key={dot.id}
          className="absolute rounded-full animate-confetti-fall"
          style={{
            left: `${dot.x}%`,
            top: `-${dot.size}px`,
            width: dot.size,
            height: dot.size,
            backgroundColor: dot.color,
            animationDelay: `${dot.delay}ms`,
            animationDuration: `${dot.duration}ms`,
          }}
        />
      ))}
    </div>
  );
}

// ── Milestone Card ────────────────────────────────────────────────────────────

function MilestoneCard({ milestone }: { milestone: Milestone }) {
  return (
    <div
      className={cn(
        "relative flex flex-col items-center gap-2 p-4 rounded-xl border text-center transition-all",
        milestone.achieved
          ? "border-green-500/40 bg-green-500/5 shadow-[0_0_12px_2px_rgba(34,197,94,0.15)]"
          : "border-[var(--border-subtle)] bg-[var(--bg-elevated-2)] opacity-60"
      )}
    >
      {/* Emoji */}
      <div className="text-3xl leading-none mt-1">
        {milestone.achieved ? (
          milestone.icon_emoji
        ) : (
          <span className="relative inline-block">
            <span className="opacity-30">{milestone.icon_emoji}</span>
            <Lock
              size={14}
              className="absolute -bottom-1 -right-1 text-[var(--text-tertiary)]"
            />
          </span>
        )}
      </div>

      {/* Label */}
      <div className="text-xs font-semibold text-[var(--text-primary)] leading-tight">
        {milestone.label}
      </div>

      {/* Description */}
      <div className="text-[10px] text-[var(--text-tertiary)] leading-tight">
        {milestone.description}
      </div>

      {/* Status badge */}
      {milestone.achieved ? (
        <span className="mt-auto text-[10px] font-bold text-green-400 bg-green-400/10 border border-green-400/20 rounded-full px-2 py-0.5">
          Achieved
        </span>
      ) : (
        <span className="mt-auto text-[10px] text-[var(--text-tertiary)] bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-full px-2 py-0.5">
          Locked
        </span>
      )}
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function MilestonesPanel() {
  const { data: rawMilestones, isLoading: milestonesLoading } = useQuery({
    queryKey: ["portfolio-milestones"],
    queryFn: getMilestones,
    staleTime: 60_000,
  });
  const milestones = Array.isArray(rawMilestones) ? rawMilestones : [];

  const { data: streak } = useQuery({
    queryKey: ["portfolio-streak"],
    queryFn: getStreak,
    staleTime: 60_000,
  });

  // Track if any milestone was achieved on first render (for confetti)
  const seenRef = useRef(false);
  const [showConfetti, setShowConfetti] = useState(false);

  useEffect(() => {
    if (!seenRef.current && milestones.length > 0) {
      seenRef.current = true;
      const hasAchieved = milestones.some((m) => m.achieved);
      if (hasAchieved) {
        setShowConfetti(true);
        const t = setTimeout(() => setShowConfetti(false), 2000);
        return () => clearTimeout(t);
      }
    }
  }, [milestones]);

  const achievedCount = milestones.filter((m) => m.achieved).length;
  const currentStreak = streak?.current_streak_weeks ?? 0;

  return (
    <div className="relative bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
      <Confetti active={showConfetti} />

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-[var(--text-primary)]">Milestones</span>
          <span className="text-[10px] font-mono text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)] px-2 py-0.5 rounded-full">
            {achievedCount}/{milestones.length}
          </span>
        </div>

        {/* Streak badge */}
        {currentStreak > 0 && (
          <div className="flex items-center gap-1.5 bg-orange-500/10 border border-orange-500/20 rounded-full px-3 py-1">
            <Flame size={13} className="text-orange-400" />
            <span className="text-xs font-bold text-orange-400">
              {currentStreak} week streak — keep going!
            </span>
          </div>
        )}
      </div>

      {/* Grid */}
      <div className="p-4">
        {milestonesLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Array.from({ length: 7 }).map((_, i) => (
              <div key={i} className="h-36 animate-pulse bg-[var(--bg-elevated-2)] rounded-xl" />
            ))}
          </div>
        ) : milestones.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center gap-3">
            <div className="text-4xl">🏆</div>
            <p className="text-sm font-semibold text-[var(--text-primary)]">No milestones yet</p>
            <p className="text-xs text-[var(--text-tertiary)]">Start trading to unlock achievements</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {milestones.map((m) => (
              <MilestoneCard key={m.id} milestone={m} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Streak Badge (for Dashboard) ──────────────────────────────────────────────

export function StreakBadgeDashboard({ streak }: { streak: number }) {
  if (streak < 3) return null;
  return (
    <div className="flex items-center gap-1.5 bg-orange-500/10 border border-orange-500/20 rounded-full px-3 py-1">
      <Flame size={13} className="text-orange-400" />
      <span className="text-xs font-bold text-orange-400">{streak}w streak</span>
    </div>
  );
}

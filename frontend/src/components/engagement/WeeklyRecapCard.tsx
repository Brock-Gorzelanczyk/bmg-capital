import { useQuery } from "@tanstack/react-query";
import client from "@/api/client";
import { X } from "lucide-react";
import { useMemo } from "react";

// ─── Types ───────────────────────────────────────────────────────────────────

interface WeeklyRecapData {
  week_label: string;           // e.g. "Mon May 26 – Jun 1"
  streak_days: number;
  lessons_completed: number;
  challenges_completed: number;
  challenges_total: number;
  journals_written: number;
  top_mover_symbol?: string;
  top_mover_pct?: number;
  top_mover_type?: string;      // "paper"
  points_earned: number;
  max_points?: number;          // optional for progress bar
}

// ─── Skeleton ────────────────────────────────────────────────────────────────

function SkeletonBlock({ className }: { className?: string }) {
  return <div className={`animate-pulse bg-white/10 rounded ${className}`} />;
}

// ─── Props ───────────────────────────────────────────────────────────────────

interface WeeklyRecapCardProps {
  onClose?: () => void;
  defaultOpen?: boolean;
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function WeeklyRecapCard({ onClose }: WeeklyRecapCardProps) {
  const { data, isLoading } = useQuery<WeeklyRecapData>({
    queryKey: ["engagement-weekly-recap"],
    queryFn: () => client.get("/api/engagement/recap/weekly").then((r) => r.data),
  });

  // Build share text (no $ values, % only)
  const shareText = useMemo(() => {
    if (!data) return "";
    return [
      "My BMG Capital week:",
      `🔥 ${data.streak_days} streak days · 📚 ${data.lessons_completed} lessons · 🧠 ${data.challenges_completed} challenges`,
      `Week of ${data.week_label}`,
      "bmgcapital.com",
    ].join("\n");
  }, [data]);

  const handleShare = () => {
    if (!shareText) return;
    navigator.clipboard.writeText(shareText).catch(() => {});
  };

  // Progress bar fill for points
  const pointsPct =
    data && data.max_points ? Math.min(data.points_earned / data.max_points, 1) : 0.6;

  return (
    /* Full-screen modal overlay */
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div
        className="relative w-full max-w-md rounded-2xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3 border-b border-[var(--border-subtle)]">
          {isLoading ? (
            <SkeletonBlock className="h-5 w-48" />
          ) : (
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              📊 Week of {data?.week_label}
            </h2>
          )}
          {onClose && (
            <button
              onClick={onClose}
              className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
            >
              <X size={18} />
            </button>
          )}
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-2 gap-px bg-[var(--border-subtle)] border-b border-[var(--border-subtle)]">
          {[
            { emoji: "🔥", label: "Streak days",  value: isLoading ? null : data?.streak_days },
            { emoji: "📚", label: "Lessons",       value: isLoading ? null : data?.lessons_completed },
            {
              emoji: "🧠",
              label: "Challenges",
              value: isLoading
                ? null
                : `${data?.challenges_completed}/${data?.challenges_total}`,
            },
            { emoji: "📝", label: "Journals",      value: isLoading ? null : data?.journals_written },
          ].map(({ emoji, label, value }) => (
            <div key={label} className="bg-[var(--bg-elevated)] px-5 py-4">
              <p className="text-[var(--text-tertiary)] text-xs mb-1">
                {emoji} {label}
              </p>
              {value === null || value === undefined ? (
                <SkeletonBlock className="h-6 w-12" />
              ) : (
                <p className="font-mono text-2xl font-bold text-[var(--text-primary)]">{value}</p>
              )}
            </div>
          ))}
        </div>

        {/* Top mover */}
        <div className="px-5 py-4 border-b border-[var(--border-subtle)]">
          <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-widest mb-1">
            Top Mover
          </p>
          {isLoading ? (
            <SkeletonBlock className="h-6 w-36" />
          ) : data?.top_mover_symbol ? (
            <div className="flex items-baseline gap-2">
              <span className="text-lg font-bold text-[var(--text-primary)]">
                {data.top_mover_symbol}
              </span>
              <span
                className={`font-mono text-sm font-semibold ${
                  (data.top_mover_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400"
                }`}
              >
                {(data.top_mover_pct ?? 0) >= 0 ? "+" : ""}
                {data.top_mover_pct?.toFixed(1)}%
              </span>
              {data.top_mover_type && (
                <span className="text-xs text-[var(--text-tertiary)]">
                  ({data.top_mover_type})
                </span>
              )}
            </div>
          ) : (
            <p className="text-sm text-[var(--text-tertiary)]">No trades this week</p>
          )}
        </div>

        {/* Points earned */}
        <div className="px-5 py-4 border-b border-[var(--border-subtle)]">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-widest">
              Points Earned This Week
            </p>
            {!isLoading && (
              <span className="font-mono text-sm font-bold text-amber-400">
                {data?.points_earned} pts
              </span>
            )}
          </div>
          <div className="h-2 rounded-full bg-white/10 overflow-hidden">
            <div
              className="h-full rounded-full bg-amber-500 transition-all duration-700"
              style={{ width: isLoading ? "0%" : `${pointsPct * 100}%` }}
            />
          </div>
        </div>

        {/* Motivational footer */}
        <div className="px-5 py-4">
          <p className="text-sm text-[var(--text-secondary)] italic mb-4">
            Keep it up! Consistency compounds.
          </p>
          <div className="flex gap-3">
            <button
              onClick={handleShare}
              disabled={isLoading || !data}
              className="flex-1 py-2 rounded-lg border border-[var(--border-subtle)] text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-emphasis)] transition-colors disabled:opacity-40"
            >
              Share
            </button>
            {onClose && (
              <button
                onClick={onClose}
                className="flex-1 py-2 rounded-lg bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium transition-colors"
              >
                Close
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

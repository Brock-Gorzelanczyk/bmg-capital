/**
 * ProgressBar — terminal-styled loading bar with two modes.
 *
 *  • determinate   → pass `progress` (0–100). Bar fills to that percentage.
 *  • indeterminate → omit `progress`. A short green segment slides across the
 *                    track on a loop (via @keyframes progress-indeterminate
 *                    in index.css).
 *
 *  Optional `label` renders above the bar in the panel-header style; optional
 *  `elapsedMs` renders an "Nm Ss" counter on the right. Both are designed to
 *  match the rest of the BMG loading UI (mono font, dim green).
 */
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface ProgressBarProps {
  /** 0–100 — when provided the bar is determinate. Omit for indeterminate. */
  progress?: number;
  /** Optional text rendered above the bar (left side). */
  label?: string;
  /** Optional text rendered above the bar (right side). */
  detail?: string;
  /** When set, show an "elapsed" counter that ticks every second once the
   *  duration exceeds `elapsedThresholdMs` (default 5 s).
   *  Pass `Date.now()` (or whenever the operation started). */
  startedAt?: number;
  /** Hide the elapsed counter until this many ms have passed. */
  elapsedThresholdMs?: number;
  className?: string;
  /** Track height in px. Default 4. */
  height?: number;
}

export function ProgressBar({
  progress,
  label,
  detail,
  startedAt,
  elapsedThresholdMs = 5000,
  className,
  height = 4,
}: ProgressBarProps) {
  const indeterminate = progress == null;
  const elapsedMs = useElapsedMs(startedAt);
  const showElapsed =
    startedAt != null && elapsedMs >= elapsedThresholdMs;

  return (
    <div className={cn("w-full", className)}>
      {(label || detail || showElapsed) && (
        <div className="flex items-center justify-between text-[10px] font-mono-t text-t-mid2 uppercase tracking-widest mb-1.5">
          <span className="truncate">{label}</span>
          <span className="text-t-muted shrink-0 ml-2 tabular-nums">
            {showElapsed && `${formatElapsed(elapsedMs)}`}
            {showElapsed && detail && " · "}
            {detail}
          </span>
        </div>
      )}

      <div
        className="w-full rounded-full overflow-hidden bg-t-bg2/70 border border-t-dim/40 relative"
        style={{ height }}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={indeterminate ? undefined : Math.round(progress!)}
      >
        {indeterminate ? (
          // Sliding green segment — width 33%, animated translateX via
          // keyframe in index.css. Linear gradient gives it soft edges so
          // it reads less like a "ping-pong block" and more like a sweep.
          <div
            className="absolute inset-y-0 left-0 w-1/3 rounded-full bg-[linear-gradient(90deg,rgba(74,222,128,0)_0%,rgba(74,222,128,0.55)_50%,rgba(74,222,128,0)_100%)] [animation:progress-indeterminate_1.4s_ease-in-out_infinite]"
            style={{ height }}
          />
        ) : (
          <div
            className="h-full bg-t-green transition-[width] duration-300 ease-out"
            style={{ width: `${clamp(progress!, 0, 100)}%` }}
          />
        )}
      </div>
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────────

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

/** Tracks elapsed ms since `startedAt`, ticking once per second. Returns 0
 *  when `startedAt` is undefined so callers can safely conditionalize on it.
 *  Only updates state from inside the setInterval callback, so React's
 *  "no setState in effect body" rule is satisfied. */
function useElapsedMs(startedAt: number | undefined): number {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (startedAt == null) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [startedAt]);
  if (startedAt == null || now == null || now < startedAt) return 0;
  return now - startedAt;
}

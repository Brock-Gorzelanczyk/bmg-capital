import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useLocation } from "react-router-dom";
import { Zap, ChevronRight, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import {
  getAutopilotStatus,
  getTodaySummary,
  pauseAll,
  resumeAll,
  type AutopilotStatus,
  type AutopilotSummary,
} from "@/api/autopilot";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeAgo(isoString: string | null): string {
  if (!isoString) return "never";
  const diffMs = Date.now() - new Date(isoString).getTime();
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} min ago`;
  return `${Math.floor(diffSec / 3600)} hr ago`;
}

function mostRecentAction(categories: AutopilotStatus["categories"]): string | null {
  const timestamps = categories
    .map((c) => c.last_action)
    .filter((t): t is string => t !== null)
    .map((t) => new Date(t).getTime());
  if (timestamps.length === 0) return null;
  return new Date(Math.max(...timestamps)).toISOString();
}

// Maps category names coming from the API to readable bullet labels.
// Falls back to the raw name if not found.
const CATEGORY_LABELS: Record<string, string> = {
  trading: "signals fired",
  paper_trades: "paper trades opened",
  closed_trades: "closed",
  news: "news filtered",
  lessons: "lessons curated",
  bills: "bills tracked",
};

function formatCategoryBullet(name: string, count: number): string {
  const label = CATEGORY_LABELS[name] ?? name.replace(/_/g, " ");
  // "closed" bullets get special treatment with a pnl suffix handled separately
  return `${count} ${label}`;
}

// ---------------------------------------------------------------------------
// Animated counter
// ---------------------------------------------------------------------------

function useCountUp(target: number, duration = 1500): number {
  const [value, setValue] = useState(0);
  const frameRef = useRef<number | null>(null);
  const startTimeRef = useRef<number | null>(null);

  useEffect(() => {
    if (target === 0) {
      setValue(0);
      return;
    }

    // Reset
    setValue(0);
    startTimeRef.current = null;

    const step = (timestamp: number) => {
      if (startTimeRef.current === null) startTimeRef.current = timestamp;
      const elapsed = timestamp - startTimeRef.current;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.round(eased * target));
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(step);
      }
    };

    frameRef.current = requestAnimationFrame(step);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [target, duration]);

  return value;
}

// ---------------------------------------------------------------------------
// Safe defaults
// ---------------------------------------------------------------------------

const EMPTY_STATUS: AutopilotStatus = {
  total_actions_today: 0,
  categories: [],
  global_paused: false,
  guardrail_status: "ok",
  health_score: 100,
};

const EMPTY_SUMMARY: AutopilotSummary = {
  total_actions: 0,
  by_category: {},
  highlights: [],
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AutopilotHeroCard() {
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();

  const { data: status = EMPTY_STATUS } = useQuery<AutopilotStatus>({
    queryKey: ["autopilot", "status"],
    queryFn: getAutopilotStatus,
    staleTime: 30_000,
    retry: 1,
    // On error just use the empty default — query returns undefined which falls back via default
  });

  const { data: summary = EMPTY_SUMMARY } = useQuery<AutopilotSummary>({
    queryKey: ["autopilot", "summary", "today"],
    queryFn: getTodaySummary,
    staleTime: 30_000,
    retry: 1,
  });

  const pauseMutation = useMutation({
    mutationFn: pauseAll,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["autopilot"] });
      toast.success("Autopilot paused");
    },
    onError: () => toast.error("Could not pause autopilot"),
  });

  const resumeMutation = useMutation({
    mutationFn: resumeAll,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["autopilot"] });
      toast.success("Autopilot resumed");
    },
    onError: () => toast.error("Could not resume autopilot"),
  });

  // Derive total from status.total_actions_today (primary) or summary fallback
  const totalActions = status.total_actions_today || summary.total_actions || 0;
  const animatedTotal = useCountUp(totalActions);

  // Build bullet list from categories with non-zero actions,
  // also using summary.by_category as a fallback.
  const bullets = buildBullets(status.categories, summary.by_category);

  const lastRunIso = mostRecentAction(status.categories);
  const lastRunLabel = timeAgo(lastRunIso);
  const isPaused = status.global_paused;

  const isActing = pauseMutation.isPending || resumeMutation.isPending;

  return (
    <div className="w-full rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-5 mb-6">
      {/* Header row */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Zap size={16} className="text-[#84cc16]" fill="#84cc16" />
          <span className="text-xs font-bold tracking-widest uppercase text-[#84cc16]">
            Autopilot
          </span>
        </div>
        <button
          onClick={() => {
            if (location.pathname === "/autopilot") {
              document.getElementById("autopilot-activity-log")?.scrollIntoView({ behavior: "smooth" });
            } else {
              navigate("/autopilot");
            }
          }}
          className="flex items-center gap-1 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
        >
          View Activity
          <ChevronRight size={13} />
        </button>
      </div>

      {/* Paused warning banner */}
      {isPaused && (
        <div className="flex items-center gap-3 mb-4 px-4 py-3 rounded-xl bg-amber-500/10 border border-amber-500/30">
          <AlertTriangle size={16} className="text-amber-400 shrink-0" />
          <span className="text-sm text-amber-300 font-medium flex-1">
            Autopilot is paused.
          </span>
          <button
            onClick={() => resumeMutation.mutate()}
            disabled={isActing}
            className="text-xs font-bold text-amber-300 hover:text-amber-100 border border-amber-500/40 rounded-lg px-3 py-1 transition-colors disabled:opacity-50"
          >
            Resume
          </button>
        </div>
      )}

      {/* Big number headline */}
      <div className="mb-4">
        <p className="text-[var(--text-primary)] text-lg font-semibold leading-snug">
          Today, BMG did{" "}
          <span
            className="text-[#84cc16] font-bold tabular-nums"
            style={{ fontSize: "1.75rem", lineHeight: 1 }}
          >
            {animatedTotal}
          </span>{" "}
          things for you
        </p>
      </div>

      {/* Bullet grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-1.5 mb-5">
        {bullets.length === 0 ? (
          <p className="col-span-3 text-xs text-[var(--text-tertiary)]">
            Ready · waiting for market open
          </p>
        ) : (
          bullets.map((b) => (
            <span key={b.key} className="text-xs text-[var(--text-secondary)] flex items-center gap-1.5">
              <span className="w-1 h-1 rounded-full bg-[#84cc16] shrink-0" />
              {b.label}
            </span>
          ))
        )}
      </div>

      {/* Footer row */}
      <div className="flex items-center justify-between">
        {!isPaused && (
          <button
            onClick={() => pauseMutation.mutate()}
            disabled={isActing}
            className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-emphasis)] transition-colors disabled:opacity-50"
          >
            Pause All
          </button>
        )}
        {isPaused && <span />}
        <span className="text-xs text-[var(--text-tertiary)]">
          Last run: {lastRunLabel}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bullet builder
// ---------------------------------------------------------------------------

interface Bullet {
  key: string;
  label: string;
}

function buildBullets(
  categories: AutopilotStatus["categories"],
  byCategory: Record<string, number>
): Bullet[] {
  // Merge categories array + by_category map; prefer the array for ordering
  const merged: Record<string, number> = { ...byCategory };
  for (const cat of categories) {
    if (cat.actions_today > 0) {
      merged[cat.name] = cat.actions_today;
    }
  }

  const entries = Object.entries(merged)
    .filter(([, count]) => count > 0)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 6); // cap at 6 bullets to keep card compact

  return entries.map(([name, count]) => ({
    key: name,
    label: formatCategoryBullet(name, count),
  }));
}

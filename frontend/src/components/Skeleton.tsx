import { cn } from "@/lib/utils";

interface SkeletonProps {
  className?: string;
  /** Optional inline width — accepts any CSS string ("100%", "120px"). */
  w?: string;
  /** Optional inline height — accepts any CSS string. */
  h?: string;
}

/** Animated gray-block placeholder. Match the eventual content shape so the
 *  layout doesn't jump when real data lands. */
export function Skeleton({ className, w, h }: SkeletonProps) {
  return (
    <div
      className={cn(
        "rounded-md bg-t-bg2/60 animate-pulse",
        className,
      )}
      style={{ width: w, height: h }}
      aria-hidden="true"
    />
  );
}

/** Convenience: a stat-card-shaped skeleton matching the top summary boxes
 *  used across Tuning, Discipline, Hypotheses, Brain pages. */
export function StatCardSkeleton() {
  return (
    <div className="bg-t-bg1 border border-t-dim rounded-xl px-4 py-3 space-y-2">
      <Skeleton h="10px" w="55%" />
      <Skeleton h="24px" w="40%" />
    </div>
  );
}

/** Convenience: a hypothesis/tuning card-shaped skeleton (title + 4-stat grid). */
export function RowCardSkeleton() {
  return (
    <div className="border border-t-dim bg-t-bg1 rounded-xl p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <Skeleton h="14px" w="40%" />
        <Skeleton h="18px" w="80px" className="rounded-full" />
      </div>
      <Skeleton h="11px" w="70%" />
      <div className="grid grid-cols-4 gap-2 pt-1">
        <Skeleton h="22px" />
        <Skeleton h="22px" />
        <Skeleton h="22px" />
        <Skeleton h="22px" />
      </div>
    </div>
  );
}

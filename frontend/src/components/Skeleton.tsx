import { cn } from "@/lib/utils";

interface SkeletonProps {
  className?: string;
  /** Optional inline width — accepts any CSS string ("100%", "120px"). */
  w?: string;
  /** Optional inline height — accepts any CSS string. */
  h?: string;
  /** Alias for `w` — matches the spec the rest of the loading UI uses. */
  width?: string;
  /** Alias for `h`. */
  height?: string;
  /** When true, render a sliding green shimmer overlay instead of the
   *  cheaper pulse animation. Use this on hero loading screens where the
   *  user is staring at the placeholder for more than a beat. */
  shimmer?: boolean;
}

/** Animated placeholder block. Match the eventual content shape so the
 *  layout doesn't jump when real data lands.
 *
 *  Two animation modes:
 *   • default → `animate-pulse` (cheap, in-and-out opacity)
 *   • shimmer → translucent green highlight sliding across the box
 *               (matches the terminal palette; uses the @keyframes shimmer
 *               defined in index.css). */
export function Skeleton({
  className,
  w,
  h,
  width,
  height,
  shimmer = false,
}: SkeletonProps) {
  return (
    <div
      className={cn(
        "rounded-md",
        shimmer
          ? // Shimmer mode — gradient sized 200% so the keyframe can slide.
            "bg-[linear-gradient(90deg,rgba(74,222,128,0.04)_0%,rgba(74,222,128,0.14)_50%,rgba(74,222,128,0.04)_100%)] bg-[length:200%_100%] [animation:shimmer_1.6s_ease-in-out_infinite]"
          : "bg-t-bg2/60 animate-pulse",
        className,
      )}
      style={{ width: width ?? w, height: height ?? h }}
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

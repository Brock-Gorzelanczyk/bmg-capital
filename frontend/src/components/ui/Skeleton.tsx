import { cn } from "@/lib/utils";

interface SkeletonProps {
  className?: string;
  rows?: number;
  height?: number | string;
}

export function Skeleton({ className, rows = 1, height = 20 }: SkeletonProps) {
  if (rows === 1) {
    return (
      <div
        className={cn("animate-pulse bg-[var(--bg-elevated-2)] rounded-lg", className)}
        style={{ height }}
      />
    );
  }
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className={cn("animate-pulse bg-[var(--bg-elevated-2)] rounded-lg", className)}
          style={{ height, width: i === rows - 1 ? "75%" : "100%" }}
        />
      ))}
    </div>
  );
}

export function SkeletonCard({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-3",
        className
      )}
    >
      <Skeleton height={20} className="w-24" />
      <Skeleton height={36} className="w-32" />
      <Skeleton height={16} className="w-20" />
    </div>
  );
}

import { cn } from "@/lib/utils";

interface StatCardProps {
  label: string;
  value: string | number;
  delta?: number | null;
  deltaLabel?: string;
  subtext?: string;
  mono?: boolean;
  className?: string;
  size?: "sm" | "md" | "lg";
  loading?: boolean;
}

export function StatCard({
  label,
  value,
  delta,
  deltaLabel,
  subtext,
  mono = true,
  className,
  size = "md",
  loading = false,
}: StatCardProps) {
  const isPos = delta != null && delta >= 0;
  const isNeg = delta != null && delta < 0;

  const valSize = {
    sm: "text-lg",
    md: "text-2xl",
    lg: "text-3xl",
  }[size];

  if (loading) {
    return (
      <div className={cn("bg-t-bg1 border border-t-dim rounded-sm p-4 animate-pulse", className)}>
        <div className="h-3 w-20 bg-t-bg2 rounded mb-3" />
        <div className="h-7 w-28 bg-t-bg2 rounded" />
      </div>
    );
  }

  return (
    <div className={cn("bg-t-bg1 border border-t-dim rounded-sm p-4 card-hover", className)}>
      {/* Label */}
      <p className="panel-header mb-2">{label}</p>

      {/* Value */}
      <p
        className={cn(
          "font-mono-t tabular-nums font-semibold leading-none text-t-hi",
          valSize,
        )}
      >
        {value}
      </p>

      {/* Delta */}
      {delta != null && (
        <p
          className={cn(
            "mt-1.5 text-xs font-mono-t tabular-nums font-medium",
            isPos && "text-t-green",
            isNeg && "text-t-red",
            !isPos && !isNeg && "text-t-mid2",
          )}
        >
          {isPos ? "+" : ""}
          {delta.toFixed(2)}%{deltaLabel ? ` ${deltaLabel}` : ""}
        </p>
      )}

      {/* Subtext */}
      {subtext && (
        <p className="mt-1 text-[10px] text-t-muted font-ui-t">{subtext}</p>
      )}
    </div>
  );
}

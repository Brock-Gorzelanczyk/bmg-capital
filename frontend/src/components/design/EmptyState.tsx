import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  cta?: React.ReactNode;
  className?: string;
  size?: "sm" | "md" | "lg";
}

export function EmptyState({
  icon,
  title,
  description,
  cta,
  className,
  size = "md",
}: EmptyStateProps) {
  const pad = { sm: "py-8", md: "py-12", lg: "py-16" }[size];

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        "bg-t-bg1 border border-t-dim rounded-sm",
        pad,
        "px-6",
        className,
      )}
    >
      {icon && (
        <p className="text-3xl mb-3 opacity-40 select-none">{icon}</p>
      )}
      <p className="panel-header mb-2">{title}</p>
      {description && (
        <p className="text-xs text-t-mid2 font-ui-t max-w-xs leading-relaxed">
          {description}
        </p>
      )}
      {cta && <div className="mt-4">{cta}</div>}
    </div>
  );
}

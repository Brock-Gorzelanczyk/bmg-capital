import { cn } from "@/lib/utils";

interface PanelHeaderProps {
  title: string;
  action?: React.ReactNode;
  as?: "h1" | "h2" | "h3" | "h4" | "p" | "div";
  className?: string;
  noSlash?: boolean;
}

export function PanelHeader({
  title,
  action,
  as: Tag = "div",
  className,
  noSlash = false,
}: PanelHeaderProps) {
  return (
    <div className={cn("flex items-center justify-between gap-2 mb-3", className)}>
      <Tag className="panel-header">
        {noSlash ? title : `// ${title}`}
      </Tag>
      {action && <div>{action}</div>}
    </div>
  );
}

import { HelpCircle } from "lucide-react";
import { useExplainStore } from "@/store/explainStore";
import { cn } from "@/lib/utils";
import { FEATURES } from "@/config/features";

interface Props {
  term: string;
  context?: string;
  className?: string;
  size?: number;
}

export default function ExplainButton({ term, context, className, size = 13 }: Props) {
  if (!FEATURES.EXPLAIN_THIS) return null;

  const explain = useExplainStore((s) => s.explain);

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        explain(term, context);
      }}
      title={`Explain: ${term}`}
      className={cn(
        "inline-flex items-center justify-center rounded-full text-zinc-600 hover:text-zinc-300 transition-colors",
        className
      )}
    >
      <HelpCircle size={size} />
    </button>
  );
}

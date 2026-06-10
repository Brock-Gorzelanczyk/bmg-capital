import { useState } from "react";
import { cn } from "@/lib/utils";
import { FEATURES } from "@/config/features";
import type { SignalSource } from "@/api/explain";
import SignalExplainModal from "./SignalExplainModal";

interface Props {
  signalId: number;
  source: SignalSource;
  className?: string;
}

export default function SignalExplainButton({ signalId, source, className }: Props) {
  const [open, setOpen] = useState(false);

  if (!FEATURES.TRADE_EXPLAIN) return null;

  return (
    <>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        title="AI trade explanation"
        className={cn(
          "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold",
          "bg-violet-500/10 border border-violet-500/20 text-violet-400",
          "hover:bg-violet-500/20 transition-colors flex-shrink-0",
          className
        )}
      >
        ⚒ AI
      </button>
      {open && (
        <SignalExplainModal
          signalId={signalId}
          source={source}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

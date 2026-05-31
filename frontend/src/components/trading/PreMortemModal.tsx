import { useState, useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { X, Brain, HelpCircle, AlertTriangle } from "lucide-react";
import { createPreMortem } from "@/api/journal";
import { cn } from "@/lib/utils";

interface PreMortemModalProps {
  symbol: string;
  direction: "long" | "short";
  positionSize?: number;
  entryPrice?: number;
  accountValue: number;
  /** Called when user saves a pre-mortem — passes the new entry id */
  onSave: (preMortemId: number) => void;
  /** Called when user skips (only allowed for <5% trades) */
  onSkip: () => void;
  onClose: () => void;
}

const MIN_CHARS = 50;

export default function PreMortemModal({
  symbol,
  direction,
  positionSize,
  entryPrice,
  accountValue,
  onSave,
  onSkip,
  onClose,
}: PreMortemModalProps) {
  const [thesis, setThesis] = useState("");
  const [showTooltip, setShowTooltip] = useState(false);
  const [showSkipWarning, setShowSkipWarning] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Determine if trade is >5% of account value
  const tradeValue = positionSize && entryPrice ? positionSize * entryPrice : positionSize ?? 0;
  const tradePct = accountValue > 0 ? (tradeValue / accountValue) * 100 : 0;
  const isLargeTrade = tradePct > 5;

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const mutation = useMutation({
    mutationFn: () =>
      createPreMortem({
        symbol,
        direction,
        thesis,
        position_size: positionSize ?? null,
        entry_price: entryPrice ?? null,
      }),
    onSuccess: (entry) => {
      onSave(entry.id);
    },
  });

  const charCount = thesis.length;
  const canSubmit = charCount >= MIN_CHARS && !mutation.isPending;

  function handleSkipClick() {
    if (isLargeTrade) {
      setShowSkipWarning(true);
      return;
    }
    onSkip();
  }

  return (
    <>
      {/* Dark overlay */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
        onClick={onClose}
      />

      {/* Modal card */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div
          className="pointer-events-auto w-full max-w-md bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-2xl shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-start justify-between px-5 pt-5 pb-4 border-b border-[var(--border-subtle)]">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-[#8B5CF6]/20 border border-[#8B5CF6]/30 flex items-center justify-center shrink-0">
                <Brain size={16} className="text-[#8B5CF6]" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-[var(--text-primary)]">
                  Pre-Trade Pre-Mortem
                </h2>
                <p className="text-xs text-[var(--text-tertiary)] mt-0.5">
                  {symbol} &middot; {direction === "long" ? "Long" : "Short"}
                  {tradePct > 0 && (
                    <span className={cn(
                      "ml-1.5 px-1.5 py-0.5 rounded text-[10px] font-semibold",
                      isLargeTrade
                        ? "bg-amber-500/20 text-amber-400"
                        : "bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)]"
                    )}>
                      {tradePct.toFixed(1)}% of account
                    </span>
                  )}
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
            >
              <X size={16} />
            </button>
          </div>

          {/* Body */}
          <div className="px-5 py-4 space-y-4">
            <div>
              <div className="flex items-center gap-1.5 mb-2">
                <p className="text-sm text-[var(--text-secondary)]">
                  Imagine this{" "}
                  <span className="font-mono font-bold text-[var(--text-primary)]">{symbol}</span>{" "}
                  trade fails in 30 days. What went wrong?
                </p>
                {/* Tooltip trigger */}
                <div className="relative inline-block">
                  <button
                    onMouseEnter={() => setShowTooltip(true)}
                    onMouseLeave={() => setShowTooltip(false)}
                    onFocus={() => setShowTooltip(true)}
                    onBlur={() => setShowTooltip(false)}
                    className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors shrink-0"
                  >
                    <HelpCircle size={14} />
                  </button>
                  {showTooltip && (
                    <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-64 bg-[#1E293B] border border-[var(--border-emphasis)] rounded-xl p-3 text-xs text-[var(--text-secondary)] shadow-xl z-10 leading-relaxed">
                      <p className="font-semibold text-[var(--text-primary)] mb-1">What is a pre-mortem?</p>
                      A pre-mortem forces you to think about failure modes before you&apos;re emotionally committed. Research shows traders who practice this have better loss management.
                    </div>
                  )}
                </div>
              </div>

              <textarea
                ref={textareaRef}
                rows={4}
                value={thesis}
                onChange={(e) => setThesis(e.target.value)}
                placeholder="e.g. The earnings miss was worse than expected, the sector sold off broadly, I sized too large and panic-sold at the worst time..."
                className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-sm rounded-xl px-3 py-2.5 placeholder-[#475569] outline-none focus:border-[#8B5CF6]/60 transition-colors resize-none leading-relaxed"
              />

              {/* Character counter */}
              <div className="flex items-center justify-between mt-1.5">
                <p className={cn(
                  "text-[11px] transition-colors",
                  charCount < MIN_CHARS ? "text-[var(--text-tertiary)]" : "text-emerald-500"
                )}>
                  {charCount < MIN_CHARS
                    ? `${MIN_CHARS - charCount} more characters to unlock submit`
                    : "Minimum met — ready to submit"}
                </p>
                <span className={cn(
                  "text-[11px] font-mono tabular-nums",
                  charCount >= MIN_CHARS ? "text-emerald-500" : "text-[var(--text-tertiary)]"
                )}>
                  {charCount}
                </span>
              </div>
            </div>

            {/* Large trade warning */}
            {isLargeTrade && (
              <div className="flex items-start gap-2 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2.5">
                <AlertTriangle size={13} className="text-amber-400 shrink-0 mt-0.5" />
                <p className="text-xs text-amber-300 leading-relaxed">
                  This trade is &gt;5% of your account. Pre-mortem is required — skip is disabled for large positions.
                </p>
              </div>
            )}

            {/* Skip warning */}
            {showSkipWarning && (
              <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2.5">
                <AlertTriangle size={13} className="text-red-400 shrink-0 mt-0.5" />
                <p className="text-xs text-red-300 leading-relaxed">
                  You cannot skip the pre-mortem for trades &gt;5% of your account. Please write your failure scenario before placing this trade.
                </p>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-5 pb-5 flex gap-2">
            <button
              onClick={handleSkipClick}
              disabled={isLargeTrade}
              title={isLargeTrade ? "Skip disabled for trades >5% of account" : "Skip pre-mortem (optional for small trades)"}
              className={cn(
                "flex-1 py-2.5 rounded-xl text-sm font-medium transition-colors",
                isLargeTrade
                  ? "bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] opacity-40 cursor-not-allowed"
                  : "bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              )}
            >
              Skip{!isLargeTrade && " (optional for &lt;5% trades)"}
            </button>
            <button
              onClick={() => mutation.mutate()}
              disabled={!canSubmit}
              className={cn(
                "flex-1 py-2.5 rounded-xl text-sm font-bold transition-all",
                canSubmit
                  ? "bg-[#8B5CF6] hover:bg-violet-500 text-white"
                  : "bg-[#8B5CF6]/30 text-[#8B5CF6]/50 cursor-not-allowed"
              )}
            >
              {mutation.isPending ? "Saving…" : "Save & Place Trade"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

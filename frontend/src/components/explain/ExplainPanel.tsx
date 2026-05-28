import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, Sparkles, BookOpen, Copy, Check, ChevronRight } from "lucide-react";
import { useExplainStore } from "@/store/explainStore";
import { useUiStore } from "@/store/uiStore";
import { explainTerm } from "@/api/explain";
import { cn } from "@/lib/utils";
import { FEATURES } from "@/config/features";

export default function ExplainPanel() {
  if (!FEATURES.EXPLAIN_THIS) return null;

  const { open, request, close, explain } = useExplainStore();
  const appMode = useUiStore((s) => s.mode);
  const [mode, setMode] = useState<"simple" | "detailed">(
    appMode === "pro" ? "detailed" : "simple"
  );
  const [copied, setCopied] = useState(false);

  // Sync mode with app mode when panel opens
  useEffect(() => {
    if (open) setMode(appMode === "pro" ? "detailed" : "simple");
  }, [open, appMode]);

  const { data, isFetching } = useQuery({
    queryKey: ["explain", request?.term, mode],
    queryFn: () => explainTerm(request!.term, mode, request?.context),
    enabled: open && !!request?.term,
    staleTime: 10 * 60_000,
  });

  const handleCopy = () => {
    if (!data) return;
    navigator.clipboard.writeText(data.explanation);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Keyboard: Escape closes
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    if (open) window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open]);

  return (
    <>
      {/* Backdrop */}
      <div
        className={cn(
          "fixed inset-0 z-40 bg-[#020617]/40 backdrop-blur-[1px] transition-opacity duration-200",
          open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
        )}
        onClick={close}
      />

      {/* Panel */}
      <div
        className={cn(
          "fixed right-0 top-0 h-full w-full max-w-sm bg-[var(--bg-elevated)] border-l border-[var(--border-emphasis)] z-50",
          "flex flex-col shadow-2xl transition-transform duration-200",
          open ? "translate-x-0" : "translate-x-full"
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-subtle)] shrink-0">
          <div className="flex items-center gap-2">
            <Sparkles size={15} className="text-[var(--accent-positive)]" />
            <span className="text-sm font-semibold text-[var(--text-primary)]">Explain This</span>
          </div>
          <div className="flex items-center gap-2">
            {data && (
              <button onClick={handleCopy} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors">
                {copied ? <Check size={14} className="text-[var(--accent-positive)]" /> : <Copy size={14} />}
              </button>
            )}
            <button onClick={close} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors">
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Term + mode toggle */}
        {request && (
          <div className="px-5 pt-4 pb-3 border-b border-[var(--border-subtle)] shrink-0">
            <h2 className="text-lg font-bold text-[var(--text-primary)] capitalize mb-3">{request.term}</h2>
            <div className="flex items-center gap-1 p-0.5 bg-[var(--bg-elevated-2)] rounded-lg w-fit">
              {(["simple", "detailed"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={cn(
                    "px-3 py-1 rounded-md text-xs font-semibold transition-all capitalize",
                    mode === m
                      ? "bg-white text-black"
                      : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
                  )}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {isFetching && (
            <div className="space-y-2">
              {[...Array(4)].map((_, i) => (
                <div key={i} className={cn("h-4 bg-[var(--bg-elevated-2)] rounded animate-pulse", i === 3 && "w-2/3")} />
              ))}
            </div>
          )}

          {!isFetching && data && (
            <>
              <div className="text-[var(--text-secondary)] text-sm leading-relaxed whitespace-pre-line">
                {/* Render **bold** markdown */}
                {data.explanation.split(/(\*\*[^*]+\*\*)/).map((part, i) =>
                  part.startsWith("**") && part.endsWith("**")
                    ? <strong key={i} className="text-[var(--text-primary)] font-semibold">{part.slice(2, -2)}</strong>
                    : <span key={i}>{part}</span>
                )}
              </div>

              {data.source === "glossary" && (
                <div className="flex items-center gap-1.5 text-[10px] text-[var(--text-tertiary)]">
                  <BookOpen size={10} />
                  <span>From BMG Capital glossary</span>
                </div>
              )}
              {data.source === "ai" && (
                <div className="flex items-center gap-1.5 text-[10px] text-[var(--text-tertiary)]">
                  <Sparkles size={10} className="text-[var(--accent-positive)]" />
                  <span>AI-generated explanation</span>
                </div>
              )}

              {/* Related terms */}
              {data.related.length > 0 && (
                <div>
                  <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-2">Related</p>
                  <div className="flex flex-wrap gap-2">
                    {data.related.map((t) => (
                      <button
                        key={t}
                        onClick={() => explain(t)}
                        className="flex items-center gap-1 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] hover:border-[var(--border-emphasis)] px-2.5 py-1 rounded-lg transition-all capitalize"
                      >
                        {t} <ChevronRight size={10} />
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {!isFetching && !data && request && (
            <p className="text-[var(--text-tertiary)] text-sm">Loading explanation…</p>
          )}
        </div>
      </div>
    </>
  );
}

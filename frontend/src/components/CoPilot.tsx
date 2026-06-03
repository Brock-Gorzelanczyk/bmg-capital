import { useState, useEffect, useRef, useCallback } from "react";
import { X } from "lucide-react";
import client from "@/api/client";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface CoPilotProps {
  isOpen: boolean;
  onClose: () => void;
  currentBotName?: string; // passed from BotDetailPage if active
  prefillQuery?: string;   // pre-fill input when opened via "Ask Co-Pilot" buttons
}

interface QAResponse {
  answer: string;
  citations?: number;
  error?: string;
}

// ─── Suggestion chips ─────────────────────────────────────────────────────────

function getSuggestions(botName: string | undefined): string[] {
  if (!botName) {
    return [
      "Which bot is outperforming this month?",
      "What's the current VIX regime?",
      "Show me all open positions across bots",
      "Which bot has the highest win rate?",
    ];
  }
  const display = botName.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return [
    `Why did ${display} last open a position?`,
    `Show ${display}'s worst trade this month`,
    `How is ${display} doing vs backtest?`,
    `Pause ${display}`,
    `Switch to ${display}`,
  ];
}

// ─── Pulsing dots loader ───────────────────────────────────────────────────────

function PulsingDots() {
  return (
    <div className="flex items-center gap-1.5 py-3">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-2 h-2 rounded-full bg-teal-400 animate-pulse"
          style={{ animationDelay: `${i * 150}ms` }}
        />
      ))}
    </div>
  );
}

// ─── Simple markdown renderer (bold + line breaks only) ──────────────────────

function SimpleMarkdown({ text }: { text: string }) {
  // Support **bold**, *italic*, and newlines
  const lines = text.split("\n");
  return (
    <div className="space-y-1">
      {lines.map((line, li) => {
        if (!line.trim()) return <br key={li} />;
        // Replace **text** with <strong> and *text* with <em>
        const parts = line.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g);
        return (
          <p key={li} className="text-zinc-200 text-sm leading-relaxed">
            {parts.map((part, pi) => {
              if (part.startsWith("**") && part.endsWith("**")) {
                return <strong key={pi} className="text-white font-semibold">{part.slice(2, -2)}</strong>;
              }
              if (part.startsWith("*") && part.endsWith("*")) {
                return <em key={pi} className="text-zinc-300">{part.slice(1, -1)}</em>;
              }
              return part;
            })}
          </p>
        );
      })}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function CoPilot({ isOpen, onClose, currentBotName, prefillQuery }: CoPilotProps) {
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<QAResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Auto-focus when opened; apply prefill if provided
  useEffect(() => {
    if (isOpen) {
      const initial = prefillQuery ?? "";
      setQuery(initial);
      setResponse(null);
      setIsLoading(false);
      setTimeout(() => {
        inputRef.current?.focus();
        // If prefill, kick off the query immediately
        if (initial) {
          // executeQuery will be called by the debounce handler via handleChange re-run
        }
      }, 50);
    }
  }, [isOpen, prefillQuery]);

  // When isOpen becomes true and prefillQuery is set, run the query immediately
  useEffect(() => {
    if (isOpen && prefillQuery) {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => executeQuery(prefillQuery), 200);
    }
  }, [isOpen, prefillQuery, executeQuery]);

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;
    function handler(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isOpen, onClose]);

  // Debounced query execution
  const executeQuery = useCallback(
    async (q: string) => {
      if (!q.trim()) {
        setResponse(null);
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setResponse(null);

      try {
        // Determine target bot: use currentBotName if set, else try to infer from query
        const botTarget = currentBotName ?? "stock_swing";
        const res = await client.post<QAResponse>(`/bots/${botTarget}/qa`, { question: q });
        setResponse(res.data);
      } catch {
        setResponse({ answer: "", error: "Co-Pilot couldn't reach the bot's audit log" });
      } finally {
        setIsLoading(false);
      }
    },
    [currentBotName]
  );

  function handleChange(value: string) {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!value.trim()) {
      setResponse(null);
      setIsLoading(false);
      return;
    }
    debounceRef.current = setTimeout(() => executeQuery(value), 300);
  }

  function handleChipClick(suggestion: string) {
    setQuery(suggestion);
    executeQuery(suggestion);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && query.trim()) {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      executeQuery(query);
    }
  }

  const suggestions = getSuggestions(currentBotName);
  const showChips = !query && !isLoading && !response;
  const showNoContext = !currentBotName && !query;

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] p-4"
      onClick={onClose}
    >
      {/* Blur backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

      {/* Glass card */}
      <div
        className="relative bg-slate-900/95 backdrop-blur border border-slate-700 rounded-2xl w-full max-w-xl shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center gap-3 px-4 pt-4 pb-3 border-b border-slate-800">
          <span className="text-teal-400 text-base">⌘</span>
          <span className="text-zinc-400 text-xs font-semibold uppercase tracking-wide">Co-Pilot</span>
          {currentBotName && (
            <span className="ml-auto text-xs px-2 py-0.5 rounded-full bg-teal-500/15 border border-teal-500/30 text-teal-400 font-semibold">
              {currentBotName.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
            </span>
          )}
          <button
            onClick={onClose}
            className={cn(
              "text-zinc-600 hover:text-white transition-colors",
              currentBotName ? "ml-2" : "ml-auto"
            )}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Input */}
        <div className="px-4 py-3">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => handleChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              currentBotName
                ? `Ask about ${currentBotName.replace(/_/g, " ")}…`
                : "Ask about any bot, or pick a suggestion below…"
            }
            className={cn(
              "w-full bg-transparent text-white text-base placeholder-zinc-600",
              "outline-none border-none focus:ring-0"
            )}
          />
        </div>

        {/* Body */}
        <div className="px-4 pb-4 min-h-[80px]">
          {/* No-context prompt */}
          {showNoContext && (
            <p className="text-zinc-600 text-sm mb-3">
              No bot selected. Ask about a specific bot or the whole portfolio.
            </p>
          )}

          {/* Suggestion chips */}
          {showChips && (
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => handleChipClick(s)}
                  className={cn(
                    "text-xs font-medium px-3 py-1.5 rounded-full border transition-colors",
                    "bg-teal-500/10 border-teal-500/30 text-teal-300",
                    "hover:bg-teal-500/20 hover:border-teal-500/50"
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {/* Loading */}
          {isLoading && <PulsingDots />}

          {/* Response */}
          {!isLoading && response && (
            <div className="space-y-3">
              {response.error ? (
                <p className="text-red-400 text-sm">{response.error}</p>
              ) : (
                <>
                  <SimpleMarkdown text={response.answer || "No answer returned."} />
                  {typeof response.citations === "number" && (
                    <p className="text-zinc-600 text-xs">
                      Based on {response.citations} audit record{response.citations !== 1 ? "s" : ""}
                    </p>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-2 border-t border-slate-800 flex items-center justify-between">
          <span className="text-zinc-700 text-xs">Enter to search · Esc to close</span>
          <span className="text-zinc-700 text-xs">⌘K</span>
        </div>
      </div>
    </div>
  );
}

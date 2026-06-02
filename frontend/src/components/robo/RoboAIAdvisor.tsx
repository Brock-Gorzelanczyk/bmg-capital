import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Bot, Send } from "lucide-react";
import { cn } from "@/lib/utils";
import client from "@/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface RoboAIAdvisorProps {
  context?: "volatility" | "rebalance" | "goal" | "tax";
  portfolioData?: object;
  className?: string;
}

interface ExplainResponse {
  explanation: string;
}

interface FollowUp {
  question: string;
  answer: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function RoboAIAdvisor({
  context = "volatility",
  portfolioData = {},
  className,
}: RoboAIAdvisorProps) {
  const [followUps, setFollowUps] = useState<FollowUp[]>([]);
  const [input, setInput] = useState("");

  // ── Initial explanation ──────────────────────────────────────────────────
  const { data, isLoading, isError } = useQuery<ExplainResponse>({
    queryKey: ["robo-ai-explain", context],
    queryFn: () =>
      client
        .post<ExplainResponse>("/api/robo/ai/explain", {
          context: context ?? "volatility",
          data: portfolioData ?? {},
        })
        .then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });

  // ── Follow-up mutation ───────────────────────────────────────────────────
  const followUpMutation = useMutation({
    mutationFn: (question: string) =>
      client
        .post<ExplainResponse>("/api/robo/ai/explain", {
          context: "followup",
          data: { question, previous: data?.explanation ?? "" },
        })
        .then((r) => r.data),
    onSuccess: (res, question) => {
      setFollowUps((prev) => [...prev, { question, answer: res.explanation }]);
      setInput("");
    },
  });

  const handleSend = () => {
    const q = input.trim();
    if (!q || followUps.length >= 3 || followUpMutation.isPending) return;
    followUpMutation.mutate(q);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handleSend();
  };

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div
      className={cn(
        "bg-gradient-to-br from-[#1E293B] to-[#0F172A]",
        "border border-[var(--border-subtle)] border-l-2 border-l-[#3B82F6]",
        "rounded-xl overflow-hidden",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-4 pt-4 pb-3 border-b border-[var(--border-subtle)]">
        <div className="w-7 h-7 rounded-lg bg-blue-500/15 border border-blue-500/20 flex items-center justify-center">
          <Bot size={15} className="text-blue-400" />
        </div>
        <span className="text-sm font-semibold text-[var(--text-primary)]">AI Advisor</span>
        {context && (
          <span className="ml-auto text-[10px] uppercase tracking-widest text-[var(--text-tertiary)] font-medium">
            {context}
          </span>
        )}
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-3">
        {/* Main explanation */}
        {isError ? (
          <p className="text-sm text-[var(--text-tertiary)] italic">
            AI advisor temporarily unavailable. Check back in a moment.
          </p>
        ) : isLoading ? (
          <div className="flex items-center gap-2 text-sm text-[var(--text-tertiary)]">
            <span className="animate-pulse tracking-widest">•••</span>
          </div>
        ) : (
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            {data?.explanation}
          </p>
        )}

        {/* Follow-ups (max 3) */}
        {followUps.map((fu, idx) => (
          <div key={idx} className="space-y-1.5 pt-2 border-t border-[var(--border-subtle)]">
            <p className="text-xs text-blue-400 font-medium">You: {fu.question}</p>
            <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{fu.answer}</p>
          </div>
        ))}

        {/* Pending follow-up loading */}
        {followUpMutation.isPending && (
          <div className="pt-2 border-t border-[var(--border-subtle)]">
            <span className="text-sm text-[var(--text-tertiary)] animate-pulse tracking-widest">
              •••
            </span>
          </div>
        )}
      </div>

      {/* Follow-up input */}
      {!isError && (
        <div className="px-4 pb-4 border-t border-[var(--border-subtle)] pt-3">
          <div className="flex items-center gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={followUps.length >= 3 || followUpMutation.isPending}
              placeholder={
                followUps.length >= 3
                  ? "Max follow-ups reached"
                  : "Ask a follow-up question..."
              }
              className="flex-1 bg-slate-800/50 border border-[var(--border-subtle)] rounded-lg px-3 py-1.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-blue-500/50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            />
            <button
              onClick={handleSend}
              disabled={
                !input.trim() ||
                followUps.length >= 3 ||
                followUpMutation.isPending ||
                isLoading
              }
              className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-500 hover:bg-blue-400 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors shrink-0"
            >
              Send <Send size={13} />
            </button>
          </div>
          {followUps.length >= 3 && (
            <p className="text-xs text-[var(--text-tertiary)] mt-1.5">
              Maximum 3 follow-ups shown.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

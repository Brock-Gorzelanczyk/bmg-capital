import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, GitBranch, HelpCircle, Lightbulb } from "lucide-react";
import { getDecisions } from "@/api/playbook";

export default function PlaybookDecisionsPage() {
  const navigate = useNavigate();

  const { data, isLoading } = useQuery({
    queryKey: ["playbook-decisions"],
    queryFn: getDecisions,
  });

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">

        {/* Header */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate("/settings/pitch/playbook")}
            className="p-2 rounded-lg border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[#4ade80]/40 transition-all"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="flex items-center gap-2">
            <GitBranch className="w-5 h-5 text-[#4ade80]" />
            <h1 className="text-xl font-bold">Decision Tree</h1>
          </div>
        </div>

        <p className="text-sm text-[var(--text-secondary)]">
          Pre-decided rules for the 8 scenarios most likely to derail the 90-day plan.
          Read before every investor meeting.
        </p>

        {/* Decision cards */}
        {isLoading ? (
          <div className="space-y-4">
            {[...Array(8)].map((_, i) => (
              <div
                key={i}
                className="h-28 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] animate-pulse"
              />
            ))}
          </div>
        ) : (
          <div className="space-y-4">
            {(data?.decisions ?? []).map((decision, i) => (
              <div
                key={i}
                className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6 space-y-3 hover:border-[#4ade80]/30 transition-colors"
              >
                <div className="flex items-start gap-3">
                  <HelpCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                  <p className="text-sm font-bold text-[var(--text-primary)] leading-snug">
                    {decision.question}
                  </p>
                </div>

                <div className="flex items-start gap-3 pl-0">
                  <Lightbulb className="w-4 h-4 text-[#4ade80] shrink-0 mt-0.5" />
                  <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
                    {decision.answer}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Print hint */}
        <div className="text-center text-xs text-[var(--text-secondary)] pt-2">
          <span>Ctrl+P / Cmd+P to print a clean copy before meetings.</span>
        </div>

      </div>
    </div>
  );
}

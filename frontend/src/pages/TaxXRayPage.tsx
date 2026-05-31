import { useCallback, useRef, useState } from "react";
import {
  FileText,
  Shield,
  AlertCircle,
  ChevronRight,
  RotateCcw,
  TrendingDown,
  TrendingUp,
  DollarSign,
  Percent,
} from "lucide-react";
import { analyzeTaxReturn, type TaxAnalysisResult, type TaxOpportunity } from "@/api/tax";
import RothLadder from "@/components/tax/RothLadder";

// ── Typewriter loading steps ───────────────────────────────────────────────────

const LOADING_STEPS = [
  "Reading your PDF...",
  "Extracting AGI...",
  "Identifying marginal bracket...",
  "Reading wages and dividends...",
  "Scanning for capital gains...",
  "Claude is analyzing opportunities...",
  "Building your tax action plan...",
];

function useLoadingSteps(active: boolean) {
  const [stepIdx, setStepIdx] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const start = useCallback(() => {
    setStepIdx(0);
    let idx = 0;
    intervalRef.current = setInterval(() => {
      idx = Math.min(idx + 1, LOADING_STEPS.length - 1);
      setStepIdx(idx);
    }, 900);
  }, []);

  const stop = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  return { step: LOADING_STEPS[stepIdx], start, stop };
}

// ── Priority badge ─────────────────────────────────────────────────────────────

function PriorityBadge({ priority }: { priority: TaxOpportunity["priority"] }) {
  const colors = {
    high: "bg-red-500/15 text-red-400 border-red-500/25",
    medium: "bg-amber-500/15 text-amber-400 border-amber-500/25",
    low: "bg-blue-500/15 text-blue-400 border-blue-500/25",
  };
  return (
    <span
      className={`text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full border ${colors[priority]}`}
    >
      {priority}
    </span>
  );
}

// ── Stat card ──────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  icon: Icon,
  accent,
}: {
  label: string;
  value: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  accent?: string;
}) {
  return (
    <div className="bg-[var(--bg-elevated)] rounded-xl border border-[var(--border-subtle)] p-4 flex flex-col gap-1">
      <div className="flex items-center gap-2 text-[var(--text-tertiary)]">
        <Icon size={14} className="shrink-0" />
        <span className="text-xs font-semibold uppercase tracking-wider">{label}</span>
      </div>
      <p className={`text-2xl font-bold mt-1 ${accent ?? "text-[var(--text-primary)]"}`}>{value}</p>
    </div>
  );
}

// ── Opportunity card ───────────────────────────────────────────────────────────

function OpportunityCard({ opp }: { opp: TaxOpportunity }) {
  const borderColors = {
    high: "border-l-red-400",
    medium: "border-l-amber-400",
    low: "border-l-blue-400",
  };
  const savings = opp.estimated_savings_dollars;
  return (
    <div
      className={`bg-[var(--bg-elevated)] rounded-xl border border-[var(--border-subtle)] border-l-2 ${borderColors[opp.priority]} p-4`}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <p className="text-sm font-semibold text-[var(--text-primary)] leading-snug">{opp.opportunity}</p>
        <PriorityBadge priority={opp.priority} />
      </div>
      <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-3">{opp.action}</p>
      {savings > 0 && (
        <div className="flex items-center gap-1.5 text-emerald-400">
          <TrendingDown size={13} className="shrink-0" />
          <span className="text-xs font-semibold">
            Est. savings: ${savings.toLocaleString()}
          </span>
        </div>
      )}
    </div>
  );
}

// ── Tabs ───────────────────────────────────────────────────────────────────────

type Tab = "analysis" | "roth";

// ── Main page ──────────────────────────────────────────────────────────────────

export default function TaxXRayPage() {
  const [isDragging, setIsDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TaxAnalysisResult | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("analysis");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { step: loadingStep, start: startSteps, stop: stopSteps } = useLoadingSteps(loading);

  const processFile = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        setError("Please upload a PDF file.");
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        setError("File is too large. Maximum size is 10 MB.");
        return;
      }
      setError(null);
      setLoading(true);
      startSteps();
      try {
        const data = await analyzeTaxReturn(file);
        setResult(data);
        setActiveTab("analysis");
      } catch (err: unknown) {
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          "Failed to analyze the PDF. Please try again.";
        setError(msg);
      } finally {
        setLoading(false);
        stopSteps();
      }
    },
    [startSteps, stopSteps]
  );

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) processFile(file);
    },
    [processFile]
  );

  const onFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) processFile(file);
      e.target.value = "";
    },
    [processFile]
  );

  const reset = () => {
    setResult(null);
    setError(null);
    setLoading(false);
    stopSteps();
  };

  const fmt = (n: number | null | undefined) =>
    n != null ? `$${n.toLocaleString()}` : "N/A";

  // ── Loading state ────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6 px-4">
        <div className="w-16 h-16 rounded-2xl bg-[var(--accent-positive)]/10 border border-[var(--accent-positive)]/25 flex items-center justify-center">
          <FileText size={28} className="text-[var(--accent-positive)] animate-pulse" />
        </div>
        <div className="text-center">
          <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-2">Analyzing your return…</h2>
          <p className="text-sm text-[var(--accent-positive)] font-medium animate-pulse min-h-[1.25rem]">
            {loadingStep}
          </p>
        </div>
        <div className="flex gap-1.5">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="w-2 h-2 rounded-full bg-[var(--accent-positive)]/60 animate-bounce"
              style={{ animationDelay: `${i * 0.15}s` }}
            />
          ))}
        </div>
      </div>
    );
  }

  // ── Results state ────────────────────────────────────────────────────────────
  if (result) {
    const sortedOpps = [...result.opportunities].sort((a, b) => {
      const order = { high: 0, medium: 1, low: 2 };
      return order[a.priority] - order[b.priority];
    });

    return (
      <div className="max-w-4xl mx-auto px-4 py-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">Tax X-Ray</h1>
            <p className="text-sm text-[var(--text-tertiary)] mt-0.5">
              1040 Analysis Results
            </p>
          </div>
          <button
            onClick={reset}
            className="flex items-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] bg-[var(--bg-elevated)] border border-[var(--border-subtle)] px-3 py-2 rounded-lg transition-colors cursor-pointer"
          >
            <RotateCcw size={14} />
            Analyze another return
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 bg-[var(--bg-elevated)] p-1 rounded-xl border border-[var(--border-subtle)] w-fit">
          {(["analysis", "roth"] as Tab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all cursor-pointer ${
                activeTab === tab
                  ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)] shadow-sm"
                  : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
              }`}
            >
              {tab === "analysis" ? "1040 Analysis" : "Roth Ladder"}
            </button>
          ))}
        </div>

        {activeTab === "analysis" && (
          <>
            {/* Stats Row */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard
                label="AGI"
                value={fmt(result.agi)}
                icon={DollarSign}
              />
              <StatCard
                label="Effective Rate"
                value={`${result.effective_rate_pct}%`}
                icon={Percent}
                accent="text-amber-400"
              />
              <StatCard
                label="Marginal Bracket"
                value={result.marginal_bracket}
                icon={TrendingUp}
                accent="text-[var(--accent-positive)]"
              />
              <StatCard
                label="Total Tax"
                value={fmt(result.total_tax)}
                icon={TrendingDown}
                accent="text-red-400"
              />
            </div>

            {/* Additional stats */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <div className="bg-[var(--bg-elevated)] rounded-xl border border-[var(--border-subtle)] p-3">
                <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">Filing Status</p>
                <p className="text-sm font-semibold text-[var(--text-primary)] mt-1 capitalize">
                  {result.filing_status.replace(/_/g, " ")}
                </p>
              </div>
              {result.w2_wages != null && (
                <div className="bg-[var(--bg-elevated)] rounded-xl border border-[var(--border-subtle)] p-3">
                  <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">W2 Wages</p>
                  <p className="text-sm font-semibold text-[var(--text-primary)] mt-1">{fmt(result.w2_wages)}</p>
                </div>
              )}
              {result.qualified_dividends != null && (
                <div className="bg-[var(--bg-elevated)] rounded-xl border border-[var(--border-subtle)] p-3">
                  <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">Qualified Dividends</p>
                  <p className="text-sm font-semibold text-[var(--text-primary)] mt-1">{fmt(result.qualified_dividends)}</p>
                </div>
              )}
              {result.capital_gains != null && (
                <div className="bg-[var(--bg-elevated)] rounded-xl border border-[var(--border-subtle)] p-3">
                  <p className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">Capital Gains/Loss</p>
                  <p className={`text-sm font-semibold mt-1 ${(result.capital_gains ?? 0) >= 0 ? "text-[var(--text-primary)]" : "text-red-400"}`}>
                    {fmt(result.capital_gains)}
                  </p>
                </div>
              )}
            </div>

            {/* Opportunities */}
            {sortedOpps.length > 0 && (
              <div>
                <h2 className="text-base font-semibold text-[var(--text-primary)] mb-3 flex items-center gap-2">
                  <ChevronRight size={16} className="text-[var(--accent-positive)]" />
                  Tax Action Plan
                </h2>
                <div className="space-y-3">
                  {sortedOpps.map((opp, i) => (
                    <OpportunityCard key={i} opp={opp} />
                  ))}
                </div>
              </div>
            )}

            {sortedOpps.length === 0 && (
              <div className="bg-[var(--bg-elevated)] rounded-xl border border-[var(--border-subtle)] p-6 text-center">
                <p className="text-[var(--text-tertiary)] text-sm">
                  No AI-powered opportunities available — ensure ANTHROPIC_API_KEY is configured.
                </p>
              </div>
            )}

            {/* Disclaimer */}
            <p className="text-xs text-[var(--text-tertiary)] border-t border-[var(--border-subtle)] pt-4">
              {result.disclaimer}
            </p>
          </>
        )}

        {activeTab === "roth" && <RothLadder />}
      </div>
    );
  }

  // ── Upload state (default) ────────────────────────────────────────────────────
  return (
    <div className="max-w-2xl mx-auto px-4 py-10 space-y-6">
      {/* Page header */}
      <div className="text-center">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-[var(--accent-positive)]/10 border border-[var(--accent-positive)]/20 mb-4">
          <FileText size={24} className="text-[var(--accent-positive)]" />
        </div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">Tax X-Ray</h1>
        <p className="text-[var(--text-tertiary)] text-sm mt-1.5 max-w-sm mx-auto">
          Upload your 1040 and get a personalized tax planning action plan powered by Claude.
        </p>
      </div>

      {/* Privacy notice */}
      <div className="flex items-start gap-3 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
        <Shield size={16} className="text-[var(--accent-positive)] shrink-0 mt-0.5" />
        <div>
          <p className="text-xs font-semibold text-[var(--text-primary)]">Your privacy is protected</p>
          <p className="text-xs text-[var(--text-tertiary)] mt-0.5">
            We extract numbers only. Your PDF is never saved to our servers — it is processed in memory and
            discarded immediately after analysis.
          </p>
        </div>
      </div>

      {/* Drop zone */}
      <div
        onDragEnter={() => setIsDragging(true)}
        onDragLeave={() => setIsDragging(false)}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`
          relative border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all duration-200
          ${isDragging
            ? "border-[var(--accent-positive)] bg-[var(--accent-positive)]/5"
            : "border-[var(--border-emphasis)] bg-[var(--bg-elevated)] hover:border-[var(--accent-positive)]/50 hover:bg-[var(--bg-elevated-2)]"
          }
        `}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          onChange={onFileChange}
        />
        <div className="flex flex-col items-center gap-3 pointer-events-none">
          <div className={`w-14 h-14 rounded-xl flex items-center justify-center transition-colors ${isDragging ? "bg-[var(--accent-positive)]/15" : "bg-[var(--bg-elevated-2)]"}`}>
            <FileText size={26} className={isDragging ? "text-[var(--accent-positive)]" : "text-[var(--text-tertiary)]"} />
          </div>
          <div>
            <p className="text-sm font-semibold text-[var(--text-primary)]">
              {isDragging ? "Drop your 1040 here" : "Drop your 1040 here or click to upload"}
            </p>
            <p className="text-xs text-[var(--text-tertiary)] mt-1">PDF only, max 10 MB</p>
          </div>
          <div className="text-xs text-[var(--text-tertiary)] bg-[var(--bg-base)] px-3 py-1.5 rounded-full border border-[var(--border-subtle)]">
            Your document is processed securely and never stored
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 bg-red-500/10 border border-red-500/25 rounded-xl p-4">
          <AlertCircle size={16} className="text-red-400 shrink-0 mt-0.5" />
          <p className="text-sm text-red-400">{error}</p>
        </div>
      )}

      {/* Roth Ladder standalone — shown below upload when no result */}
      <div className="pt-4 border-t border-[var(--border-subtle)]">
        <RothLadder />
      </div>
    </div>
  );
}

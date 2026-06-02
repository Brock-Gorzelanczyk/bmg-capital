import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/utils";
import {
  Briefcase,
  ShieldCheck,
  Zap,
  ChevronRight,
  AlertTriangle,
  Bot,
  X,
} from "lucide-react";
import {
  getRoboDashboard,
  getAiExplanation,
  getRebalanceHistory,
  simulateRebalance,
  type RoboDashboard as RoboDashboardData,
  type RebalanceSimulation,
} from "@/api/robo";

// ── Donut Chart ───────────────────────────────────────────────────────────────

function DonutChart({ allocation }: { allocation: Record<string, number> }) {
  const segments = [
    { key: "equity", color: "#3B82F6", label: "Equity" },
    { key: "bonds", color: "#22C55E", label: "Bonds" },
    { key: "cash", color: "#64748B", label: "Cash" },
  ];

  const total = Object.values(allocation).reduce((a, b) => a + b, 0) || 100;
  const cx = 50;
  const cy = 50;
  const r = 38;
  const gap = 2;

  let cumulativeDeg = -90;

  const arcs = segments.map(({ key, color, label }) => {
    const pct = (allocation[key] ?? 0) / total;
    const deg = pct * 360 - gap;
    const startDeg = cumulativeDeg + gap / 2;
    cumulativeDeg += pct * 360;

    const toRad = (d: number) => (d * Math.PI) / 180;
    const x1 = cx + r * Math.cos(toRad(startDeg));
    const y1 = cy + r * Math.sin(toRad(startDeg));
    const endDeg = startDeg + Math.max(deg, 0);
    const x2 = cx + r * Math.cos(toRad(endDeg));
    const y2 = cy + r * Math.sin(toRad(endDeg));
    const largeArc = deg > 180 ? 1 : 0;

    if (pct < 0.005) return null;

    return (
      <path
        key={key}
        d={`M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`}
        fill={color}
        opacity={0.85}
        aria-label={`${label}: ${Math.round(pct * 100)}%`}
      />
    );
  });

  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 100 100" className="w-20 h-20 shrink-0">
        <circle cx={cx} cy={cy} r={r} fill="var(--bg-base, #0f172a)" />
        {arcs}
        <circle cx={cx} cy={cy} r={24} fill="var(--bg-elevated, #1e293b)" />
      </svg>
      <div className="flex flex-col gap-1">
        {segments.map(({ key, color, label }) => {
          const pct = Math.round(((allocation[key] ?? 0) / total) * 100);
          return (
            <div key={key} className="flex items-center gap-1.5 text-xs">
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ background: color }}
              />
              <span className="text-[var(--text-tertiary)]">
                {label}: <span className="text-[var(--text-secondary)] font-medium">{pct}%</span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Goal Progress Bar ─────────────────────────────────────────────────────────

function GoalBar({
  name,
  value,
  target,
  probability_pct,
}: {
  name: string;
  value: number;
  target: number;
  probability_pct: number;
}) {
  const pct = Math.min((value / target) * 100, 100);
  const probColor =
    probability_pct >= 80
      ? "bg-green-500 text-green-100"
      : probability_pct >= 60
      ? "bg-amber-500 text-amber-100"
      : "bg-red-500 text-red-100";

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-[var(--text-secondary)]">{name}</span>
        <span
          className={cn(
            "text-[10px] font-semibold px-1.5 py-0.5 rounded-full",
            probColor
          )}
        >
          {probability_pct}%
        </span>
      </div>
      <div className="h-1.5 bg-[var(--border-subtle)] rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 rounded-full transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between text-[10px] text-[var(--text-tertiary)]">
        <span>{formatCurrency(value, 0)}</span>
        <span>{formatCurrency(target, 0)}</span>
      </div>
    </div>
  );
}

// ── Return Badge ──────────────────────────────────────────────────────────────

function ReturnBadge({ pct }: { pct: number }) {
  const positive = pct >= 0;
  return (
    <span
      className={cn(
        "text-xs font-semibold px-2 py-0.5 rounded-full",
        positive ? "text-green-400 bg-green-400/10" : "text-red-400 bg-red-400/10"
      )}
    >
      {positive ? "+" : ""}
      {pct.toFixed(1)}% YTD
    </span>
  );
}

// ── Rebalance Modal ───────────────────────────────────────────────────────────

function RebalanceModal({
  sim,
  onClose,
}: {
  sim: RebalanceSimulation;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl w-full max-w-md p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-[var(--text-primary)]">Rebalance Simulation</h3>
          <button
            onClick={onClose}
            className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <div className="text-xs text-[var(--text-secondary)] bg-blue-500/10 border border-blue-500/20 rounded-lg px-3 py-2">
          {sim.summary}
        </div>

        <div className="space-y-2">
          {sim.trades.map((t, i) => (
            <div
              key={i}
              className="flex items-center justify-between text-sm border-b border-[var(--border-subtle)] pb-2 last:border-0 last:pb-0"
            >
              <div>
                <span className="font-medium text-[var(--text-primary)]">{t.symbol}</span>
                <span
                  className={cn(
                    "ml-2 text-xs font-semibold",
                    t.action === "buy" ? "text-green-400" : "text-red-400"
                  )}
                >
                  {t.action.toUpperCase()}
                </span>
              </div>
              <div className="text-right text-[var(--text-secondary)]">
                <div>{t.qty_needed} shares</div>
                <div className="text-xs text-[var(--text-tertiary)]">
                  ~{formatCurrency(t.estimated_value, 0)}
                </div>
              </div>
            </div>
          ))}
        </div>

        {sim.taxes_triggered > 0 && (
          <div className="flex items-center gap-2 text-xs text-amber-400 bg-amber-400/10 border border-amber-400/20 rounded-lg px-3 py-2">
            <AlertTriangle size={13} />
            Estimated tax event: {formatCurrency(sim.taxes_triggered, 0)}
          </div>
        )}

        <button
          onClick={onClose}
          className="w-full py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors"
        >
          Close
        </button>
      </div>
    </div>
  );
}

// ── Get Started Hero ──────────────────────────────────────────────────────────

function GetStartedHero() {
  const navigate = useNavigate();
  return (
    <div className="flex flex-col items-center justify-center py-24 px-4 text-center space-y-6">
      <div className="w-16 h-16 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
        <Briefcase size={32} className="text-blue-400" />
      </div>
      <div className="space-y-2">
        <h2 className="text-2xl font-bold text-[var(--text-primary)]">
          Set up your Core portfolio
        </h2>
        <p className="text-[var(--text-tertiary)] max-w-sm">
          Answer 6 quick questions and we'll build a personalized, automatically rebalanced
          portfolio matched to your goals in under 2 minutes.
        </p>
      </div>
      <button
        onClick={() => navigate("/robo/quiz")}
        className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-semibold transition-colors"
      >
        Take Risk Quiz
        <ChevronRight size={18} />
      </button>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function RoboDashboard() {
  const navigate = useNavigate();
  const [simOpen, setSimOpen] = useState(false);
  const [simResult, setSimResult] = useState<RebalanceSimulation | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["robo-dashboard"],
    queryFn: getRoboDashboard,
    staleTime: 30_000,
    retry: 1,
  });

  const { data: historyData } = useQuery({
    queryKey: ["robo-rebalance-history"],
    queryFn: getRebalanceHistory,
    staleTime: 60_000,
    retry: 1,
  });

  const { data: aiData } = useQuery({
    queryKey: ["robo-ai-volatility"],
    queryFn: () => getAiExplanation("volatility", {}),
    staleTime: 300_000,
    retry: 1,
  });

  const simMutation = useMutation({
    mutationFn: () => simulateRebalance(),
    onSuccess: (result) => {
      setSimResult(result);
      setSimOpen(true);
    },
    onError: () => toast.error("Failed to simulate rebalance"),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-32 text-[var(--text-tertiary)]">
        <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!data?.risk_profile) {
    return <GetStartedHero />;
  }

  const { core, active, total_value, risk_profile } = data as RoboDashboardData;
  const recentLogs = ((historyData?.logs ?? []) as Record<string, string>[]).slice(0, 3);

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Briefcase size={22} className="text-blue-400" />
          <div>
            <h1 className="text-xl font-bold text-[var(--text-primary)]">BMG Core Portfolio</h1>
            <p className="text-sm text-[var(--text-tertiary)]">
              Total: {formatCurrency(total_value, 0)} &nbsp;·&nbsp; Core{" "}
              {Math.round(core.allocation_pct)}% · Active {Math.round(active.allocation_pct)}%
            </p>
          </div>
        </div>
        {!core.value && (
          <button
            onClick={() => navigate("/robo/quiz")}
            className="flex items-center gap-1 text-sm text-blue-400 hover:text-blue-300 font-medium transition-colors"
          >
            Set Up Core <ChevronRight size={14} />
          </button>
        )}
      </div>

      {/* Rebalance needed banner */}
      {core.rebalance_needed && (
        <div className="flex items-center justify-between bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3">
          <div className="flex items-center gap-2 text-amber-400 text-sm font-medium">
            <AlertTriangle size={16} />
            Drift detected — portfolio needs rebalancing
          </div>
          <button
            onClick={() => simMutation.mutate()}
            disabled={simMutation.isPending}
            className="text-xs font-semibold text-amber-300 hover:text-white bg-amber-500/20 hover:bg-amber-500/40 px-3 py-1.5 rounded-lg transition-colors"
          >
            {simMutation.isPending ? "Simulating…" : "Simulate Rebalance"}
          </button>
        </div>
      )}

      {/* Core + Active panels */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Core Panel */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">
              Core (Managed)
            </span>
            <ReturnBadge pct={core.ytd_return_pct} />
          </div>

          <p className="text-2xl font-bold text-[var(--text-primary)]">
            {formatCurrency(core.value, 0)}
          </p>

          {risk_profile?.target_allocation && (
            <DonutChart allocation={risk_profile.target_allocation} />
          )}

          <div className="space-y-3 pt-1">
            {core.goals.map((g, i) => (
              <GoalBar key={i} {...g} />
            ))}
          </div>

          {!core.direct_index_enabled && core.value < 25_000 && (
            <div className="text-xs text-[var(--text-tertiary)] border border-[var(--border-subtle)] rounded-lg px-3 py-2">
              Direct Indexing unlocks at{" "}
              <span className="text-[var(--text-secondary)] font-medium">$25,000</span>
            </div>
          )}
          {core.direct_index_enabled && (
            <div className="text-xs text-green-400 border border-green-500/20 rounded-lg px-3 py-2 bg-green-500/5">
              ✓ Direct Indexing enabled
            </div>
          )}
        </div>

        {/* Active Panel */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">
              Active (Self-Directed)
            </span>
            <ReturnBadge pct={active.ytd_return_pct} />
          </div>

          <p className="text-2xl font-bold text-[var(--text-primary)]">
            {formatCurrency(active.value, 0)}
          </p>

          <div className="space-y-2">
            {[
              { label: "Strategy Lab", value: active.paper_value, color: "text-blue-400" },
              { label: "Individual Holdings", value: active.holdings_value, color: "text-green-400" },
              { label: "Crypto", value: active.crypto_value, color: "text-amber-400" },
            ].map(({ label, value, color }) => (
              <div key={label} className="flex items-center justify-between text-sm">
                <span className="text-[var(--text-tertiary)]">{label}</span>
                <span className={cn("font-semibold tabular-nums", color)}>
                  {formatCurrency(value, 0)}
                </span>
              </div>
            ))}
          </div>

          <div className="border-t border-[var(--border-subtle)] pt-3">
            <button
              onClick={() => navigate("/strategy")}
              className="flex items-center gap-1.5 text-sm text-blue-400 hover:text-blue-300 font-medium transition-colors"
            >
              <Zap size={14} />
              Open Strategy Lab
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>

      {/* Risk Firewall */}
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-2">
        <div className="flex items-center gap-2 mb-3">
          <ShieldCheck size={16} className="text-green-400" />
          <span className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">
            Risk Firewall
          </span>
        </div>
        {[
          "Active losses don't affect Core goals.",
          "Core never borrows from Active.",
        ].map((line) => (
          <div key={line} className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
            <span className="text-green-400 font-bold">✓</span>
            {line}
          </div>
        ))}
      </div>

      {/* Recent Actions */}
      {recentLogs.length > 0 && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 space-y-2">
          <span className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">
            Recent Actions
          </span>
          <div className="space-y-1.5 pt-1">
            {recentLogs.map((log, i) => (
              <div key={i} className="flex items-start gap-2 text-sm text-[var(--text-secondary)]">
                <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" />
                {log.summary ?? log.action ?? JSON.stringify(log)}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* AI Advisor */}
      {aiData?.explanation && (
        <div className="rounded-xl p-4 space-y-2 bg-gradient-to-br from-blue-600/20 via-blue-500/10 to-transparent border border-blue-500/20">
          <div className="flex items-center gap-2">
            <Bot size={16} className="text-blue-400" />
            <span className="text-xs font-semibold text-blue-400 uppercase tracking-wider">
              AI Advisor
            </span>
          </div>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            "{aiData.explanation}"
          </p>
        </div>
      )}

      {/* Simulate Rebalance Button (secondary) */}
      <div className="flex justify-center">
        <button
          onClick={() => simMutation.mutate()}
          disabled={simMutation.isPending}
          className="flex items-center gap-2 px-5 py-2.5 border border-[var(--border-subtle)] hover:border-blue-500/50 text-[var(--text-secondary)] hover:text-blue-400 text-sm font-medium rounded-xl transition-colors"
        >
          {simMutation.isPending ? (
            <span className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
          ) : (
            <Zap size={15} />
          )}
          Simulate Rebalance
        </button>
      </div>

      {/* Rebalance Modal */}
      {simOpen && simResult && (
        <RebalanceModal sim={simResult} onClose={() => setSimOpen(false)} />
      )}
    </div>
  );
}

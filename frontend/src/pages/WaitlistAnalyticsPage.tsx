import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Users, TrendingUp, Zap, BarChart2 } from "lucide-react";
import { toast } from "sonner";
import {
  getWaitlistStats,
  getWaitlistGrowth,
  getWaitlistLeaderboard,
  addWaitlistSignup,
  type WaitlistStats,
  type WaitlistGrowthPoint,
  type WaitlistLeaderEntry,
} from "@/api/founder";

// ── Bar chart (SVG, no recharts) ───────────────────────────────────────────────

interface GrowthChartProps {
  data: WaitlistGrowthPoint[];
}

function GrowthChart({ data }: GrowthChartProps) {
  const [tooltip, setTooltip] = useState<{ x: number; y: number; label: string; count: number } | null>(null);

  if (!data.length) {
    return (
      <div className="h-48 flex items-center justify-center text-[var(--text-secondary)] text-sm">
        No growth data
      </div>
    );
  }

  const W = 600;
  const H = 160;
  const PAD_L = 40;
  const PAD_B = 24;
  const PAD_T = 8;
  const chartW = W - PAD_L - 8;
  const chartH = H - PAD_B - PAD_T;

  const maxVal = Math.max(...data.map((d) => d.count), 1);
  const barW = Math.max(2, Math.floor(chartW / data.length) - 2);

  // Y-axis labels
  const ySteps = 4;
  const yLabels = Array.from({ length: ySteps + 1 }, (_, i) =>
    Math.round((maxVal / ySteps) * i)
  );

  return (
    <div className="relative w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        className="w-full"
        style={{ minWidth: 300, height: H }}
        onMouseLeave={() => setTooltip(null)}
      >
        {/* Y-axis gridlines + labels */}
        {yLabels.map((val, i) => {
          const y = PAD_T + chartH - (val / maxVal) * chartH;
          return (
            <g key={i}>
              <line
                x1={PAD_L}
                x2={W - 8}
                y1={y}
                y2={y}
                stroke="rgba(255,255,255,0.06)"
                strokeWidth={1}
              />
              <text
                x={PAD_L - 4}
                y={y + 4}
                textAnchor="end"
                fontSize={9}
                fill="rgba(255,255,255,0.35)"
              >
                {val}
              </text>
            </g>
          );
        })}

        {/* Bars */}
        {data.map((d, i) => {
          const barH = Math.max(1, (d.count / maxVal) * chartH);
          const x = PAD_L + (i * chartW) / data.length + (chartW / data.length - barW) / 2;
          const y = PAD_T + chartH - barH;
          const label = d.date.slice(5); // "MM-DD"

          return (
            <g key={i}>
              <rect
                x={x}
                y={y}
                width={barW}
                height={barH}
                fill="#4ade80"
                fillOpacity={0.85}
                rx={1}
                style={{ cursor: "pointer" }}
                onMouseEnter={(e) => {
                  const svgEl = (e.target as SVGRectElement).closest("svg")!;
                  const rect = svgEl.getBoundingClientRect();
                  setTooltip({
                    x: rect.left + x + barW / 2,
                    y: rect.top + y - 8,
                    label,
                    count: d.count,
                  });
                }}
              />
              {/* X-axis date (every 7) */}
              {i % 7 === 0 && (
                <text
                  x={x + barW / 2}
                  y={H - 4}
                  textAnchor="middle"
                  fontSize={8}
                  fill="rgba(255,255,255,0.35)"
                >
                  {label}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="fixed z-50 bg-zinc-900 border border-[var(--border-subtle)] rounded px-2.5 py-1.5 text-xs pointer-events-none shadow-xl"
          style={{ left: tooltip.x, top: tooltip.y, transform: "translate(-50%, -100%)" }}
        >
          <div className="text-[var(--text-secondary)]">{tooltip.label}</div>
          <div className="font-bold text-[#4ade80]">{tooltip.count} signups</div>
        </div>
      )}
    </div>
  );
}

// ── Hero stat card ─────────────────────────────────────────────────────────────

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  sub?: string;
}

function StatCard({ icon, label, value, sub }: StatCardProps) {
  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-5 space-y-2">
      <div className="flex items-center gap-2 text-[var(--text-secondary)]">
        {icon}
        <span className="text-xs font-bold uppercase tracking-widest">{label}</span>
      </div>
      <div className="text-3xl font-black font-mono" style={{ color: "#4ade80" }}>
        {value}
      </div>
      {sub && <div className="text-xs text-[var(--text-secondary)]">{sub}</div>}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function WaitlistAnalyticsPage() {
  const qc = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [source, setSource] = useState("manual");

  const { data: stats, isLoading: statsLoading } = useQuery<WaitlistStats>({
    queryKey: ["waitlist-stats"],
    queryFn: getWaitlistStats,
    staleTime: 60_000,
  });

  const { data: growth = [] } = useQuery<WaitlistGrowthPoint[]>({
    queryKey: ["waitlist-growth"],
    queryFn: getWaitlistGrowth,
    staleTime: 60_000,
  });

  const { data: leaderboard = [] } = useQuery<WaitlistLeaderEntry[]>({
    queryKey: ["waitlist-leaderboard"],
    queryFn: getWaitlistLeaderboard,
    staleTime: 60_000,
  });

  const addMutation = useMutation({
    mutationFn: () => addWaitlistSignup(email, source),
    onSuccess: () => {
      toast.success("Signup added!");
      setEmail("");
      setSource("manual");
      setFormOpen(false);
      qc.invalidateQueries({ queryKey: ["waitlist-stats"] });
      qc.invalidateQueries({ queryKey: ["waitlist-growth"] });
    },
    onError: () => toast.error("Failed to add signup"),
  });

  const total = stats?.total ?? 0;
  const today = stats?.today ?? 0;
  const viralK = stats?.viral_k ?? 0;
  const activationRate = stats?.activation_rate ?? 0;
  const topSources = stats?.top_sources ?? [];
  const totalSources = topSources.reduce((s, r) => s + r.count, 0);

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">

        {/* Header */}
        <div>
          <h1 className="text-2xl font-black text-[var(--text-primary)]">
            Waitlist Analytics
          </h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            Growth, virality, and referral tracking
          </p>
        </div>

        {/* Hero stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard
            icon={<Users className="w-4 h-4" />}
            label="Total Signups"
            value={statsLoading ? "…" : total.toLocaleString()}
          />
          <StatCard
            icon={<TrendingUp className="w-4 h-4" />}
            label="Today"
            value={
              <span className={today > 0 ? "text-green-400" : undefined}>
                +{statsLoading ? "…" : today}
              </span>
            }
          />
          <StatCard
            icon={<Zap className="w-4 h-4" />}
            label="Viral Coefficient k"
            value={statsLoading ? "…" : viralK.toFixed(2)}
            sub="avg referrals per signup"
          />
          <StatCard
            icon={<BarChart2 className="w-4 h-4" />}
            label="Activation Rate"
            value={`${statsLoading ? "…" : activationRate}%`}
          />
        </div>

        {/* Growth chart */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6 space-y-4">
          <h2 className="text-sm font-bold text-[var(--text-primary)] uppercase tracking-widest">
            30-Day Growth
          </h2>
          <GrowthChart data={growth.slice(-30)} />
        </div>

        {/* Two-col: Sources + Leaderboard */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

          {/* Top Sources */}
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6 space-y-4">
            <h2 className="text-sm font-bold text-[var(--text-primary)] uppercase tracking-widest">
              Top Sources
            </h2>
            {topSources.length === 0 ? (
              <p className="text-sm text-[var(--text-secondary)]">No source data.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[var(--text-secondary)] text-xs uppercase tracking-wide border-b border-[var(--border-subtle)]">
                    <th className="text-left pb-2">Source</th>
                    <th className="text-right pb-2">Count</th>
                    <th className="text-right pb-2">%</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {topSources.map((row) => (
                    <tr key={row.source} className="hover:bg-[var(--bg-base)] transition-colors">
                      <td className="py-2 text-[var(--text-primary)] capitalize">{row.source}</td>
                      <td className="py-2 text-right font-mono font-semibold text-[#4ade80]">
                        {row.count.toLocaleString()}
                      </td>
                      <td className="py-2 text-right font-mono text-[var(--text-secondary)]">
                        {totalSources > 0
                          ? ((row.count / totalSources) * 100).toFixed(1)
                          : "0"}
                        %
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Referral Leaderboard */}
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-6 space-y-4">
            <h2 className="text-sm font-bold text-[var(--text-primary)] uppercase tracking-widest">
              Referral Leaderboard
            </h2>
            {leaderboard.length === 0 ? (
              <p className="text-sm text-[var(--text-secondary)]">No referrals yet.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[var(--text-secondary)] text-xs uppercase tracking-wide border-b border-[var(--border-subtle)]">
                    <th className="text-left pb-2">#</th>
                    <th className="text-left pb-2">Email</th>
                    <th className="text-right pb-2">Refs</th>
                    <th className="text-right pb-2">Queue</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {leaderboard.slice(0, 10).map((row, i) => (
                    <tr key={row.email} className="hover:bg-[var(--bg-base)] transition-colors">
                      <td className="py-2 font-mono text-[var(--text-secondary)] text-xs">
                        {i + 1}
                      </td>
                      <td className="py-2 text-[var(--text-primary)] truncate max-w-[140px]">
                        {row.email}
                      </td>
                      <td className="py-2 text-right font-mono font-bold text-[#4ade80]">
                        {row.referral_count}
                      </td>
                      <td className="py-2 text-right font-mono text-[var(--text-secondary)] text-xs">
                        #{row.position_in_queue}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Manual signup form */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] overflow-hidden">
          <button
            onClick={() => setFormOpen((v) => !v)}
            className="w-full flex items-center justify-between px-6 py-4 hover:bg-[var(--bg-base)] transition-colors text-left"
          >
            <span className="text-sm font-semibold text-[var(--text-primary)]">
              Add Manual Signup
            </span>
            {formOpen ? (
              <ChevronUp className="w-4 h-4 text-[var(--text-secondary)]" />
            ) : (
              <ChevronDown className="w-4 h-4 text-[var(--text-secondary)]" />
            )}
          </button>

          {formOpen && (
            <div className="px-6 pb-6 space-y-4 border-t border-[var(--border-subtle)]">
              <div className="pt-4 grid grid-cols-1 sm:grid-cols-3 gap-3">
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="email@example.com"
                  className="sm:col-span-2 text-sm bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none focus:border-[#4ade80]/50"
                />
                <select
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                  className="text-sm bg-[var(--bg-base)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-[var(--text-primary)] focus:outline-none focus:border-[#4ade80]/50"
                >
                  <option value="manual">Manual</option>
                  <option value="twitter">Twitter</option>
                  <option value="linkedin">LinkedIn</option>
                  <option value="referral">Referral</option>
                  <option value="email">Email</option>
                  <option value="other">Other</option>
                </select>
              </div>
              <button
                onClick={() => addMutation.mutate()}
                disabled={!email || addMutation.isPending}
                className="px-5 py-2 rounded-lg bg-[#4ade80] text-black text-sm font-semibold hover:bg-[#a3e635] transition-colors disabled:opacity-50"
              >
                {addMutation.isPending ? "Adding…" : "Add Signup"}
              </button>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}

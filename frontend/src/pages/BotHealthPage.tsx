import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { RefreshCw, CheckCircle, AlertTriangle, XCircle, MinusCircle, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import client from "@/api/client";

// ── Types ──────────────────────────────────────────────────────────────────────

type PipelineHealth = "GREEN" | "YELLOW" | "RED" | "DISABLED";

interface BotHealthRow {
  bot:                   string;
  pipeline_health:       PipelineHealth;
  enabled:               boolean;
  paused_reason?:        string | null;
  disable_category?:     string | null;
  last_signal_at?:       string | null;
  minutes_since_last?:   number | null;
  signals_24h:           number;
  discord_posts_24h:     number;
  trades_24h:            number;
  open_positions:        number;
  expected_interval_min: number;
  alert_threshold_min:   number;
  status?:               string;
  reason?:               string;
}

interface BotHealthResponse {
  bots:        BotHealthRow[];
  summary:     { green: number; yellow: number; red: number; disabled: number };
  checked_at:  string;
}

// ── Display helpers ────────────────────────────────────────────────────────────

const BOT_LABELS: Record<string, string> = {
  stock_swing:                  "Stock Swing",
  stock_day:                    "Stock Day",
  stock_lt:                     "Stock LT",
  crypto_swing:                 "Crypto Swing",
  crypto_day:                   "Crypto Day",
  crypto_lt:                    "Crypto LT",
  crypto_onchain:               "Crypto Onchain",
  crypto_quant_aggressive:      "Quant Aggressive",
  crypto_quant_scalper:         "Quant Scalper",
  crypto_quant_mean_reversion:  "Quant Mean Rev",
  options_income:               "Options Income",
  options_directional:          "Options Directional",
  crypto_meanrev_2163:          "MeanRev 2163",
  tsmom_multi_asset:            "TSMOM Multi-Asset",
  quality_factor:               "Quality Factor",
  value_quality:                "Value Quality",
  earnings_nlp:                 "Earnings NLP",
};

const HEALTH_CONFIG: Record<PipelineHealth, {
  label: string; icon: React.ElementType;
  row: string; badge: string; dot: string;
}> = {
  GREEN:    { label: "GREEN",    icon: CheckCircle,  row: "hover:bg-emerald-950/20", badge: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30", dot: "bg-emerald-400" },
  YELLOW:   { label: "YELLOW",   icon: AlertTriangle, row: "hover:bg-amber-950/20",   badge: "bg-amber-500/15 text-amber-400 border-amber-500/30",    dot: "bg-amber-400" },
  RED:      { label: "RED",      icon: XCircle,      row: "bg-red-950/10 hover:bg-red-950/20", badge: "bg-red-500/15 text-red-400 border-red-500/30",  dot: "bg-red-500 animate-pulse" },
  DISABLED: { label: "DISABLED", icon: MinusCircle,  row: "opacity-50 hover:opacity-70",       badge: "bg-zinc-800 text-zinc-500 border-zinc-700",    dot: "bg-zinc-600" },
};

function fmtAge(minutes: number | null | undefined): string {
  if (minutes == null) return "never";
  if (minutes < 60)    return `${Math.round(minutes)}m ago`;
  if (minutes < 1440)  return `${(minutes / 60).toFixed(1)}h ago`;
  return `${(minutes / 1440).toFixed(1)}d ago`;
}

function fmtInterval(min: number): string {
  if (min < 60)    return `${min}m`;
  if (min < 1440)  return `${min / 60}h`;
  if (min < 10080) return `${(min / 1440).toFixed(0)}d`;
  return `${(min / 10080).toFixed(0)}w`;
}

// ── API ────────────────────────────────────────────────────────────────────────

const fetchBotHealth = (): Promise<BotHealthResponse> =>
  client.get("/admin/bot-health").then(r => r.data);

const runSyntheticCheck = (): Promise<{ ok: boolean; passed: number; total: number; results: unknown[] }> =>
  client.post("/admin/synthetic-check").then(r => r.data);

// ── Components ─────────────────────────────────────────────────────────────────

function SummaryCard({ count, label, color }: { count: number; label: string; color: string }) {
  return (
    <div className={cn("rounded-xl border p-4 flex flex-col items-center gap-1", color)}>
      <span className="text-2xl font-bold font-mono tabular-nums">{count}</span>
      <span className="text-xs font-semibold uppercase tracking-wider opacity-70">{label}</span>
    </div>
  );
}

function HealthBadge({ health }: { health: PipelineHealth }) {
  const cfg = HEALTH_CONFIG[health];
  const Icon = cfg.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border", cfg.badge)}>
      <Icon size={10} />
      {cfg.label}
    </span>
  );
}

// ── Page ────────────────────────────────────────────────────────────────────────

export default function BotHealthPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [syntheticResult, setSyntheticResult] = useState<string | null>(null);

  const { data, isLoading, isError, dataUpdatedAt } = useQuery({
    queryKey: ["admin", "bot-health"],
    queryFn:  fetchBotHealth,
    refetchInterval: 30_000,
    staleTime:       25_000,
  });

  const syntheticMut = useMutation({
    mutationFn: runSyntheticCheck,
    onSuccess: (res) => {
      setSyntheticResult(`${res.passed}/${res.total} passed`);
      qc.invalidateQueries({ queryKey: ["admin", "bot-health"] });
      setTimeout(() => setSyntheticResult(null), 8000);
    },
    onError: () => setSyntheticResult("check failed"),
  });

  const checkedAt = data?.checked_at
    ? new Date(data.checked_at).toLocaleTimeString()
    : null;

  const summary = data?.summary ?? { green: 0, yellow: 0, red: 0, disabled: 0 };

  // Sort: RED first, then YELLOW, then GREEN, then DISABLED
  const ORDER: Record<PipelineHealth, number> = { RED: 0, YELLOW: 1, GREEN: 2, DISABLED: 3 };
  const rows = [...(data?.bots ?? [])].sort(
    (a, b) => (ORDER[a.pipeline_health] ?? 4) - (ORDER[b.pipeline_health] ?? 4),
  );

  return (
    <div className="min-h-screen bg-[var(--bmg-bg)] text-[var(--bmg-text)] p-6">
      <div className="max-w-7xl mx-auto">

        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <p className="text-xs text-zinc-500 uppercase tracking-widest mb-0.5">BMG Capital · Admin</p>
            <h1 className="text-2xl font-bold tracking-tight">Bot Pipeline Health</h1>
            {checkedAt && (
              <p className="text-xs text-zinc-500 mt-0.5 flex items-center gap-1">
                <RefreshCw size={10} className="animate-spin-slow" />
                last checked {checkedAt} · refreshes every 30s
              </p>
            )}
          </div>
          <button
            onClick={() => syntheticMut.mutate()}
            disabled={syntheticMut.isPending}
            className="flex items-center gap-2 text-sm px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 transition-colors disabled:opacity-50"
          >
            <Zap size={14} className={syntheticMut.isPending ? "animate-pulse" : ""} />
            {syntheticMut.isPending ? "Running…" : "Synthetic Check"}
            {syntheticResult && (
              <span className={cn(
                "ml-1 text-xs font-bold",
                syntheticResult.includes("failed") ? "text-red-400" : "text-emerald-400"
              )}>
                {syntheticResult}
              </span>
            )}
          </button>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-4 gap-3 mb-6">
          <SummaryCard count={summary.green}    label="Green"    color="bg-emerald-950/20 border-emerald-500/20 text-emerald-400" />
          <SummaryCard count={summary.yellow}   label="Yellow"   color="bg-amber-950/20 border-amber-500/20 text-amber-400" />
          <SummaryCard count={summary.red}      label="Red"      color="bg-red-950/20 border-red-500/20 text-red-400" />
          <SummaryCard count={summary.disabled} label="Disabled" color="bg-zinc-900 border-zinc-700 text-zinc-500" />
        </div>

        {/* Health table */}
        <div className="rounded-xl border border-zinc-800 overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-zinc-800 bg-zinc-900/60">
                <th className="text-left px-4 py-2.5 font-semibold text-zinc-400 uppercase tracking-wider w-44">Bot</th>
                <th className="text-left px-3 py-2.5 font-semibold text-zinc-400 uppercase tracking-wider">Health</th>
                <th className="text-right px-3 py-2.5 font-semibold text-zinc-400 uppercase tracking-wider">Last Signal</th>
                <th className="text-right px-3 py-2.5 font-semibold text-zinc-400 uppercase tracking-wider">Signals 24h</th>
                <th className="text-right px-3 py-2.5 font-semibold text-zinc-400 uppercase tracking-wider">Discord 24h</th>
                <th className="text-right px-3 py-2.5 font-semibold text-zinc-400 uppercase tracking-wider">Trades 24h</th>
                <th className="text-right px-3 py-2.5 font-semibold text-zinc-400 uppercase tracking-wider">Open Pos</th>
                <th className="text-right px-4 py-2.5 font-semibold text-zinc-400 uppercase tracking-wider">Cadence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/60">
              {isLoading && (
                <tr><td colSpan={8} className="text-center py-12 text-zinc-500">Loading…</td></tr>
              )}
              {isError && (
                <tr><td colSpan={8} className="text-center py-12 text-red-400">Failed to load health data</td></tr>
              )}
              {rows.map((row) => {
                const cfg = HEALTH_CONFIG[row.pipeline_health] ?? HEALTH_CONFIG.DISABLED;
                const hasPostingGap = row.signals_24h > 0 && row.discord_posts_24h < row.signals_24h;
                return (
                  <tr
                    key={row.bot}
                    onClick={() => navigate(`/admin/bot-health/${row.bot}`)}
                    className={cn(
                      "cursor-pointer transition-colors",
                      cfg.row,
                    )}
                  >
                    {/* Bot name */}
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className={cn("w-2 h-2 rounded-full flex-shrink-0", cfg.dot)} />
                        <span className="font-mono font-semibold text-zinc-200">
                          {BOT_LABELS[row.bot] ?? row.bot}
                        </span>
                      </div>
                    </td>

                    {/* Health badge */}
                    <td className="px-3 py-2.5">
                      <HealthBadge health={row.pipeline_health} />
                      {row.pipeline_health === "DISABLED" && (
                        <span className="ml-1.5 text-[9px] text-zinc-500 font-mono">
                          {row.disable_category === "T0_INCUBATION" ? "incubation"
                            : row.disable_category === "ADMIN_LOCK"  ? "admin-lock"
                            : row.disable_category === "HEALTH_HALT" ? "health-halt"
                            : "not-enabled"}
                        </span>
                      )}
                    </td>

                    {/* Last signal */}
                    <td className="px-3 py-2.5 text-right font-mono text-zinc-300 tabular-nums">
                      {fmtAge(row.minutes_since_last)}
                    </td>

                    {/* Signals 24h */}
                    <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-300">
                      {row.signals_24h}
                    </td>

                    {/* Discord posts 24h */}
                    <td className={cn(
                      "px-3 py-2.5 text-right font-mono tabular-nums",
                      hasPostingGap ? "text-red-400 font-bold" : "text-zinc-300",
                    )}>
                      {row.discord_posts_24h}
                      {hasPostingGap && <span className="ml-1 text-[9px]">gap!</span>}
                    </td>

                    {/* Trades 24h */}
                    <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-300">
                      {row.trades_24h}
                    </td>

                    {/* Open positions */}
                    <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-300">
                      {row.open_positions}
                    </td>

                    {/* Expected cadence */}
                    <td className="px-4 py-2.5 text-right text-zinc-500 tabular-nums">
                      {fmtInterval(row.expected_interval_min)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <p className="text-[10px] text-zinc-600 mt-3">
          Click any row to open the bot detail page. GREEN = last signal ≤ 2× cadence and Discord posted.
          YELLOW = 2–4× or posting gap. RED = &gt;4× cadence or signals fired but Discord silent.
        </p>
      </div>
    </div>
  );
}

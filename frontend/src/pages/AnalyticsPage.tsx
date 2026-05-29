import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { BarChart2, TrendingUp, TrendingDown, Zap, Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import { getJournalAnalytics } from "@/api/journalAnalytics";

// ── Formatters ────────────────────────────────────────────────────────────────

function fmtDollar(n: number) {
  const abs = Math.abs(n);
  const formatted =
    abs >= 1_000_000
      ? `$${(abs / 1_000_000).toFixed(2)}M`
      : abs >= 1_000
      ? `$${(abs / 1_000).toFixed(1)}K`
      : `$${abs.toFixed(2)}`;
  return n < 0 ? `-${formatted}` : formatted;
}

function fmtDollarFull(n: number) {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(n: number) {
  return `${n.toFixed(1)}%`;
}

function fmtMonth(ym: string) {
  const [year, month] = ym.split("-");
  const d = new Date(parseInt(year), parseInt(month) - 1, 1);
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function moodEmoji(mood: number) {
  return ["", "😞", "😕", "😐", "😊", "🤩"][mood] ?? "—";
}

// ── Pill filter components ────────────────────────────────────────────────────

const DAY_OPTIONS = [
  { label: "30D", value: 30 },
  { label: "90D", value: 90 },
  { label: "180D", value: 180 },
  { label: "1Y", value: 365 },
  { label: "All", value: 9999 },
];

const ACCOUNT_OPTIONS = [
  { label: "All", value: "all" },
  { label: "Paper", value: "paper" },
  { label: "Live", value: "live" },
];

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn("animate-pulse rounded-xl bg-[var(--bg-elevated)]", className)} />
  );
}

function SkeletonDashboard() {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-24" />)}
      </div>
      <Skeleton className="h-64" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Skeleton className="h-64" />
        <Skeleton className="h-64" />
      </div>
    </div>
  );
}

// ── Custom chart tooltip ──────────────────────────────────────────────────────

function ChartTooltip({
  active,
  payload,
  label,
  valueFormatter = fmtDollarFull,
  labelKey = "date",
}: {
  active?: boolean;
  payload?: Array<{ value: number; name?: string }>;
  label?: string;
  valueFormatter?: (n: number) => string;
  labelKey?: string;
}) {
  if (!active || !payload?.length) return null;
  const val = payload[0].value;
  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-[var(--text-tertiary)] mb-0.5">{labelKey === "date" ? label : label}</p>
      <p className={cn("font-bold font-mono", val >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
        {valueFormatter(val)}
      </p>
    </div>
  );
}

// ── Headline card ─────────────────────────────────────────────────────────────

function HeadlineCard({
  label,
  value,
  sub,
  positive,
}: {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean;
}) {
  const colorClass =
    positive === undefined
      ? "text-[var(--text-primary)]"
      : positive
      ? "text-[var(--accent-positive)]"
      : "text-[var(--accent-negative)]";

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
      <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">{label}</p>
      <p className={cn("text-xl font-bold font-mono leading-tight", colorClass)}>{value}</p>
      {sub && <p className="text-[var(--text-tertiary)] text-xs mt-0.5">{sub}</p>}
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const [days, setDays] = useState(365);
  const [accountType, setAccountType] = useState("all");

  const { data, isLoading } = useQuery({
    queryKey: ["journal-analytics", days, accountType],
    queryFn: () => getJournalAnalytics(days, accountType),
    staleTime: 30_000,
  });

  return (
    <div className="space-y-5 pb-10">
      {/* Page header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)] flex items-center gap-2">
            <BarChart2 size={20} className="text-[var(--accent-positive)]" />
            Trade Analytics
          </h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Performance insights across all your trades</p>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Days filter */}
          <div className="flex items-center bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg p-0.5 gap-0.5">
            {DAY_OPTIONS.map(({ label, value }) => (
              <button
                key={value}
                onClick={() => setDays(value)}
                className={cn(
                  "px-3 py-1.5 text-xs font-semibold rounded-md transition-colors",
                  days === value
                    ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]"
                    : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
                )}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Account type filter */}
          <div className="flex items-center bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg p-0.5 gap-0.5">
            {ACCOUNT_OPTIONS.map(({ label, value }) => (
              <button
                key={value}
                onClick={() => setAccountType(value)}
                className={cn(
                  "px-3 py-1.5 text-xs font-semibold rounded-md transition-colors",
                  accountType === value
                    ? "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]"
                    : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Loading skeleton */}
      {isLoading && <SkeletonDashboard />}

      {/* No data empty state */}
      {!isLoading && data && data.headline.total_trades === 0 && (
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-16 text-center">
          <Activity size={40} className="text-[var(--border-emphasis)] mx-auto mb-4" />
          <p className="text-[var(--text-primary)] font-semibold text-lg">No trades yet</p>
          <p className="text-[var(--text-tertiary)] text-sm mt-1">Start trading to see your analytics</p>
        </div>
      )}

      {/* Dashboard content */}
      {!isLoading && data && data.headline.total_trades > 0 && (
        <div className="space-y-5">

          {/* ── Headline stats ──────────────────────────────────────────── */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <HeadlineCard
              label="Total P&L"
              value={fmtDollarFull(data.headline.total_pnl)}
              positive={data.headline.total_pnl >= 0}
            />
            <HeadlineCard
              label="Win Rate"
              value={fmtPct(data.headline.win_rate)}
              sub={`${data.headline.total_trades} trades`}
              positive={data.headline.win_rate >= 50}
            />
            <HeadlineCard
              label="Profit Factor"
              value={data.headline.profit_factor.toFixed(2)}
              positive={data.headline.profit_factor >= 1}
            />
            <HeadlineCard
              label="Avg R-Multiple"
              value={data.headline.avg_r_multiple.toFixed(2) + "R"}
              positive={data.headline.avg_r_multiple > 0}
            />
            <HeadlineCard
              label="Max Drawdown"
              value={fmtPct(data.headline.max_drawdown)}
              positive={false}
            />
            <HeadlineCard
              label="Best Trade"
              value={fmtDollar(data.headline.best_trade.pnl)}
              sub={data.headline.best_trade.symbol}
              positive
            />
          </div>

          {/* ── Equity Curve ────────────────────────────────────────────── */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5">
            <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-4">Equity Curve</h2>
            {data.equity_curve.length === 0 ? (
              <div className="h-48 flex items-center justify-center text-[var(--text-tertiary)] text-sm">
                No trades yet
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={data.equity_curve} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--accent-positive)" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="var(--accent-positive)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    interval="preserveStartEnd"
                    tickFormatter={(v: string) => {
                      const d = new Date(v);
                      return `${d.toLocaleString("default", { month: "short" })} '${String(d.getFullYear()).slice(2)}`;
                    }}
                  />
                  <YAxis
                    tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v: number) => fmtDollar(v)}
                    width={58}
                  />
                  <Tooltip content={<ChartTooltip />} />
                  <Area
                    type="monotone"
                    dataKey="cumulative_pnl"
                    stroke="var(--accent-positive)"
                    strokeWidth={2}
                    fill="url(#equityGrad)"
                    dot={false}
                    activeDot={{ r: 4, fill: "var(--accent-positive)" }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* ── By Setup + R Distribution ───────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

            {/* By Setup table */}
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5">
              <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Edge by Setup</h2>
              {data.by_setup.length === 0 ? (
                <p className="text-[var(--text-tertiary)] text-sm">No setup data</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-[var(--text-tertiary)] uppercase tracking-wider text-[10px]">
                        <th className="text-left pb-2 font-medium">Setup</th>
                        <th className="text-right pb-2 font-medium">Trades</th>
                        <th className="text-right pb-2 font-medium">Win %</th>
                        <th className="text-right pb-2 font-medium">Avg P&L</th>
                        <th className="text-right pb-2 font-medium">Total P&L</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border-subtle)]">
                      {data.by_setup.map((row) => (
                        <tr key={row.setup} className="hover:bg-[var(--bg-elevated-2)]/40 transition-colors">
                          <td className="py-2 text-[var(--text-secondary)] font-medium pr-3">
                            {row.setup === "(none)" ? (
                              <span className="text-[var(--text-tertiary)] italic">No tag</span>
                            ) : row.setup}
                          </td>
                          <td className="py-2 text-right text-[var(--text-tertiary)] font-mono">{row.trade_count}</td>
                          <td className="py-2 text-right font-mono">
                            <span className={row.win_rate >= 50 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"}>
                              {fmtPct(row.win_rate)}
                            </span>
                          </td>
                          <td className={cn("py-2 text-right font-mono", row.avg_pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                            {fmtDollarFull(row.avg_pnl)}
                          </td>
                          <td className={cn("py-2 text-right font-bold font-mono", row.total_pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                            {fmtDollarFull(row.total_pnl)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* R Distribution bar chart */}
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5">
              <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-4">R-Multiple Distribution</h2>
              {data.r_distribution.every((b) => b.count === 0) ? (
                <p className="text-[var(--text-tertiary)] text-sm">No R data</p>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={data.r_distribution} margin={{ top: 0, right: 4, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
                    <XAxis
                      dataKey="bucket"
                      tick={{ fill: "var(--text-tertiary)", fontSize: 9 }}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis
                      tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
                      tickLine={false}
                      axisLine={false}
                      allowDecimals={false}
                      width={28}
                    />
                    <Tooltip
                      content={({ active, payload, label }) => {
                        if (!active || !payload?.length) return null;
                        return (
                          <div className="bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-xs shadow-xl">
                            <p className="text-[var(--text-tertiary)] mb-0.5">{label}</p>
                            <p className="font-bold text-[var(--text-primary)] font-mono">{payload[0].value} trades</p>
                          </div>
                        );
                      }}
                    />
                    <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                      {data.r_distribution.map((entry, idx) => {
                        const isNeg = entry.bucket.startsWith("<") || entry.bucket.startsWith("-");
                        return (
                          <Cell
                            key={idx}
                            fill={isNeg ? "var(--accent-negative)" : "var(--accent-positive)"}
                            fillOpacity={0.8}
                          />
                        );
                      })}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* ── Monthly Performance ─────────────────────────────────────── */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5">
            <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-4">Monthly Performance</h2>
            {data.by_month.length === 0 ? (
              <p className="text-[var(--text-tertiary)] text-sm">No monthly data</p>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={data.by_month} margin={{ top: 0, right: 4, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
                  <XAxis
                    dataKey="month"
                    tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={fmtMonth}
                  />
                  <YAxis
                    tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v: number) => fmtDollar(v)}
                    width={58}
                  />
                  <Tooltip
                    content={({ active, payload, label }) => {
                      if (!active || !payload?.length) return null;
                      const val = payload[0].value as number;
                      return (
                        <div className="bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-lg px-3 py-2 text-xs shadow-xl">
                          <p className="text-[var(--text-tertiary)] mb-0.5">{fmtMonth(label as string)}</p>
                          <p className={cn("font-bold font-mono", val >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                            {fmtDollarFull(val)}
                          </p>
                        </div>
                      );
                    }}
                  />
                  <Bar dataKey="total_pnl" radius={[3, 3, 0, 0]}>
                    {data.by_month.map((entry, idx) => (
                      <Cell
                        key={idx}
                        fill={entry.total_pnl >= 0 ? "var(--accent-positive)" : "var(--accent-negative)"}
                        fillOpacity={0.8}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* ── By Symbol (top 10) + Streaks & Mood ────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

            {/* By Symbol table */}
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5">
              <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Top Symbols</h2>
              {data.by_symbol.length === 0 ? (
                <p className="text-[var(--text-tertiary)] text-sm">No symbol data</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-[var(--text-tertiary)] uppercase tracking-wider text-[10px]">
                        <th className="text-left pb-2 font-medium">Symbol</th>
                        <th className="text-right pb-2 font-medium">Trades</th>
                        <th className="text-right pb-2 font-medium">Win %</th>
                        <th className="text-right pb-2 font-medium">Total P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.by_symbol.slice(0, 10).map((row, idx) => (
                        <tr
                          key={row.symbol}
                          className={cn(
                            "transition-colors",
                            idx % 2 === 0 ? "bg-transparent" : "bg-[var(--bg-elevated-2)]/30"
                          )}
                        >
                          <td className="py-2 text-[var(--text-primary)] font-bold font-mono pr-3">{row.symbol}</td>
                          <td className="py-2 text-right text-[var(--text-tertiary)] font-mono">{row.trade_count}</td>
                          <td className="py-2 text-right font-mono">
                            <span className={row.win_rate >= 50 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"}>
                              {fmtPct(row.win_rate)}
                            </span>
                          </td>
                          <td className={cn("py-2 text-right font-bold font-mono", row.total_pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                            {fmtDollarFull(row.total_pnl)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Streaks + Mood */}
            <div className="space-y-4">
              {/* Streaks */}
              <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5">
                <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3 flex items-center gap-2">
                  <Zap size={14} className="text-[#F59E0B]" />
                  Streaks
                </h2>
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: "Current Win", value: data.streaks.current_win_streak, positive: true },
                    { label: "Current Loss", value: data.streaks.current_loss_streak, positive: false },
                    { label: "Longest Win", value: data.streaks.longest_win_streak, positive: true },
                    { label: "Longest Loss", value: data.streaks.longest_loss_streak, positive: false },
                  ].map(({ label, value, positive }) => (
                    <div key={label} className="bg-[var(--bg-elevated-2)] rounded-xl p-3 text-center">
                      <p className={cn("text-2xl font-bold font-mono", positive ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                        {value}
                      </p>
                      <p className="text-[10px] text-[var(--text-tertiary)] mt-0.5">{label}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Mood breakdown */}
              <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5">
                <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Performance by Mood</h2>
                {data.by_mood.length === 0 ? (
                  <p className="text-[var(--text-tertiary)] text-sm">No mood data</p>
                ) : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-[var(--text-tertiary)] uppercase tracking-wider text-[10px]">
                        <th className="text-left pb-2 font-medium">Mood</th>
                        <th className="text-right pb-2 font-medium">Trades</th>
                        <th className="text-right pb-2 font-medium">Win %</th>
                        <th className="text-right pb-2 font-medium">Avg P&L</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border-subtle)]">
                      {[...data.by_mood].sort((a, b) => a.mood - b.mood).map((row) => (
                        <tr key={row.mood} className="hover:bg-[var(--bg-elevated-2)]/40">
                          <td className="py-2 text-lg">{moodEmoji(row.mood)}</td>
                          <td className="py-2 text-right text-[var(--text-tertiary)] font-mono">{row.count}</td>
                          <td className="py-2 text-right font-mono">
                            <span className={row.win_rate >= 50 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"}>
                              {fmtPct(row.win_rate)}
                            </span>
                          </td>
                          <td className={cn("py-2 text-right font-bold font-mono", row.avg_pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                            {fmtDollarFull(row.avg_pnl)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>

          {/* ── By Symbol Detail (top 20) ───────────────────────────────── */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-5">
            <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3 flex items-center gap-2">
              <TrendingUp size={14} className="text-[var(--accent-positive)]" />
              Symbol Breakdown (Top 20)
            </h2>
            {data.by_symbol.length === 0 ? (
              <p className="text-[var(--text-tertiary)] text-sm">No trades recorded</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[var(--text-tertiary)] uppercase tracking-wider text-[10px] border-b border-[var(--border-subtle)]">
                      <th className="text-left pb-2 font-medium">Symbol</th>
                      <th className="text-right pb-2 font-medium">Trades</th>
                      <th className="text-right pb-2 font-medium">Wins</th>
                      <th className="text-right pb-2 font-medium">Losses</th>
                      <th className="text-right pb-2 font-medium">Win Rate</th>
                      <th className="text-right pb-2 font-medium">Total P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_symbol.slice(0, 20).map((row, idx) => (
                      <tr
                        key={row.symbol}
                        className={cn(
                          "transition-colors hover:bg-[var(--bg-elevated-2)]/40",
                          idx % 2 === 0 ? "" : "bg-[var(--bg-elevated-2)]/20"
                        )}
                      >
                        <td className="py-2 text-[var(--text-primary)] font-bold font-mono pr-4">{row.symbol}</td>
                        <td className="py-2 text-right text-[var(--text-tertiary)] font-mono">{row.trade_count}</td>
                        <td className="py-2 text-right text-[var(--accent-positive)] font-mono">{row.wins}</td>
                        <td className="py-2 text-right text-[var(--accent-negative)] font-mono">{row.losses}</td>
                        <td className="py-2 text-right font-mono">
                          <span className={row.win_rate >= 50 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"}>
                            {fmtPct(row.win_rate)}
                          </span>
                        </td>
                        <td className={cn("py-2 text-right font-bold font-mono", row.total_pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                          {fmtDollarFull(row.total_pnl)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* ── Worst trade footnote ─────────────────────────────────────── */}
          <div className="flex items-center gap-4 text-xs text-[var(--text-tertiary)] px-1">
            <span className="flex items-center gap-1.5">
              <TrendingDown size={12} className="text-[var(--accent-negative)]" />
              Worst trade: <span className="font-mono text-[var(--accent-negative)] font-semibold">{data.headline.worst_trade.symbol}</span>
              {" "}{fmtDollarFull(data.headline.worst_trade.pnl)} on {data.headline.worst_trade.date}
            </span>
            <span className="ml-auto">
              Avg hold: <span className="font-mono text-[var(--text-secondary)]">{data.headline.avg_hold_days.toFixed(1)}d</span>
            </span>
          </div>

        </div>
      )}
    </div>
  );
}

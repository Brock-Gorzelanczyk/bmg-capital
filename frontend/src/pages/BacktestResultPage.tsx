import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Clock, AlertTriangle, TrendingUp, TrendingDown } from "lucide-react";
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { cn } from "@/lib/utils";
import { getBacktestResult } from "@/api/candidates";

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined, d = 2): string {
  return v == null ? "—" : v.toFixed(d);
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  try { return new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }); }
  catch { return s; }
}

function DeltaChip({ current, previous }: { current: number | null; previous: number | null }) {
  if (current == null || previous == null) return null;
  const delta = current - previous;
  const pos = delta >= 0;
  return (
    <span className={cn("inline-flex items-center gap-0.5 text-[10px] font-bold", pos ? "text-emerald-400" : "text-rose-400")}>
      {pos ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
      {pos ? "+" : ""}{delta.toFixed(2)} vs prev
    </span>
  );
}

// ── Equity curve parsing ───────────────────────────────────────────────────────

interface EquityPoint { date: string; value: number }
interface DrawdownPoint { date: string; dd: number }

function parseEquityCurve(json: string | null): EquityPoint[] | null {
  if (!json) return null;
  try {
    const parsed = JSON.parse(json);
    if (!Array.isArray(parsed) || parsed.length === 0) return null;

    // Format 1: [{date, equity|value|close|nav}, ...]
    if (typeof parsed[0] === "object" && parsed[0] !== null) {
      const first = parsed[0] as Record<string, unknown>;
      const dateKey = ["date", "t", "timestamp", "Date"].find(k => k in first) ?? null;
      const valKey  = ["equity", "value", "close", "nav", "v", "portfolio_value"].find(k => k in first) ?? null;
      if (dateKey && valKey) {
        return parsed.map((p: Record<string, unknown>) => ({
          date: String(p[dateKey]),
          value: Number(p[valKey]),
        })).filter(p => !isNaN(p.value));
      }
    }

    // Format 2: [[date, value], ...]
    if (Array.isArray(parsed[0]) && parsed[0].length >= 2) {
      return (parsed as [string | number, number][]).map(([d, v]) => ({
        date: String(d),
        value: Number(v),
      })).filter(p => !isNaN(p.value));
    }

    return null;
  } catch {
    return null;
  }
}

function computeDrawdown(equity: EquityPoint[]): DrawdownPoint[] {
  let peak = -Infinity;
  return equity.map(p => {
    if (p.value > peak) peak = p.value;
    const dd = peak > 0 ? ((p.value - peak) / peak) * 100 : 0;
    return { date: p.date, dd: parseFloat(dd.toFixed(2)) };
  });
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SummaryCard({ label, value, sub, good }: { label: string; value: string; sub?: string; good?: boolean }) {
  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 flex flex-col gap-1">
      <p className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">{label}</p>
      <p className={cn("text-xl font-bold font-mono-t tabular-nums",
        good === true ? "text-emerald-400" : good === false ? "text-rose-400" : "text-[var(--text-primary)]"
      )}>
        {value}
      </p>
      {sub && <p className="text-[10px] text-[var(--text-tertiary)]">{sub}</p>}
    </div>
  );
}

function StatusBanner({ status, error }: { status: string; error: string | null }) {
  if (status === "done") return null;
  if (status === "failed") {
    return (
      <div className="flex items-start gap-2 bg-rose-950/30 border border-rose-800/50 rounded-xl p-4">
        <AlertTriangle size={16} className="text-rose-400 shrink-0 mt-0.5" />
        <div>
          <p className="text-rose-400 font-semibold text-sm">Backtest failed</p>
          {error && <p className="text-[var(--text-tertiary)] text-xs mt-1 font-mono">{error}</p>}
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 bg-blue-950/30 border border-blue-800/50 rounded-xl p-4">
      <Clock size={14} className="text-blue-400 animate-spin shrink-0" />
      <p className="text-blue-400 text-sm font-semibold">
        {status === "running" ? "Backtest is running…" : "Backtest is queued…"} Auto-refreshing every 5s.
      </p>
    </div>
  );
}

// ── Custom tooltip ─────────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-xs shadow-lg">
      <p className="text-zinc-400 mb-1">{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} className="font-mono font-bold" style={{ color: p.color }}>
          {p.name}: {typeof p.value === "number" ? (p.name === "Drawdown" ? `${p.value.toFixed(2)}%` : p.value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })) : p.value}
        </p>
      ))}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function BacktestResultPage() {
  const { candidateName, jobId } = useParams<{ candidateName: string; jobId: string }>();
  const name = candidateName ?? "";
  const id   = jobId ?? "";

  const { data, isLoading, error } = useQuery({
    queryKey: ["backtest-result", name, id],
    queryFn: () => getBacktestResult(name, id),
    staleTime: 5_000,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "done" || s === "failed" ? false : 5_000;
    },
  });

  const equity = useMemo(() => data?.equity_curve_json ? parseEquityCurve(data.equity_curve_json) : null, [data?.equity_curve_json]);
  const drawdown = useMemo(() => equity ? computeDrawdown(equity) : null, [equity]);

  // Thin x-axis labels — show at most 12 ticks
  const xTicks = useMemo(() => {
    if (!equity || equity.length <= 12) return undefined;
    const step = Math.ceil(equity.length / 12);
    return equity.filter((_, i) => i % step === 0).map(p => p.date);
  }, [equity]);

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto pb-20 space-y-4 animate-pulse">
        <div className="h-5 bg-zinc-800 rounded w-36" />
        <div className="h-8 bg-zinc-800 rounded w-64" />
        <div className="grid grid-cols-4 gap-3">{[...Array(4)].map((_, i) => <div key={i} className="h-20 bg-zinc-800 rounded-xl" />)}</div>
        <div className="h-64 bg-zinc-800 rounded-xl" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="max-w-4xl mx-auto py-20 text-center">
        <p className="text-rose-400 text-sm">Backtest result not found</p>
        <Link to={`/candidates/${name}`} className="mt-4 inline-block text-xs text-blue-400 hover:text-blue-300">← Back to {name}</Link>
      </div>
    );
  }

  const params = (() => { try { return JSON.parse(data.params_json ?? "{}"); } catch { return {}; } })();

  return (
    <div className="max-w-4xl mx-auto pb-20 md:pb-6 space-y-6">

      {/* Header */}
      <div className="space-y-1">
        <Link to={`/candidates/${name}`} className="inline-flex items-center gap-1 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]">
          <ArrowLeft size={12} /> {name.replace(/_/g, " ")}
        </Link>
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">
            Backtest <span className="text-[var(--text-tertiary)] font-mono text-base">{id.slice(0, 8)}…</span>
          </h1>
          <span className={cn("inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider",
            data.status === "done"    ? "text-emerald-400 bg-emerald-900/30" :
            data.status === "failed"  ? "text-rose-400 bg-rose-900/30" :
            data.status === "running" ? "text-blue-400 bg-blue-900/30" :
                                        "text-amber-400 bg-amber-900/30"
          )}>
            {data.status === "running" && <Clock size={9} className="animate-spin mr-1" />}
            {data.status}
          </span>
        </div>
        <p className="text-xs text-[var(--text-tertiary)]">
          Period: {data.start_date ?? "—"} to {data.end_date ?? "—"}
          {params.capital != null && ` · Capital: $${Number(params.capital).toLocaleString()}`}
        </p>
      </div>

      <StatusBanner status={data.status} error={data.error_message} />

      {/* Primary metric cards */}
      {data.status === "done" && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <SummaryCard
              label="Net Sharpe"
              value={fmt(data.net_sharpe)}
              sub="post-cost annualized"
              good={data.net_sharpe != null ? data.net_sharpe >= 0.5 : undefined}
            />
            <SummaryCard
              label="Max Drawdown"
              value={data.max_drawdown_pct != null ? `${fmt(data.max_drawdown_pct)}%` : "—"}
              sub="peak-to-trough"
              good={data.max_drawdown_pct != null ? data.max_drawdown_pct <= 25 : undefined}
            />
            <SummaryCard
              label="Win Rate"
              value={data.win_rate != null ? `${fmt(data.win_rate, 1)}%` : "—"}
              good={data.win_rate != null ? data.win_rate >= 50 : undefined}
            />
            <SummaryCard
              label="Trades"
              value={data.n_trades != null ? String(data.n_trades) : "—"}
              sub="total executed"
            />
          </div>

          {/* Secondary metrics */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "Gross Sharpe",   value: fmt(data.gross_sharpe) },
              { label: "Profit Factor",  value: fmt(data.profit_factor) },
              { label: "Cost Drag",      value: data.total_cost_pct != null ? `${fmt(data.total_cost_pct, 1)}%` : "—" },
              { label: "Beta to SPY",    value: fmt(data.beta_spy) },
            ].map(({ label, value }) => (
              <div key={label} className="bg-[var(--bg-elevated)]/60 border border-[var(--border-subtle)]/60 rounded-xl px-4 py-3 flex flex-col gap-1">
                <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider font-semibold">{label}</p>
                <p className="font-mono font-bold text-[var(--text-secondary)] tabular-nums">{value}</p>
              </div>
            ))}
          </div>

          {/* Comparison to previous run */}
          {data.previous_run && (
            <div className="flex flex-wrap gap-4 bg-[var(--bg-elevated)]/40 border border-[var(--border-subtle)]/50 rounded-xl px-4 py-3">
              <span className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider font-semibold self-center">vs previous backtest</span>
              <DeltaChip current={data.net_sharpe} previous={data.previous_run.net_sharpe} />
              {data.max_drawdown_pct != null && data.previous_run.max_drawdown_pct != null && (
                <span className={cn("inline-flex items-center gap-0.5 text-[10px] font-bold",
                  data.max_drawdown_pct <= data.previous_run.max_drawdown_pct ? "text-emerald-400" : "text-rose-400"
                )}>
                  DD: {fmt(data.max_drawdown_pct)}% vs {fmt(data.previous_run.max_drawdown_pct)}%
                </span>
              )}
            </div>
          )}

          {/* Equity curve */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-4">
            <p className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-4">Equity Curve</p>
            {equity && equity.length > 1 ? (
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={equity} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="date" ticks={xTicks} tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} tickLine={false} axisLine={false} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} width={44} />
                  <Tooltip content={<ChartTooltip />} />
                  <Line type="monotone" dataKey="value" name="Portfolio" dot={false} stroke="#3b82f6" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[240px] flex items-center justify-center text-[var(--text-tertiary)] text-sm">
                Equity curve unavailable for this run
              </div>
            )}
          </div>

          {/* Drawdown chart */}
          {drawdown && drawdown.length > 1 && (
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-2xl p-4">
              <p className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-4">Drawdown</p>
              <ResponsiveContainer width="100%" height={160}>
                <AreaChart data={drawdown} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="date" ticks={xTicks} tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--text-tertiary)" }} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}%`} width={44} />
                  <Tooltip content={<ChartTooltip />} />
                  <defs>
                    <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#f43f5e" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="#f43f5e" stopOpacity={0.05} />
                    </linearGradient>
                  </defs>
                  <Area type="monotone" dataKey="dd" name="Drawdown" dot={false} stroke="#f43f5e" strokeWidth={1.5} fill="url(#ddGrad)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}

      {/* Disclosure */}
      <div className="bg-zinc-900/40 border border-zinc-800/50 rounded-xl px-4 py-3">
        <p className="text-[10px] text-zinc-600 leading-relaxed">
          Backtest costs computed via Almgren-Chriss square-root impact model with maker/taker fees per exchange. Net Sharpe reflects realistic post-cost performance. Backtest does not capture: market regime changes not present in historical data, liquidity black swans, or exchange downtime. Past performance does not predict future returns.
        </p>
      </div>
    </div>
  );
}

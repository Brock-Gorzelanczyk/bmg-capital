/**
 * BacktestPanel — Strategy Scout: extended Past Triggers with year filter,
 * aggregate stats card, sortable trigger table, and a cumulative equity curve.
 *
 * Replaces the legacy 5-row "PAST TRIGGERS" table on /strategy/scout/<sym>/<id>.
 * Backend: GET /api/strategy/<id>/backtest?symbol=<sym>&years=<N>.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import client from "@/api/client";
import { cn } from "@/lib/utils";
import { ProgressBar } from "./ProgressBar";
import { Skeleton } from "./Skeleton";

type SortKey = "date" | "return" | "hold";
type YearFilter = 1 | 3 | 5 | 0; // 0 == ALL

interface BacktestTrigger {
  entry_date: string;
  entry_price: number;
  exit_date: string;
  exit_price: number;
  return_pct: number;
  hold_days: number;
  mfe_pct: number;
  mae_pct: number;
}

interface BacktestResult {
  strategy_id: string;
  symbol: string;
  years_requested: number;
  years_available: number;
  bar_count: number;
  triggers: BacktestTrigger[];
  trigger_count: number;
  win_rate: number | null;
  avg_return: number | null;
  median_return: number | null;
  sharpe: number | null;
  max_dd: number;
  profit_factor: number | null;
  avg_hold_days: number | null;
  equity_curve: { date: string; cum_return: number }[];
}

const YEAR_OPTIONS: { label: string; value: YearFilter }[] = [
  { label: "1Y", value: 1 },
  { label: "3Y", value: 3 },
  { label: "5Y", value: 5 },
  { label: "ALL", value: 0 },
];

function fmtPct(v: number | null | undefined, decimals = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(decimals)}%`;
}

function fmtDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

interface Props {
  ticker: string;
  strategyId: string;
  /** Called with a trigger when its row is clicked — parent should highlight the date on the chart. */
  onSelectTrigger?: (t: BacktestTrigger) => void;
}

export default function BacktestPanel({ ticker, strategyId, onSelectTrigger }: Props) {
  const [years, setYears] = useState<YearFilter>(5);
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sortDesc, setSortDesc] = useState(true);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["scout-backtest", ticker, strategyId, years],
    queryFn: async () => {
      const r = await client.get<BacktestResult>(`/strategy/${strategyId}/backtest`, {
        params: { symbol: ticker, years },
      });
      return r.data;
    },
    staleTime: 60_000,
    retry: 0,
  });

  // ProgressBar surfaces an elapsed counter after 5 s. We capture the
  // fetch start when the query key changes (i.e. a new backtest run begins).
  // Using useMemo keyed on [ticker, strategyId, years] gives us a fresh
  // start timestamp per request without setState-in-effect lint trips.
  const fetchStart = useMemo(
    () => Date.now(),
    [ticker, strategyId, years],
  );

  // Human-readable lookback window for the loading message — derived from
  // the same year filter we send to the backend so the two stay in sync.
  const yearsLabel =
    years === 0 ? "all available" : `${years} year${years === 1 ? "" : "s"}`;

  const triggers = useMemo(() => {
    const rows = [...(data?.triggers ?? [])];
    rows.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "date":
          cmp = a.entry_date.localeCompare(b.entry_date);
          break;
        case "return":
          cmp = a.return_pct - b.return_pct;
          break;
        case "hold":
          cmp = a.hold_days - b.hold_days;
          break;
      }
      return sortDesc ? -cmp : cmp;
    });
    return rows;
  }, [data, sortKey, sortDesc]);

  const flipSort = (k: SortKey) => {
    if (sortKey === k) setSortDesc(!sortDesc);
    else {
      setSortKey(k);
      setSortDesc(true);
    }
  };

  // Build an inline SVG equity curve (compact, no extra deps)
  const equityPath = useMemo(() => {
    const curve = data?.equity_curve ?? [];
    if (curve.length < 2) return null;
    const W = 600;
    const H = 80;
    const xs = curve.map((_, i) => (i / (curve.length - 1)) * W);
    const ys = curve.map(p => p.cum_return);
    const minY = Math.min(0, ...ys);
    const maxY = Math.max(0, ...ys);
    const range = maxY - minY || 1;
    const scaleY = (y: number) => H - ((y - minY) / range) * H;
    let d = `M ${xs[0].toFixed(1)} ${scaleY(ys[0]).toFixed(1)}`;
    for (let i = 1; i < curve.length; i++) {
      d += ` L ${xs[i].toFixed(1)} ${scaleY(ys[i]).toFixed(1)}`;
    }
    const final = ys[ys.length - 1];
    return { d, W, H, final, zero: scaleY(0) };
  }, [data]);

  return (
    <div className="bg-t-bg1 border border-t-dim rounded-2xl p-5 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <span className="text-[10px] font-mono-t text-t-faint uppercase tracking-widest">
          // PAST TRIGGERS · {ticker} × {strategyId}
        </span>
        <div className="flex items-center gap-1">
          {YEAR_OPTIONS.map(opt => (
            <button
              key={opt.label}
              onClick={() => setYears(opt.value)}
              className={cn(
                "text-[10px] font-mono-t px-2 py-1 rounded border transition-colors",
                years === opt.value
                  ? "border-t-mid text-t-hi bg-t-bg2"
                  : "border-t-dim/40 text-t-muted hover:text-t-hi hover:border-t-dim"
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading && (
        // Group D loading: indeterminate progress bar describing the work
        // ("Backtesting N years of bars…") + a skeleton of the stat strip
        // and triggers table so the panel doesn't visually collapse.
        <div className="space-y-3 py-1">
          <ProgressBar
            label={`Backtesting ${yearsLabel} of bars for ${ticker}…`}
            detail={strategyId}
            startedAt={fetchStart}
          />
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
            {[...Array(7)].map((_, i) => (
              <div
                key={i}
                className="bg-t-bg0 border border-t-dim/40 rounded-md p-2 space-y-1"
              >
                <Skeleton h="9px" w="60%" />
                <Skeleton h="14px" w="50%" />
              </div>
            ))}
          </div>
          <div className="space-y-1.5 pt-1">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="flex items-center gap-3">
                <Skeleton h="11px" w="80px" shimmer />
                <Skeleton h="11px" w="50px" shimmer />
                <Skeleton h="11px" w="50px" shimmer />
                <div className="ml-auto flex items-center gap-3">
                  <Skeleton h="11px" w="44px" shimmer />
                  <Skeleton h="11px" w="32px" shimmer />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {isError && (
        <div className="text-t-red text-xs py-6 text-center">
          Could not load backtest — endpoint may not have bar data for this symbol.
        </div>
      )}

      {data && !isLoading && (
        <>
          {/* Stats card */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 text-xs">
            <Stat label="Triggers" value={String(data.trigger_count)} />
            <Stat
              label="Win rate"
              value={data.win_rate != null ? `${(data.win_rate * 100).toFixed(0)}%` : "—"}
              tone={data.win_rate != null && data.win_rate >= 0.5 ? "good" : "muted"}
            />
            <Stat
              label="Avg return"
              value={fmtPct(data.avg_return)}
              tone={data.avg_return != null ? (data.avg_return >= 0 ? "good" : "bad") : "muted"}
            />
            <Stat label="Median" value={fmtPct(data.median_return)} />
            <Stat
              label="Sharpe"
              value={data.sharpe != null ? data.sharpe.toFixed(2) : "—"}
              tone={data.sharpe != null && data.sharpe >= 1 ? "good" : "muted"}
            />
            <Stat
              label="Max DD"
              value={fmtPct(data.max_dd)}
              tone={data.max_dd < -0.2 ? "bad" : "muted"}
            />
            <Stat
              label="Profit factor"
              value={data.profit_factor != null ? data.profit_factor.toFixed(2) : "—"}
              tone={data.profit_factor != null && data.profit_factor >= 1.5 ? "good" : "muted"}
            />
          </div>

          {/* Data span hint */}
          <div className="text-[10px] font-mono-t text-t-faint">
            Based on {data.years_available} years ({data.bar_count} bars). Avg hold:{" "}
            {data.avg_hold_days != null ? `${data.avg_hold_days.toFixed(1)}d` : "—"}.
          </div>

          {/* Equity curve */}
          {equityPath && (
            <div className="border border-t-dim/40 rounded-md p-2 bg-t-bg0/40">
              <div className="text-[10px] font-mono-t text-t-faint mb-1">
                EQUITY CURVE (cumulative return through triggers)
              </div>
              <svg
                viewBox={`0 0 ${equityPath.W} ${equityPath.H}`}
                className="w-full h-20"
                preserveAspectRatio="none"
              >
                <line
                  x1={0}
                  y1={equityPath.zero}
                  x2={equityPath.W}
                  y2={equityPath.zero}
                  stroke="currentColor"
                  className="text-t-dim"
                  strokeDasharray="2 2"
                  strokeWidth={0.5}
                />
                <path
                  d={equityPath.d}
                  fill="none"
                  stroke={equityPath.final >= 0 ? "#22c55e" : "#ef4444"}
                  strokeWidth={1.5}
                />
              </svg>
              <div
                className={cn(
                  "text-[10px] font-mono-t text-right mt-0.5",
                  equityPath.final >= 0 ? "text-t-green" : "text-t-red"
                )}
              >
                {fmtPct(equityPath.final)} total
              </div>
            </div>
          )}

          {/* Triggers table */}
          {triggers.length === 0 ? (
            <div className="text-t-muted text-xs py-4 text-center">
              No triggers in the selected window.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono-t">
                <thead>
                  <tr className="text-t-gdim border-b border-t-dim/50">
                    <SortHeader label="Date" k="date" sortKey={sortKey} desc={sortDesc} onClick={flipSort} />
                    <th className="text-right pb-2 font-medium">Entry</th>
                    <th className="text-right pb-2 font-medium">Exit</th>
                    <SortHeader label="Return" k="return" sortKey={sortKey} desc={sortDesc} onClick={flipSort} align="right" />
                    <SortHeader label="Hold" k="hold" sortKey={sortKey} desc={sortDesc} onClick={flipSort} align="right" />
                    <th className="text-right pb-2 font-medium">MFE / MAE</th>
                  </tr>
                </thead>
                <tbody>
                  {triggers.map((t, i) => (
                    <tr
                      key={`${t.entry_date}-${i}`}
                      onClick={() => onSelectTrigger?.(t)}
                      className={cn(
                        "border-b border-t-dim/30 last:border-0",
                        onSelectTrigger && "cursor-pointer hover:bg-t-bg2/40"
                      )}
                    >
                      <td className="py-1.5 text-t-body">{fmtDate(t.entry_date)}</td>
                      <td className="py-1.5 text-right text-t-muted">${t.entry_price.toFixed(2)}</td>
                      <td className="py-1.5 text-right text-t-muted">${t.exit_price.toFixed(2)}</td>
                      <td
                        className={cn(
                          "py-1.5 text-right font-semibold",
                          t.return_pct >= 0 ? "text-t-green" : "text-t-red"
                        )}
                      >
                        {fmtPct(t.return_pct)}
                      </td>
                      <td className="py-1.5 text-right text-t-muted">{t.hold_days}d</td>
                      <td className="py-1.5 text-right text-t-muted text-[10px]">
                        <span className="text-t-green/70">{fmtPct(t.mfe_pct, 1)}</span>
                        {" / "}
                        <span className="text-t-red/70">{fmtPct(t.mae_pct, 1)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

interface StatProps {
  label: string;
  value: string;
  tone?: "good" | "bad" | "muted";
}

function Stat({ label, value, tone = "muted" }: StatProps) {
  return (
    <div className="bg-t-bg0 border border-t-dim/40 rounded-md p-2">
      <div className="text-[9px] uppercase tracking-widest text-t-faint">{label}</div>
      <div
        className={cn(
          "font-semibold tabular-nums mt-0.5",
          tone === "good" && "text-t-green",
          tone === "bad" && "text-t-red",
          tone === "muted" && "text-t-hi"
        )}
      >
        {value}
      </div>
    </div>
  );
}

interface SortHeaderProps {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  desc: boolean;
  onClick: (k: SortKey) => void;
  align?: "left" | "right";
}

function SortHeader({ label, k, sortKey, desc, onClick, align = "left" }: SortHeaderProps) {
  const active = sortKey === k;
  return (
    <th
      className={cn(
        "pb-2 font-medium select-none cursor-pointer hover:text-t-hi",
        align === "right" ? "text-right" : "text-left"
      )}
      onClick={() => onClick(k)}
    >
      {label}
      {active ? (desc ? " ↓" : " ↑") : ""}
    </th>
  );
}

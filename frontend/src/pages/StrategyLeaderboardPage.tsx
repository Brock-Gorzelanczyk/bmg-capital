import { useState, useMemo } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { BracketFrame, SectionLabel, BMGButton } from "@/components/design";
import { cn } from "@/lib/utils";
import {
  getStrategyLeaderboard,
  type StrategyLeaderboardRow,
  type Period,
  type StratSort,
} from "@/api/performance";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtUsd(v: number) {
  const abs = Math.abs(v);
  const s = abs >= 1000 ? `$${(abs / 1000).toFixed(1)}k` : `$${abs.toFixed(0)}`;
  return v < 0 ? `-${s}` : `+${s}`;
}

function fmtPct(v: number | null) {
  if (v == null) return "—";
  const s = (Math.abs(v) * 100).toFixed(1) + "%";
  return v < 0 ? `-${s}` : `+${s}`;
}

function pctColor(v: number | null) {
  if (v == null) return "text-zinc-400";
  return v >= 0 ? "text-emerald-400" : "text-red-400";
}

function usdColor(v: number) {
  return v >= 0 ? "text-emerald-400" : "text-red-400";
}

// ── Constants ─────────────────────────────────────────────────────────────────

const PERIODS: { label: string; value: Period }[] = [
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" },
  { label: "90d", value: "90d" },
  { label: "All", value: "all" },
];

const CATEGORIES = ["All", "Trend", "Mean Reversion", "Quant", "Momentum"];

const SORTS: { label: string; value: StratSort }[] = [
  { label: "$ P&L", value: "pnl" },
  { label: "Return %", value: "return" },
  { label: "Win Rate", value: "win_rate" },
  { label: "Trades", value: "trades" },
];

// ── StrategyDetailModal ───────────────────────────────────────────────────────

interface ModalProps {
  row: StrategyLeaderboardRow;
  onClose: () => void;
}

function StrategyDetailModal({ row, onClose }: ModalProps) {
  const sourceLabel = row.source?.toUpperCase() ?? "BOT";

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <BracketFrame className="w-full max-w-lg bg-zinc-950 rounded-2xl p-6" bracketSize={14}>
        {/* Header */}
        <div className="flex items-start justify-between gap-3 mb-6">
          <div className="min-w-0">
            <SectionLabel as="p" className="mb-1">
              // STRATEGY DETAIL — {row.strategy_name}
            </SectionLabel>
            <div className="mt-2 flex items-center gap-2 flex-wrap">
              <span className="font-mono text-[10px] uppercase tracking-widest px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700">
                {sourceLabel}
              </span>
              {row.category && (
                <span className="font-mono text-[10px] uppercase tracking-widest px-2 py-0.5 rounded bg-zinc-800/50 text-zinc-500 border border-zinc-800">
                  {row.category}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 text-zinc-500 hover:text-white transition-colors text-lg leading-none mt-0.5"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* 3-stat row */}
        <div className="grid grid-cols-3 gap-3 mb-6">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 text-center">
            <SectionLabel className="block mb-1 text-zinc-600">$ P&amp;L</SectionLabel>
            <span className={cn("font-mono text-lg font-semibold tabular-nums", usdColor(row.total_pnl_usd))}>
              {fmtUsd(row.total_pnl_usd)}
            </span>
          </div>
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 text-center">
            <SectionLabel className="block mb-1 text-zinc-600">Return %</SectionLabel>
            <span className={cn("font-mono text-lg font-semibold tabular-nums", pctColor(row.weighted_return_pct))}>
              {fmtPct(row.weighted_return_pct)}
            </span>
          </div>
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 text-center">
            <SectionLabel className="block mb-1 text-zinc-600">Win Rate</SectionLabel>
            <span className={cn("font-mono text-lg font-semibold tabular-nums", pctColor(row.win_rate))}>
              {row.win_rate != null ? `${(row.win_rate * 100).toFixed(1)}%` : "—"}
            </span>
          </div>
        </div>

        {/* Bots note */}
        <p className="text-xs text-zinc-500 font-mono mb-6">
          Runs in{" "}
          <span className="text-zinc-300 font-semibold">{row.bots_using}</span>{" "}
          {row.bots_using === 1 ? "bot" : "bots"} &middot;{" "}
          <span className="text-zinc-400">{row.total_trades.toLocaleString()} total trades</span>
        </p>

        {/* CTA */}
        <div className="flex items-center gap-3">
          <Link to="/strategy/forge" className="flex-1">
            <BMGButton variant="primary" size="md" className="w-full">
              Add to a Forge bot →
            </BMGButton>
          </Link>
          <BMGButton variant="secondary" size="md" onClick={onClose}>
            Close
          </BMGButton>
        </div>
      </BracketFrame>
    </div>,
    document.body
  );
}

// ── KPI Cards ─────────────────────────────────────────────────────────────────

interface KpiCardProps {
  label: string;
  name: string | null;
  value: string;
  valueClass?: string;
}

function KpiCard({ label, name, value, valueClass }: KpiCardProps) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-4 py-3 min-w-0">
      <SectionLabel as="p" className="mb-1 text-zinc-600">
        {label}
      </SectionLabel>
      {name && (
        <p className="text-xs text-zinc-400 font-mono truncate mb-0.5">{name}</p>
      )}
      <p className={cn("font-mono text-lg font-semibold tabular-nums", valueClass ?? "text-white")}>
        {value}
      </p>
    </div>
  );
}

// ── PillButton ────────────────────────────────────────────────────────────────

interface PillButtonProps {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function PillButton({ active, onClick, children }: PillButtonProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-3 py-1.5 rounded-lg font-mono text-[11px] uppercase tracking-widest transition-all duration-150",
        active
          ? "bg-zinc-700 text-white"
          : "bg-zinc-900 border border-zinc-800 text-zinc-500 hover:text-zinc-300 hover:border-zinc-700"
      )}
    >
      {children}
    </button>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function SkeletonRows() {
  return (
    <div className="flex flex-col gap-2 p-4">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="h-12 rounded-xl bg-zinc-900 border border-zinc-800 animate-pulse"
        />
      ))}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function StrategyLeaderboardPage() {
  const [period, setPeriod] = useState<Period>("30d");
  const [category, setCategory] = useState("All");
  const [sort, setSort] = useState<StratSort>("pnl");
  const [selected, setSelected] = useState<StrategyLeaderboardRow | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["strategy-leaderboard", period, sort],
    queryFn: () => getStrategyLeaderboard(period, sort),
    staleTime: 300_000,
    retry: 0,
  });

  // Client-side category filter
  const rows = useMemo(() => {
    const all = data?.strategies ?? [];
    if (category === "All") return all;
    return all.filter(
      (r) => r.category?.toLowerCase() === category.toLowerCase()
    );
  }, [data, category]);

  // KPI derivations
  const kpi = useMemo(() => {
    const all = data?.strategies ?? [];
    if (!all.length) return null;

    const bestPnl = all.reduce((a, b) => (b.total_pnl_usd > a.total_pnl_usd ? b : a), all[0]);
    const worstPnl = all.reduce((a, b) => (b.total_pnl_usd < a.total_pnl_usd ? b : a), all[0]);
    const bestReturn = all.reduce((a, b) => {
      const av = a.weighted_return_pct ?? -Infinity;
      const bv = b.weighted_return_pct ?? -Infinity;
      return bv > av ? b : a;
    }, all[0]);
    const mostDeployed = all.reduce((a, b) => (b.bots_using > a.bots_using ? b : a), all[0]);

    return { bestPnl, worstPnl, bestReturn, mostDeployed };
  }, [data]);

  // ── Error state (treat as 404 / feature not enabled) ─────────────────────
  if (isError) {
    return (
      <div className="min-h-screen bg-zinc-950 text-white p-6 flex items-start justify-center pt-20">
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-10 text-center max-w-md w-full">
          <SectionLabel as="p" className="mb-3 text-zinc-600">
            // Performance Analytics
          </SectionLabel>
          <p className="text-white font-semibold mb-2">Performance analytics not enabled</p>
          <p className="text-zinc-500 text-sm">
            Strategy performance tracking requires an active bot with trades. Enable the analytics
            feature flag or start a bot to see data here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8 space-y-6">

        {/* ── Header ──────────────────────────────────────────────────────── */}
        <div>
          <SectionLabel as="h1" className="text-base mb-1">
            // STRATEGY LEADERBOARD
          </SectionLabel>
          <p className="text-sm text-zinc-500">
            Dollar-weighted performance across every strategy in every bot.
          </p>
        </div>

        {/* ── KPI Cards ───────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {isLoading || !kpi ? (
            Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="bg-zinc-900 border border-zinc-800 rounded-2xl px-4 py-3 h-20 animate-pulse"
              />
            ))
          ) : (
            <>
              <KpiCard
                label="Best $ P&L"
                name={kpi.bestPnl.strategy_name}
                value={fmtUsd(kpi.bestPnl.total_pnl_usd)}
                valueClass="text-emerald-400"
              />
              <KpiCard
                label="Best Return"
                name={kpi.bestReturn.strategy_name}
                value={fmtPct(kpi.bestReturn.weighted_return_pct)}
                valueClass={pctColor(kpi.bestReturn.weighted_return_pct)}
              />
              <KpiCard
                label="Worst $ P&L"
                name={kpi.worstPnl.strategy_name}
                value={fmtUsd(kpi.worstPnl.total_pnl_usd)}
                valueClass="text-red-400"
              />
              <KpiCard
                label="Most Deployed"
                name={kpi.mostDeployed.strategy_name}
                value={`${kpi.mostDeployed.bots_using} bots`}
                valueClass="text-zinc-200"
              />
            </>
          )}
        </div>

        {/* ── Filter Row ──────────────────────────────────────────────────── */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Period */}
          <div className="flex items-center gap-1">
            {PERIODS.map((p) => (
              <PillButton key={p.value} active={period === p.value} onClick={() => setPeriod(p.value)}>
                {p.label}
              </PillButton>
            ))}
          </div>

          <div className="w-px h-6 bg-zinc-800 hidden sm:block" />

          {/* Category */}
          <div className="flex items-center gap-1 flex-wrap">
            {CATEGORIES.map((c) => (
              <PillButton key={c} active={category === c} onClick={() => setCategory(c)}>
                {c}
              </PillButton>
            ))}
          </div>

          <div className="w-px h-6 bg-zinc-800 hidden sm:block" />

          {/* Sort */}
          <div className="flex items-center gap-1">
            {SORTS.map((s) => (
              <PillButton key={s.value} active={sort === s.value} onClick={() => setSort(s.value)}>
                {s.label}
              </PillButton>
            ))}
          </div>
        </div>

        {/* ── Table ───────────────────────────────────────────────────────── */}
        {isLoading ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
            <SkeletonRows />
          </div>
        ) : rows.length === 0 ? (
          /* Empty state */
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-12 text-center">
            <SectionLabel as="p" className="mb-2 text-zinc-600">
              // No Data
            </SectionLabel>
            <p className="text-white font-semibold mb-1">No strategy data yet</p>
            <p className="text-zinc-500 text-sm">
              Strategies from active bots will appear here.
            </p>
          </div>
        ) : (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
            {/* Column headers */}
            <div className="grid grid-cols-[40px_1fr_120px_110px_100px_90px_70px_60px] gap-2 px-4 py-2 border-b border-zinc-800">
              {["Rank", "Strategy", "Category", "$ P&L", "Return %", "Win Rate", "Trades", "Bots"].map((h) => (
                <span key={h} className="text-[10px] uppercase tracking-widest text-zinc-600 font-mono">
                  {h}
                </span>
              ))}
            </div>

            {/* Rows */}
            <div>
              {rows.map((row, idx) => (
                <button
                  key={row.strategy_id}
                  onClick={() => setSelected(row)}
                  className="w-full text-left grid grid-cols-[40px_1fr_120px_110px_100px_90px_70px_60px] gap-2 px-4 py-3 border-b border-zinc-800/50 last:border-b-0 hover:bg-zinc-800/40 cursor-pointer transition-colors duration-100"
                >
                  {/* Rank */}
                  <span className="font-mono text-sm text-zinc-500 tabular-nums self-center">
                    {idx + 1}
                  </span>

                  {/* Strategy */}
                  <div className="min-w-0 self-center">
                    <p className="text-white font-semibold text-sm truncate leading-tight">
                      {row.strategy_name}
                    </p>
                  </div>

                  {/* Category */}
                  <div className="self-center">
                    {row.category ? (
                      <span className="font-mono text-[10px] uppercase tracking-widest px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700 whitespace-nowrap">
                        {row.category}
                      </span>
                    ) : (
                      <span className="text-zinc-600 text-xs">—</span>
                    )}
                  </div>

                  {/* $ P&L */}
                  <span
                    className={cn(
                      "font-mono text-sm tabular-nums self-center",
                      usdColor(row.total_pnl_usd)
                    )}
                  >
                    {fmtUsd(row.total_pnl_usd)}
                  </span>

                  {/* Return % */}
                  <span
                    className={cn(
                      "font-mono text-sm tabular-nums self-center",
                      pctColor(row.weighted_return_pct)
                    )}
                  >
                    {fmtPct(row.weighted_return_pct)}
                  </span>

                  {/* Win Rate */}
                  <span
                    className={cn(
                      "font-mono text-sm tabular-nums self-center",
                      pctColor(row.win_rate)
                    )}
                  >
                    {row.win_rate != null
                      ? `${(row.win_rate * 100).toFixed(1)}%`
                      : "—"}
                  </span>

                  {/* Trades */}
                  <span className="font-mono text-sm tabular-nums text-zinc-300 self-center">
                    {row.total_trades.toLocaleString()}
                  </span>

                  {/* Bots */}
                  <span className="font-mono text-sm tabular-nums text-zinc-400 self-center">
                    {row.bots_using}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Detail Modal ──────────────────────────────────────────────────── */}
      {selected && (
        <StrategyDetailModal row={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

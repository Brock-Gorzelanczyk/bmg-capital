import { useState, useMemo } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { BracketFrame, SectionLabel, BMGButton } from "@/components/design";
import { cn } from "@/lib/utils";
import {
  getStrategyLeaderboard,
  getBotLeaderboardRanking,
  type StrategyLeaderboardRow,
  type BotLeaderboardRow,
  type BotLbSort,
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
  if (v == null) return "text-t-muted";
  return v >= 0 ? "text-t-green" : "text-t-red";
}

function usdColor(v: number) {
  return v >= 0 ? "text-t-green" : "text-t-red";
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
      <BracketFrame className="w-full max-w-lg bg-t-bg0 rounded-2xl p-6" bracketSize={14}>
        {/* Header */}
        <div className="flex items-start justify-between gap-3 mb-6">
          <div className="min-w-0">
            <SectionLabel as="p" className="mb-1">
              // STRATEGY DETAIL — {row.strategy_name}
            </SectionLabel>
            <div className="mt-2 flex items-center gap-2 flex-wrap">
              <span className="font-mono-t text-[10px] uppercase tracking-widest px-2 py-0.5 rounded bg-t-bg1 text-t-mid2 border border-t-dim">
                {sourceLabel}
              </span>
              {row.category && (
                <span className="font-mono-t text-[10px] uppercase tracking-widest px-2 py-0.5 rounded bg-t-bg1/50 text-t-muted border border-t-dim">
                  {row.category}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 text-t-muted hover:text-t-hi transition-colors text-lg leading-none mt-0.5"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* 3-stat row */}
        <div className="grid grid-cols-3 gap-3 mb-6">
          <div className="bg-t-bg1 border border-t-dim rounded-xl px-4 py-3 text-center">
            <SectionLabel className="block mb-1 text-t-gdim">$ P&amp;L</SectionLabel>
            <span className={cn("font-mono-t text-lg font-semibold tabular-nums", usdColor(row.total_pnl_usd))}>
              {fmtUsd(row.total_pnl_usd)}
            </span>
          </div>
          <div className="bg-t-bg1 border border-t-dim rounded-xl px-4 py-3 text-center">
            <SectionLabel className="block mb-1 text-t-gdim">Return %</SectionLabel>
            <span className={cn("font-mono-t text-lg font-semibold tabular-nums", pctColor(row.weighted_return_pct))}>
              {fmtPct(row.weighted_return_pct)}
            </span>
          </div>
          <div className="bg-t-bg1 border border-t-dim rounded-xl px-4 py-3 text-center">
            <SectionLabel className="block mb-1 text-t-gdim">Win Rate</SectionLabel>
            <span className={cn("font-mono-t text-lg font-semibold tabular-nums", pctColor(row.win_rate))}>
              {row.win_rate != null ? `${(row.win_rate * 100).toFixed(1)}%` : "—"}
            </span>
          </div>
        </div>

        {/* Bots note */}
        <p className="text-xs text-t-muted font-mono-t mb-6">
          Runs in{" "}
          <span className="text-t-mid2 font-semibold">{row.bots_using}</span>{" "}
          {row.bots_using === 1 ? "bot" : "bots"} &middot;{" "}
          <span className="text-t-muted">{row.total_trades.toLocaleString()} total trades</span>
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
    <div className="bg-t-bg1 border border-t-dim rounded-2xl px-4 py-3 min-w-0">
      <SectionLabel as="p" className="mb-1 text-t-gdim">
        {label}
      </SectionLabel>
      {name && (
        <p className="text-xs text-t-muted font-mono-t truncate mb-0.5">{name}</p>
      )}
      <p className={cn("font-mono-t text-lg font-semibold tabular-nums", valueClass ?? "text-t-hi")}>
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
        "px-3 py-1.5 rounded-lg font-mono-t text-[11px] uppercase tracking-widest transition-all duration-150",
        active
          ? "bg-t-bg2 text-t-hi"
          : "bg-t-bg1 border border-t-dim text-t-muted hover:text-t-mid2 hover:border-t-mid"
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
          className="h-12 rounded-xl bg-t-bg1 border border-t-dim animate-pulse"
        />
      ))}
    </div>
  );
}

// ── Tier badge helpers ────────────────────────────────────────────────────────

const TIER_BADGE: Record<string, string> = {
  T3: "text-t-green border-t-green/30 bg-t-green/10",
  T2: "text-t-cyan border-t-cyan/30 bg-t-cyan/10",
  T1: "text-t-amber border-t-amber/30 bg-t-amber/10",
  T0: "text-t-muted border-t-muted/30 bg-t-muted/10",
};

const BOT_LB_SORTS: { label: string; value: BotLbSort }[] = [
  { label: "All-Time %", value: "pnl" },
  { label: "Sharpe", value: "sharpe" },
  { label: "Win Rate", value: "win_rate" },
  { label: "Drawdown", value: "drawdown" },
];

const RANK_RING: Record<number, string> = {
  1: "ring-1 ring-t-amber/50",
  2: "ring-1 ring-t-muted/40",
  3: "ring-1 ring-t-amber/30",
};

function BotLeaderboardTable({ sort }: { sort: BotLbSort }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["bot-leaderboard-ranking", sort],
    queryFn: () => getBotLeaderboardRanking(sort),
    staleTime: 120_000,
    retry: 0,
  });

  const rows = data?.strategies ?? [];

  if (isLoading) {
    return (
      <div className="bg-t-bg1 border border-t-dim rounded-2xl overflow-hidden">
        <SkeletonRows />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="bg-t-bg1 border border-t-dim rounded-2xl px-5 py-12 text-center">
        <SectionLabel as="p" className="mb-2 text-t-gdim">// Bot Ranking</SectionLabel>
        <p className="text-t-hi font-semibold mb-1">Could not load bot rankings</p>
        <p className="text-t-muted text-sm">Check that bots are enabled and try again.</p>
      </div>
    );
  }

  if (!rows.length) {
    return (
      <div className="bg-t-bg1 border border-t-dim rounded-2xl px-5 py-12 text-center">
        <SectionLabel as="p" className="mb-2 text-t-gdim">// Bot Ranking</SectionLabel>
        <p className="text-t-hi font-semibold mb-1">No bot data yet</p>
        <p className="text-t-muted text-sm">Enable bots and wait for the first nightly rollup (2am ET).</p>
      </div>
    );
  }

  return (
    <div className="bg-t-bg1 border border-t-dim rounded-2xl overflow-hidden">
      <div className="grid grid-cols-[36px_1fr_72px_100px_100px_90px_80px_70px_70px_60px] gap-2 px-4 py-2 border-b border-t-dim">
        {["#", "Bot", "Tier", "Start $", "Now $", "All-Time %", "Sharpe", "Win %", "Trades", "Days"].map((h) => (
          <span key={h} className="text-[10px] uppercase tracking-widest text-t-gdim font-mono-t">{h}</span>
        ))}
      </div>
      <div>
        {rows.map((row) => {
          const isUp = row.all_time_pnl_pct >= 0;
          return (
            <Link
              key={row.allocation_id}
              to={`/strategy/${row.bot_id}`}
              className={cn(
                "w-full text-left grid grid-cols-[36px_1fr_72px_100px_100px_90px_80px_70px_70px_60px] gap-2 px-4 py-3 border-b border-t-dim/50 last:border-b-0 hover:bg-t-bg2/40 transition-colors duration-100 rounded-none card-hover",
                RANK_RING[row.rank]
              )}
            >
              <span className="font-mono-t text-sm text-t-muted tabular-nums self-center">{row.rank}</span>
              <div className="min-w-0 self-center">
                <p className="text-t-hi font-semibold text-sm truncate leading-tight">{row.strategy_name}</p>
                {!row.enabled && <p className="text-t-gdim text-[10px]">disabled</p>}
              </div>
              <div className="self-center">
                <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded-full border", TIER_BADGE[row.tier] ?? TIER_BADGE.T0)}>
                  {row.tier}
                </span>
              </div>
              <span className="font-mono-t text-xs tabular-nums text-t-muted self-center">
                ${row.starting_capital >= 1000 ? `${(row.starting_capital / 1000).toFixed(0)}k` : row.starting_capital.toFixed(0)}
              </span>
              <span className="font-mono-t text-xs tabular-nums text-t-hi self-center">
                ${row.current_equity >= 1000 ? `${(row.current_equity / 1000).toFixed(1)}k` : row.current_equity.toFixed(0)}
              </span>
              <span className={cn("font-mono-t text-sm font-bold tabular-nums self-center", isUp ? "text-t-green" : "text-t-red")}>
                {isUp ? "+" : ""}{row.all_time_pnl_pct.toFixed(2)}%
              </span>
              <span className={cn("font-mono-t text-xs tabular-nums self-center", row.sharpe_30d == null ? "text-t-gdim" : row.sharpe_30d >= 0 ? "text-t-mid2" : "text-t-red")}>
                {row.sharpe_30d != null ? row.sharpe_30d.toFixed(2) : "—"}
              </span>
              <span className={cn("font-mono-t text-xs tabular-nums self-center", row.win_rate == null ? "text-t-gdim" : row.win_rate >= 0.5 ? "text-t-green" : "text-t-muted")}>
                {row.win_rate != null ? `${(row.win_rate * 100).toFixed(0)}%` : "—"}
              </span>
              <span className="font-mono-t text-xs tabular-nums text-t-muted self-center">{row.trades_count.toLocaleString()}</span>
              <span className="font-mono-t text-xs tabular-nums text-t-gdim self-center">{row.days_live}d</span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

interface IcSnapshot {
  strategy_name: string;
  ic_63d: number | null;
  classification: string | null;
  recommendation: string | null;
  n_signals: number;
}

export default function StrategyLeaderboardPage() {
  const [tab, setTab] = useState<"bots" | "strategies">("bots");
  const [period, setPeriod] = useState<Period>("30d");
  const [category, setCategory] = useState("All");
  const [sort, setSort] = useState<StratSort>("pnl");
  const [botSort, setBotSort] = useState<BotLbSort>("pnl");
  const [selected, setSelected] = useState<StrategyLeaderboardRow | null>(null);

  const { data: icData } = useQuery({
    queryKey: ["ic-strategies"],
    queryFn: async () => {
      try {
        const r = await fetch("/api/ic/strategies", { headers: { Authorization: `Bearer ${localStorage.getItem("bmg_token")}` } });
        if (!r.ok) return [] as IcSnapshot[];
        const json = await r.json();
        return (json as IcSnapshot[]);
      } catch { return [] as IcSnapshot[]; }
    },
    staleTime: 60_000,
  });
  const icMap = Object.fromEntries((icData ?? []).map((s) => [s.strategy_name, s]));

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

  return (
    <div className="min-h-screen bg-t-bg0 text-t-hi animate-page-in">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8 space-y-6">

        {/* ── Header ──────────────────────────────────────────────────────── */}
        <div className="flex items-start justify-between flex-wrap gap-3">
          <div>
            <SectionLabel as="h1" className="text-base mb-1">
              // STRATEGY LEADERBOARD
            </SectionLabel>
            <p className="text-sm text-t-muted">
              {tab === "bots"
                ? "Per-bot all-time P&L ranking."
                : "Dollar-weighted performance across every strategy in every bot."}
            </p>
          </div>
          <div className="flex items-center gap-1">
            <PillButton active={tab === "bots"} onClick={() => setTab("bots")}>Bots</PillButton>
            <PillButton active={tab === "strategies"} onClick={() => setTab("strategies")}>Strategies</PillButton>
          </div>
        </div>

        {/* ── KPI Cards (strategy-attribution only — hidden when flag off) ── */}
        {tab === "strategies" && (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {isLoading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="bg-t-bg1 border border-t-dim rounded-2xl px-4 py-3 h-20 animate-pulse"
                />
              ))
            ) : isError || !kpi ? (
              Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="bg-t-bg1 border border-t-dim rounded-2xl px-4 py-3 h-20 flex items-center justify-center">
                  <span className="text-t-gdim font-mono-t text-xs">—</span>
                </div>
              ))
            ) : (
              <>
                <KpiCard
                  label="Best $ P&L"
                  name={kpi.bestPnl.strategy_name}
                  value={fmtUsd(kpi.bestPnl.total_pnl_usd)}
                  valueClass="text-t-green"
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
                  valueClass="text-t-red"
                />
                <KpiCard
                  label="Most Deployed"
                  name={kpi.mostDeployed.strategy_name}
                  value={`${kpi.mostDeployed.bots_using} bots`}
                  valueClass="text-t-dim"
                />
              </>
            )}
          </div>
        )}

        {/* ── Bot Leaderboard (primary tab) ─────────────────────────────── */}
        {tab === "bots" && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-t-gdim font-mono-t uppercase tracking-widest">Sort by</span>
              {BOT_LB_SORTS.map((s) => (
                <PillButton key={s.value} active={botSort === s.value} onClick={() => setBotSort(s.value)}>
                  {s.label}
                </PillButton>
              ))}
            </div>
            <BotLeaderboardTable sort={botSort} />
          </>
        )}

        {/* ── Strategy attribution tab ─────────────────────────────────── */}
        {tab === "strategies" && (<>
        <div className="flex flex-wrap items-center gap-2">
          {/* Period */}
          <div className="flex items-center gap-1">
            {PERIODS.map((p) => (
              <PillButton key={p.value} active={period === p.value} onClick={() => setPeriod(p.value)}>
                {p.label}
              </PillButton>
            ))}
          </div>

          <div className="w-px h-6 bg-t-dim hidden sm:block" />

          {/* Category */}
          <div className="flex items-center gap-1 flex-wrap">
            {CATEGORIES.map((c) => (
              <PillButton key={c} active={category === c} onClick={() => setCategory(c)}>
                {c}
              </PillButton>
            ))}
          </div>

          <div className="w-px h-6 bg-t-dim hidden sm:block" />

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
          <div className="bg-t-bg1 border border-t-dim rounded-2xl overflow-hidden">
            <SkeletonRows />
          </div>
        ) : isError ? (
          <div className="bg-t-bg1 border border-t-dim rounded-2xl px-5 py-12 text-center">
            <SectionLabel as="p" className="mb-2 text-t-gdim">// Strategy Attribution</SectionLabel>
            <p className="text-t-hi font-semibold mb-1">No strategy data yet</p>
            <p className="text-t-muted text-sm">
              Strategy attribution populates after the first nightly rollup (2am ET) once bots are active.
            </p>
          </div>
        ) : rows.length === 0 ? (
          <div className="bg-t-bg1 border border-t-dim rounded-2xl px-5 py-12 text-center">
            <SectionLabel as="p" className="mb-2 text-t-gdim">// No Data</SectionLabel>
            <p className="text-t-hi font-semibold mb-1">No strategy data yet</p>
            <p className="text-t-muted text-sm">Strategies from active bots will appear here.</p>
          </div>
        ) : (
          <div className="bg-t-bg1 border border-t-dim rounded-2xl overflow-hidden">
            {/* Column headers */}
            <div className="grid grid-cols-[40px_1fr_120px_110px_100px_90px_90px_70px_60px] gap-2 px-4 py-2 border-b border-t-dim">
              {["Rank", "Strategy", "Category", "$ P&L", "Return %", "Win Rate", "IC (63d)", "Trades", "Bots"].map((h) => (
                <span key={h} className="text-[10px] uppercase tracking-widest text-t-gdim font-mono-t">
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
                  className="w-full text-left grid grid-cols-[40px_1fr_120px_110px_100px_90px_90px_70px_60px] gap-2 px-4 py-3 border-b border-t-dim/50 last:border-b-0 hover:bg-t-bg2/40 cursor-pointer transition-colors duration-100 card-hover"
                >
                  {/* Rank */}
                  <span className="font-mono-t text-sm text-t-muted tabular-nums self-center">
                    {idx + 1}
                  </span>

                  {/* Strategy */}
                  <div className="min-w-0 self-center">
                    <p className="text-t-hi font-semibold text-sm truncate leading-tight">
                      {row.strategy_name}
                    </p>
                  </div>

                  {/* Category */}
                  <div className="self-center">
                    {row.category ? (
                      <span className="font-mono-t text-[10px] uppercase tracking-widest px-2 py-0.5 rounded bg-t-bg2 text-t-muted border border-t-mid whitespace-nowrap">
                        {row.category}
                      </span>
                    ) : (
                      <span className="text-t-gdim text-xs">—</span>
                    )}
                  </div>

                  {/* $ P&L */}
                  <span
                    className={cn(
                      "font-mono-t text-sm tabular-nums self-center",
                      usdColor(row.total_pnl_usd)
                    )}
                  >
                    {fmtUsd(row.total_pnl_usd)}
                  </span>

                  {/* Return % */}
                  <span
                    className={cn(
                      "font-mono-t text-sm tabular-nums self-center",
                      pctColor(row.weighted_return_pct)
                    )}
                  >
                    {fmtPct(row.weighted_return_pct)}
                  </span>

                  {/* Win Rate */}
                  <span
                    className={cn(
                      "font-mono-t text-sm tabular-nums self-center",
                      pctColor(row.win_rate)
                    )}
                  >
                    {row.win_rate != null
                      ? `${(row.win_rate * 100).toFixed(1)}%`
                      : "—"}
                  </span>

                  {/* IC (63d) */}
                  <div className="self-center">
                    {(() => {
                      const ic = icMap[row.strategy_id ?? row.strategy_name ?? ""];
                      if (!ic || ic.ic_63d == null) return <span className="text-[10px] text-zinc-600">—</span>;
                      const cls = ic.classification ?? "INSUFFICIENT";
                      const color = cls === "STRONG" ? "text-emerald-400 bg-emerald-900/30" :
                                    cls === "MARGINAL" ? "text-amber-400 bg-amber-900/30" :
                                    cls === "NOISE" ? "text-rose-400 bg-rose-900/30" :
                                    cls === "INVERTED" ? "text-purple-400 bg-purple-900/30" :
                                    "text-zinc-500 bg-zinc-800/40";
                      return (
                        <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold ${color}`}>
                          {ic.ic_63d > 0 ? "+" : ""}{(ic.ic_63d * 100).toFixed(1)}%
                        </span>
                      );
                    })()}
                  </div>

                  {/* Trades */}
                  <span className="font-mono-t text-sm tabular-nums text-t-mid2 self-center">
                    {row.total_trades.toLocaleString()}
                  </span>

                  {/* Bots */}
                  <span className="font-mono-t text-sm tabular-nums text-t-muted self-center">
                    {row.bots_using}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
        </>)} {/* end strategies tab */}
      </div>

      {/* ── Detail Modal ──────────────────────────────────────────────────── */}
      {selected && (
        <StrategyDetailModal row={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

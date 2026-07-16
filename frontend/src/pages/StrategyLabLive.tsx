import { useState, useEffect, useRef, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createChart, LineSeries, ColorType } from "lightweight-charts";
import type { IChartApi, UTCTimestamp } from "lightweight-charts";
import client from "@/api/client";
import {
  getBots,
  getStrategyLabPortfolio,
  type BotListItem,
  type PortfolioData,
} from "@/api/bots";

type Window = "1D" | "1W" | "1M" | "3M" | "YTD" | "ALL";
type ChartView = "Value" | "P&L";
type StatusBadge = "PROVEN" | "PROVING" | "FAILING" | "IDLE";
type SilentReason = "NO SIGNALS" | "PERSIST-DROPPED" | "ALL REJECTED" | "DISABLED" | "AWAITING REBALANCE" | null;

interface NavEntry {
  date: string;
  // Backend `get_nav_history` returns `nav_cents`; older callers used
  // `value_cents`. Accept either so this survives a rename.
  nav_cents?: number;
  value_cents?: number;
  pct_change?: number;
}

interface InertBotRow {
  bot_id: string;
  scanner_ran_24h: boolean;
  scanner_last_run_at: string | null;
  signals_produced_24h: number;
  signals_blocked_by_confidence: number;
  signals_blocked_by_cooldown: number;
  signals_blocked_by_discipline_gate: number;
  signals_blocked_by_sleeve_cap: number;
  orders_attempted_24h: number;
  orders_rejected_24h: number;
  verdict: string;
  enabled: boolean;
}

const WINDOW_DAYS: Record<Window, number> = {
  "1D": 1,
  "1W": 7,
  "1M": 30,
  "3M": 90,
  "YTD": 365,
  "ALL": 3650,
};

// 2026-07-16 cost cut: 15s → 60s. Strategy Lab is a browse page, not a
// live-trading terminal — no need to hammer the backend every 15 seconds.
const POLL_MS = 60_000;

function fmtDollars(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}
function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}
function fmtSigned(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${fmtDollars(v, 2)}`;
}
function fmtClock(d: Date | null): string {
  if (!d) return "—";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function computeStatus(bot: BotListItem): { status: StatusBadge; criteria: string } {
  const trades = bot.stats.total_trades ?? 0;
  const sharpe = bot.stats.sharpe_30d ?? null;
  const win = bot.stats.win_rate_pct ?? 0;
  const parts: string[] = [
    `trades ${trades}/50`,
    `sharpe ${sharpe !== null ? sharpe.toFixed(2) : "—"}/1.0`,
    `win ${win.toFixed(0)}%/55%`,
  ];
  if (trades === 0) return { status: "IDLE", criteria: parts.join(" · ") };
  if (trades >= 50 && sharpe !== null && sharpe > 1.0 && win > 55) {
    return { status: "PROVEN", criteria: parts.join(" · ") };
  }
  if (trades >= 50 && (sharpe !== null && sharpe < 0 || win < 40)) {
    return { status: "FAILING", criteria: parts.join(" · ") };
  }
  return { status: "PROVING", criteria: parts.join(" · ") };
}

function computeSilentReason(bot: BotListItem, inert: InertBotRow | undefined): SilentReason {
  if (bot.allocation && bot.allocation.enabled === false) return "DISABLED";
  if (!inert) return null;
  const sig = inert.signals_produced_24h ?? 0;
  const blocked =
    (inert.signals_blocked_by_confidence ?? 0) +
    (inert.signals_blocked_by_cooldown ?? 0) +
    (inert.signals_blocked_by_discipline_gate ?? 0) +
    (inert.signals_blocked_by_sleeve_cap ?? 0);
  if (!inert.enabled) return "DISABLED";
  if (sig === 0 && blocked === 0) return "NO SIGNALS";
  if (inert.orders_attempted_24h > 0 && inert.orders_rejected_24h === inert.orders_attempted_24h) {
    return "ALL REJECTED";
  }
  if (sig === 0 && blocked > 0) return "PERSIST-DROPPED";
  return null;
}

const STATUS_COLORS: Record<StatusBadge, string> = {
  PROVEN: "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40",
  PROVING: "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40",
  FAILING: "bg-red-500/20 text-red-300 border border-red-500/40",
  IDLE: "bg-slate-500/20 text-slate-300 border border-slate-500/40",
};

const SILENT_COLORS: Record<NonNullable<SilentReason>, string> = {
  "NO SIGNALS": "bg-slate-800 text-slate-300 border border-slate-700",
  "PERSIST-DROPPED": "bg-amber-900/40 text-amber-300 border border-amber-700/60",
  "ALL REJECTED": "bg-red-900/40 text-red-300 border border-red-700/60",
  "DISABLED": "bg-slate-700 text-slate-400 border border-slate-600",
  "AWAITING REBALANCE": "bg-purple-900/40 text-purple-300 border border-purple-700/60",
};

export default function StrategyLabLive() {
  const [window, setWindow] = useState<Window>("1M");
  const [chartView, setChartView] = useState<ChartView>("Value");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<
    "sharpe_30d" | "return_30d_pct" | "total_trades" | "win_rate_pct" | "all_time_pnl_usd" | "starting_capital_usd" | "deployed_cents"
  >("sharpe_30d");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [lastSynced, setLastSynced] = useState<Date | null>(null);
  const [connState, setConnState] = useState<"live" | "amber">("live");

  // ── Data fetching ─────────────────────────────────────────────────────────
  const portfolioQuery = useQuery({
    queryKey: ["strategy-lab-live", "portfolio"],
    queryFn: getStrategyLabPortfolio,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });
  const botsQuery = useQuery({
    queryKey: ["strategy-lab-live", "bots"],
    queryFn: getBots,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });
  const navQuery = useQuery({
    queryKey: ["strategy-lab-live", "nav-history", window],
    queryFn: async (): Promise<NavEntry[]> => {
      const days = WINDOW_DAYS[window];
      const res = await client.get<{ entries: NavEntry[] }>(
        `/bots/portfolio/nav-history`,
        { params: { days } },
      );
      return res.data.entries ?? [];
    },
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });
  const inertQuery = useQuery({
    queryKey: ["strategy-lab-live", "inert"],
    queryFn: async (): Promise<{ inert_bots: InertBotRow[] }> => {
      const res = await client.get<{ inert_bots: InertBotRow[] }>(
        `/admin/inert-bot-scan`,
      );
      return res.data;
    },
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
    // If the user isn't admin, this 401s and we just render without why-silent chips.
    retry: false,
  });

  // Track fetch success/failure to drive live/amber dot.
  useEffect(() => {
    const anyErr =
      portfolioQuery.isError || botsQuery.isError || navQuery.isError;
    const anyOk =
      portfolioQuery.isSuccess && botsQuery.isSuccess && navQuery.isSuccess;
    if (anyOk) {
      setConnState("live");
      setLastSynced(new Date());
    } else if (anyErr) {
      setConnState("amber");
    }
  }, [
    portfolioQuery.status,
    botsQuery.status,
    navQuery.status,
    portfolioQuery.dataUpdatedAt,
    botsQuery.dataUpdatedAt,
    navQuery.dataUpdatedAt,
  ]);

  const portfolio: PortfolioData | undefined = portfolioQuery.data;
  const bots: BotListItem[] = botsQuery.data?.bots ?? [];
  const navEntries: NavEntry[] = navQuery.data ?? portfolio?.equity_curve ?? [];
  const inertByBot = useMemo(() => {
    const map: Record<string, InertBotRow> = {};
    for (const r of inertQuery.data?.inert_bots ?? []) {
      map[r.bot_id] = r;
    }
    return map;
  }, [inertQuery.data]);

  // ── Hero chart wiring ─────────────────────────────────────────────────────
  const chartHostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<any>(null);

  useEffect(() => {
    if (!chartHostRef.current) return;
    const chart = createChart(chartHostRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#94a3b8",
        fontFamily: "ui-monospace, SFMono-Regular, monospace",
      },
      grid: {
        vertLines: { color: "rgba(148, 163, 184, 0.08)" },
        horzLines: { color: "rgba(148, 163, 184, 0.08)" },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      autoSize: true,
      handleScroll: false,
      handleScale: false,
    });
    const series = chart.addSeries(LineSeries, {
      color: "#34d399",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chartRef.current = chart;
    seriesRef.current = series;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || navEntries.length === 0) return;
    const getCents = (e: NavEntry): number => (e.nav_cents ?? e.value_cents ?? 0);
    const openCents = getCents(navEntries[0]);
    const points = navEntries
      .map((e) => {
        const t = Math.floor(new Date(e.date).getTime() / 1000) as UTCTimestamp;
        const raw = getCents(e) / 100;
        const v = chartView === "P&L" ? raw - openCents / 100 : raw;
        return { time: t, value: v };
      })
      .filter((p) => Number.isFinite(p.value) && p.value !== 0)
      .sort((a, b) => (a.time as number) - (b.time as number));
    seriesRef.current.setData(points);
    seriesRef.current.applyOptions({
      color: chartView === "P&L" && points.length > 0 && points[points.length - 1].value < 0
        ? "#f87171"
        : "#34d399",
    });
  }, [navEntries, chartView]);

  // ── Leaderboard sort/filter (state preserved across polls) ────────────────
  const filteredSortedBots = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = bots.filter((b) => {
      if (!q) return true;
      const name = (b.profile?.name ?? "").toLowerCase();
      return name.includes(q);
    });
    // Edge / trade sort: prefer 30d Sharpe when available, else expectancy $/trade.
    // Keeps sorting monotonic across bots at different maturity.
    const edgeScore = (s: BotListItem["stats"]): number => {
      if (s.sharpe_30d !== null && s.sharpe_30d !== undefined) return s.sharpe_30d;
      if ((s.total_trades ?? 0) > 0 && s.all_time_pnl_usd !== null && s.all_time_pnl_usd !== undefined) {
        return s.all_time_pnl_usd / (s.total_trades as number);
      }
      return -Infinity;
    };
    const dir = sortDir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const av =
        sortKey === "starting_capital_usd"
          ? a.stats.starting_capital_usd
          : sortKey === "deployed_cents"
          ? (a.stats.deployed_cents ?? 0) / 100
          : sortKey === "sharpe_30d"
          ? edgeScore(a.stats)
          : sortKey === "all_time_pnl_usd"
          ? a.stats.all_time_pnl_usd
          : (a.stats as any)[sortKey];
      const bv =
        sortKey === "starting_capital_usd"
          ? b.stats.starting_capital_usd
          : sortKey === "deployed_cents"
          ? (b.stats.deployed_cents ?? 0) / 100
          : sortKey === "sharpe_30d"
          ? edgeScore(b.stats)
          : sortKey === "all_time_pnl_usd"
          ? b.stats.all_time_pnl_usd
          : (b.stats as any)[sortKey];
      const an = av ?? -Infinity;
      const bn = bv ?? -Infinity;
      if (an === bn) return 0;
      return an < bn ? -dir : dir;
    });
  }, [bots, search, sortKey, sortDir]);

  // ── Idle capital ──────────────────────────────────────────────────────────
  const { totalAllocated, totalDeployed } = useMemo(() => {
    let a = 0;
    let d = 0;
    for (const b of bots) {
      a += (b.stats.starting_capital_cents ?? 0);
      d += (b.stats.deployed_cents ?? 0);
    }
    return { totalAllocated: a / 100, totalDeployed: d / 100 };
  }, [bots]);
  const idleCapital = Math.max(0, totalAllocated - totalDeployed);

  // ── Period tiles ──────────────────────────────────────────────────────────
  const pnl = portfolio?.pnl;
  const tiles: Array<{ label: string; window: string; usd: number | null; pct: number | null }> = [
    {
      label: "All-Time",
      window: "since inception",
      usd: pnl?.all_time?.cents !== undefined ? pnl.all_time.cents / 100 : null,
      pct: pnl?.all_time?.pct !== undefined ? pnl.all_time.pct * 100 : null,
    },
    {
      label: "Month-to-Date",
      window: "since 1st of month",
      usd: pnl?.mtd?.cents !== undefined ? pnl.mtd.cents / 100 : null,
      pct: pnl?.mtd?.pct !== undefined ? pnl.mtd.pct * 100 : null,
    },
    {
      label: "Week-to-Date",
      window: "since Sunday",
      usd: pnl?.wtd?.cents !== undefined ? pnl.wtd.cents / 100 : null,
      pct: pnl?.wtd?.pct !== undefined ? pnl.wtd.pct * 100 : null,
    },
    {
      label: "Today",
      window: "since prior close",
      usd: pnl?.today?.cents !== undefined ? pnl.today.cents / 100 : null,
      pct: pnl?.today?.pct !== undefined ? pnl.today.pct * 100 : null,
    },
  ];

  const nav = portfolio?.total_value_cents !== undefined ? portfolio.total_value_cents / 100 : null;
  const todayPnl = portfolio?.today_pnl_cents !== undefined ? portfolio.today_pnl_cents / 100 : null;
  const todayPct = portfolio?.today_pnl_pct ?? null;

  // ── Column sort helper ────────────────────────────────────────────────────
  const th = (label: string, key: typeof sortKey) => {
    const active = sortKey === key;
    return (
      <button
        onClick={() => {
          if (active) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
          else {
            setSortKey(key);
            setSortDir("desc");
          }
        }}
        className={`text-left text-xs uppercase tracking-wider px-3 py-2 hover:text-emerald-300 ${
          active ? "text-emerald-400" : "text-slate-400"
        }`}
      >
        {label} {active ? (sortDir === "asc" ? "▲" : "▼") : ""}
      </button>
    );
  };

  return (
    <div className="min-h-screen bg-[#040804] text-slate-200 p-6">
      {/* Header row: title + sync indicator */}
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-2xl font-mono tracking-wider text-emerald-400">STRATEGY LAB</h1>
          <p className="text-xs text-slate-500 mt-1">
            live-wired · every number bound to canonical
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              connState === "live" ? "bg-emerald-400 animate-pulse" : "bg-amber-400"
            }`}
          />
          <span className="text-slate-500">last synced {fmtClock(lastSynced)}</span>
        </div>
      </div>

      {/* Hero portfolio value */}
      <div className="mb-6 border border-emerald-500/20 rounded-lg p-6 bg-emerald-950/10">
        <div className="text-xs uppercase tracking-widest text-emerald-400/80 mb-2">Fund NAV · updates live</div>
        <div className="text-5xl font-mono text-emerald-300 tabular-nums">
          {fmtDollars(nav, 2)}
        </div>
        <div className="mt-2 text-sm">
          Today:{" "}
          <span className={todayPnl && todayPnl >= 0 ? "text-emerald-400" : "text-red-400"}>
            {fmtSigned(todayPnl)} ({fmtPct(todayPct, 2)})
          </span>
        </div>
      </div>

      {/* Period P&L tiles */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-6">
        {tiles.map((t) => {
          const positive = (t.usd ?? 0) >= 0;
          return (
            <div
              key={t.label}
              className={`border rounded-lg p-4 ${
                positive ? "border-emerald-500/30 bg-emerald-950/10" : "border-red-500/30 bg-red-950/10"
              }`}
            >
              <div className="text-xs text-slate-400 uppercase tracking-wide">{t.label}</div>
              <div className="text-[10px] text-slate-500 mb-2">{t.window}</div>
              <div className={`text-2xl font-mono tabular-nums ${positive ? "text-emerald-300" : "text-red-300"}`}>
                {fmtSigned(t.usd)}
              </div>
              <div className={`text-sm font-mono tabular-nums ${positive ? "text-emerald-400/80" : "text-red-400/80"}`}>
                {fmtPct(t.pct, 2)}
              </div>
            </div>
          );
        })}
      </div>

      {/* Chart controls + host */}
      <div className="mb-6 border border-slate-800 rounded-lg p-4 bg-slate-950/40">
        <div className="flex items-center justify-between mb-3">
          <div className="flex gap-1">
            {(["1D", "1W", "1M", "3M", "YTD", "ALL"] as Window[]).map((w) => (
              <button
                key={w}
                onClick={() => setWindow(w)}
                className={`px-3 py-1 text-xs font-mono rounded ${
                  window === w
                    ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                    : "text-slate-400 border border-transparent hover:border-slate-700"
                }`}
              >
                {w}
              </button>
            ))}
          </div>
          <div className="flex gap-1">
            {(["Value", "P&L"] as ChartView[]).map((v) => (
              <button
                key={v}
                onClick={() => setChartView(v)}
                className={`px-3 py-1 text-xs font-mono rounded ${
                  chartView === v
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                    : "text-slate-400 border border-transparent hover:border-slate-700"
                }`}
              >
                {v}
              </button>
            ))}
          </div>
        </div>
        <div ref={chartHostRef} className="h-72 w-full" />
      </div>

      {/* Utilization strip */}
      <div className="mb-6 border border-slate-800 rounded-lg p-4 bg-slate-950/40">
        <div className="flex items-baseline justify-between mb-2">
          <div className="text-xs uppercase tracking-widest text-slate-400">
            Fleet Utilization
          </div>
          <div className="text-xs text-slate-500 font-mono">
            {fmtDollars(totalDeployed, 0)} / {fmtDollars(totalAllocated, 0)} deployed ·{" "}
            <span className="text-amber-400">{fmtDollars(idleCapital, 0)} idle</span>
          </div>
        </div>
        <div className="h-2 w-full bg-slate-800 rounded overflow-hidden">
          <div
            className="h-full bg-emerald-500"
            style={{
              width: `${
                totalAllocated > 0 ? Math.min(100, (totalDeployed / totalAllocated) * 100) : 0
              }%`,
            }}
          />
        </div>
      </div>

      {/* Leaderboard */}
      <div className="border border-slate-800 rounded-lg bg-slate-950/40">
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <div>
            <div className="text-xs uppercase tracking-widest text-slate-400">Leaderboard</div>
            <div className="text-xs text-slate-500 mt-1">
              {filteredSortedBots.length} bot{filteredSortedBots.length === 1 ? "" : "s"}
              {portfolio?.leaderboard && (
                <span className="ml-2 text-slate-600">
                  (agg reports {portfolio.leaderboard.length})
                </span>
              )}
            </div>
          </div>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="filter by name"
            className="bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-emerald-500/50 w-64"
          />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/40">
              <tr>
                <th className="text-left text-xs uppercase tracking-wider px-3 py-2 text-slate-400">Bot</th>
                <th className="text-left text-xs uppercase tracking-wider px-3 py-2 text-slate-400">Status</th>
                <th className="text-left text-xs uppercase tracking-wider px-3 py-2 text-slate-400">Silent?</th>
                <th>{th("Trades", "total_trades")}</th>
                <th>{th("Win %", "win_rate_pct")}</th>
                <th>{th("Edge / trade", "sharpe_30d")}</th>
                <th>{th("30d %", "return_30d_pct")}</th>
                <th>{th("All-Time $", "all_time_pnl_usd")}</th>
                <th>{th("Allocated", "starting_capital_usd")}</th>
                <th>{th("Deployed", "deployed_cents")}</th>
                <th className="text-left text-xs uppercase tracking-wider px-3 py-2 text-slate-400">Util</th>
              </tr>
            </thead>
            <tbody>
              {filteredSortedBots.map((b) => {
                const { status, criteria } = computeStatus(b);
                const silent = computeSilentReason(b, inertByBot[b.profile.name]);
                const allocatedUsd = b.stats.starting_capital_usd ?? 0;
                const deployedUsd = (b.stats.deployed_cents ?? 0) / 100;
                const utilPct = allocatedUsd > 0 ? Math.min(100, (deployedUsd / allocatedUsd) * 100) : 0;
                const trades = b.stats.total_trades ?? 0;
                const winPct = b.stats.win_rate_pct ?? 0;
                const sharpe = b.stats.sharpe_30d;
                const r30 = b.stats.return_30d_pct;
                const atUsd = b.stats.all_time_pnl_usd;
                const atPct = b.stats.all_time_pnl_pct;
                return (
                  <tr key={b.profile.name} className="border-t border-slate-900 hover:bg-slate-900/40">
                    <td className="px-3 py-2 font-mono text-xs">
                      <div className="text-slate-200">{b.profile.name}</div>
                      <div className="text-slate-500 text-[10px]">{b.profile.asset_class}</div>
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`inline-block px-2 py-0.5 text-[10px] font-mono rounded ${STATUS_COLORS[status]}`}
                        title={criteria}
                      >
                        {status}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {silent ? (
                        <span
                          className={`inline-block px-2 py-0.5 text-[10px] font-mono rounded ${SILENT_COLORS[silent]}`}
                        >
                          {silent}
                        </span>
                      ) : (
                        <span className="text-slate-600 text-xs">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums text-slate-300">{trades}</td>
                    <td className="px-3 py-2 font-mono tabular-nums text-slate-300">
                      {trades === 0 ? "—" : `${winPct.toFixed(0)}%`}
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums">
                      {sharpe !== null && sharpe !== undefined ? (
                        <span
                          className={sharpe > 1.0 ? "text-emerald-400" : sharpe < 0 ? "text-red-400" : "text-slate-300"}
                          title={`30d annualized Sharpe · needs >1.0 for PROVEN`}
                        >
                          {sharpe.toFixed(2)}
                          <span className="text-slate-500 text-[10px] ml-1">σ30d</span>
                        </span>
                      ) : trades > 0 && atUsd !== null && atUsd !== undefined ? (
                        <span
                          className={atUsd >= 0 ? "text-emerald-400" : "text-red-400"}
                          title={`Expectancy = all-time P&L / closed trades. Shown while daily-Sharpe window is short.`}
                        >
                          {fmtSigned(atUsd / trades)}
                          <span className="text-slate-500 text-[10px] ml-1">
                            /trade ({trades})
                          </span>
                        </span>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums">
                      <span className={r30 >= 0 ? "text-emerald-400" : "text-red-400"}>
                        {fmtPct(r30, 2)}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums">
                      {atUsd === null || atUsd === undefined ? (
                        <span className="text-slate-600">—</span>
                      ) : (
                        <span className={atUsd >= 0 ? "text-emerald-400" : "text-red-400"}>
                          {fmtSigned(atUsd)}
                          {atPct !== null && atPct !== undefined && (
                            <span className="text-slate-500 ml-1">({fmtPct(atPct, 1)})</span>
                          )}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums text-slate-300">
                      {fmtDollars(allocatedUsd, 0)}
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums text-slate-300">
                      {fmtDollars(deployedUsd, 0)}
                    </td>
                    <td className="px-3 py-2 min-w-[80px]">
                      <div className="h-1.5 w-full bg-slate-800 rounded overflow-hidden">
                        <div
                          className={`h-full ${utilPct > 90 ? "bg-red-500" : utilPct > 60 ? "bg-emerald-500" : "bg-cyan-500"}`}
                          style={{ width: `${utilPct}%` }}
                        />
                      </div>
                      <div className="text-[10px] text-slate-500 mt-0.5 tabular-nums">
                        {utilPct.toFixed(0)}%
                      </div>
                    </td>
                  </tr>
                );
              })}
              {filteredSortedBots.length === 0 && (
                <tr>
                  <td colSpan={11} className="text-center text-slate-500 py-8">
                    no bots match your filter
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="text-[10px] text-slate-600 text-center mt-6 font-mono">
        polling every {POLL_MS / 1000}s · sort/filter preserved across refreshes
      </div>
    </div>
  );
}

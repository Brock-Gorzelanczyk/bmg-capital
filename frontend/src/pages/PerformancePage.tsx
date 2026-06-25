import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { BracketFrame, SectionLabel, BMGButton } from "@/components/design";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine, Cell,
} from "recharts";
import {
  getPortfolioPerformance, getBotLeaderboard, getBotPerformance,
  getBotEquityCurve, getBotMonthlyReturns, getBotStrategyAttribution,
  getBotSymbolAttribution, getBotTimeOfDay,
  type Period, type LeaderboardMetric, type StrategyRow,
} from "@/api/performance";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt$(v: number | null | undefined, decimals = 0): string {
  if (v == null) return "—";
  const abs = Math.abs(v);
  const s = abs >= 1_000_000
    ? `$${(abs / 1_000_000).toFixed(2)}M`
    : abs >= 1_000
    ? `$${(abs / 1_000).toFixed(1)}k`
    : `$${abs.toFixed(decimals)}`;
  return v < 0 ? `-${s}` : `+${s}`;
}

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return v.toFixed(digits);
}

function pColor(v: number | null | undefined): string {
  if (v == null) return "text-zinc-400";
  return v >= 0 ? "text-emerald-400" : "text-red-400";
}

const BOT_DISPLAY: Record<string, string> = {
  stock_swing: "Stock Swing",
  stock_day: "Stock Day",
  stock_lt: "Stock LT",
  crypto_swing: "Crypto Swing",
  crypto_day: "Crypto Day",
  crypto_lt: "Crypto LT",
  crypto_quant_aggressive: "Quant Aggressive",
  crypto_quant_scalper: "Quant Scalper",
  crypto_quant_mean_reversion: "Quant MR",
  options_income: "Options Income",
  options_directional: "Options Directional",
};

const PERIODS: Period[] = ["7d", "30d", "90d", "all"];

// ── KPI card ──────────────────────────────────────────────────────────────────

function KpiCard({
  label, value, sub, valueClass,
}: { label: string; value: string; sub?: string; valueClass?: string }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-4 py-3 flex-1 min-w-0">
      <p className="text-[10px] font-semibold text-zinc-600 uppercase tracking-widest mb-1">{label}</p>
      <p className={cn("text-2xl font-bold font-mono", valueClass ?? "text-white")}>{value}</p>
      {sub && <p className="text-xs text-zinc-500 mt-0.5 font-mono">{sub}</p>}
    </div>
  );
}

// ── Equity curve chart ─────────────────────────────────────────────────────────

function EquityCurve({ curve }: { curve: Array<{ date: string; equity_usd: number; drawdown_pct: number }> }) {
  if (!curve.length) return (
    <div className="h-48 flex items-center justify-center text-zinc-600 text-sm">No equity data</div>
  );
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={curve} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#52525b" }} tickLine={false} axisLine={false}
          tickFormatter={(d) => d.slice(5)} interval="preserveStartEnd" />
        <YAxis tick={{ fontSize: 9, fill: "#52525b" }} tickLine={false} axisLine={false}
          tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} width={44} />
        <Tooltip
          contentStyle={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, fontSize: 11 }}
          formatter={(v: number) => [`$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`, "Equity"]}
        />
        <Line type="monotone" dataKey="equity_usd" stroke="#34d399" strokeWidth={1.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── Monthly returns heatmap ────────────────────────────────────────────────────

const MONTH_LABELS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function MonthlyHeatmap({ monthly }: { monthly: Array<{ year: number; month: number; return_pct: number }> }) {
  if (!monthly.length) return null;
  const years = [...new Set(monthly.map((r) => r.year))].sort();
  const byKey = Object.fromEntries(monthly.map((r) => [`${r.year}-${r.month}`, r.return_pct]));

  return (
    <div className="overflow-x-auto">
      <table className="text-[10px] font-mono min-w-max">
        <thead>
          <tr>
            <th className="text-zinc-600 text-left pr-3 pb-1">Year</th>
            {MONTH_LABELS.map((m) => (
              <th key={m} className="text-zinc-600 text-center px-1 pb-1 w-9">{m}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {years.map((yr) => (
            <tr key={yr}>
              <td className="text-zinc-500 pr-3 py-0.5">{yr}</td>
              {MONTH_LABELS.map((_, mi) => {
                const v = byKey[`${yr}-${mi + 1}`];
                const pct = v != null ? v * 100 : null;
                const bg = pct == null
                  ? "bg-zinc-800/30"
                  : pct > 3 ? "bg-emerald-500/40" : pct > 0 ? "bg-emerald-500/15"
                  : pct < -3 ? "bg-red-500/40" : "bg-red-500/15";
                return (
                  <td key={mi} className={cn("text-center px-1 py-0.5 rounded", bg)}>
                    {pct != null ? (
                      <span className={pct >= 0 ? "text-emerald-400" : "text-red-400"}>
                        {pct >= 0 ? "+" : ""}{pct.toFixed(1)}
                      </span>
                    ) : <span className="text-zinc-700">·</span>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Strategy attribution table ─────────────────────────────────────────────────

type AttrSort = "contrib" | "raw_return";
type SortDir = "asc" | "desc";

function AttributionTable({
  rows, totalCapital, sortBy, sortDir, onSort,
}: {
  rows: StrategyRow[];
  totalCapital: number;
  sortBy: AttrSort;
  sortDir: SortDir;
  onSort: (col: AttrSort) => void;
}) {
  if (!rows.length) return <p className="text-zinc-600 text-xs text-center py-6">No strategy data</p>;
  const dirMul = sortDir === "desc" ? 1 : -1;
  const sorted = [...rows].sort((a, b) => {
    if (sortBy === "contrib") return (b.pnl_usd - a.pnl_usd) * dirMul;
    return ((b.raw_return_pct ?? 0) - (a.raw_return_pct ?? 0)) * dirMul;
  });
  const totPnl = rows.reduce((s, r) => s + r.pnl_usd, 0);
  const arrow = sortDir === "desc" ? "▼" : "▲";

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs min-w-max">
        <thead>
          <tr className="border-b border-zinc-800">
            <th className="text-left text-[10px] text-zinc-600 uppercase py-2 pr-4">Strategy</th>
            <th
              className="text-right text-[10px] text-zinc-600 uppercase py-2 px-3 cursor-pointer hover:text-zinc-400 select-none"
              onClick={() => onSort("raw_return")}
            >
              Raw Return% {sortBy === "raw_return" ? arrow : ""}
            </th>
            <th
              className="text-right text-[10px] text-zinc-600 uppercase py-2 px-3 cursor-pointer hover:text-zinc-400 select-none"
              onClick={() => onSort("contrib")}
            >
              $ Contrib {sortBy === "contrib" ? arrow : ""}
            </th>
            <th className="text-right text-[10px] text-zinc-600 uppercase py-2 px-3">Capital</th>
            <th className="text-right text-[10px] text-zinc-600 uppercase py-2 pl-3">Weight</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={row.strategy} className="border-b border-zinc-800/40 hover:bg-zinc-800/20">
              <td className="py-2 pr-4 font-medium text-white">
                {row.strategy?.replace(/_/g, " ") ?? "Unattributed"}
              </td>
              <td className={cn("text-right px-3 font-mono", pColor(row.raw_return_pct))}>
                {fmtPct(row.raw_return_pct)}
              </td>
              <td className={cn("text-right px-3 font-mono", pColor(row.pnl_usd))}>
                {fmt$(row.pnl_usd, 0)}
              </td>
              <td className="text-right px-3 font-mono text-zinc-400">
                ${(row.capital_deployed_usd ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </td>
              <td className="text-right pl-3 font-mono text-zinc-400">
                {row.weight_pct != null ? `${row.weight_pct.toFixed(1)}%` : "—"}
              </td>
            </tr>
          ))}
          <tr className="border-t border-zinc-700">
            <td className="py-2 pr-4 font-bold text-zinc-300 text-[10px] uppercase">BOT TOTAL (weighted)</td>
            <td className="text-right px-3 font-mono text-zinc-300">
              {fmtPct(totalCapital > 0 ? totPnl / totalCapital : null)}
            </td>
            <td className={cn("text-right px-3 font-mono font-bold", pColor(totPnl))}>
              {fmt$(totPnl, 0)}
            </td>
            <td className="text-right px-3 font-mono text-zinc-400">
              ${totalCapital.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </td>
            <td className="text-right pl-3 font-mono text-zinc-400">100%</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// ── Mini strategy leaderboard widget ──────────────────────────────────────────

function MiniLeaderboard({ userId }: { userId?: number }) {
  const { data } = useQuery({
    queryKey: ["strat-lb-mini"],
    queryFn: () => import("@/api/performance").then((m) => m.getStrategyLeaderboard("30d", "pnl")),
    staleTime: 300_000,
    retry: 0,
  });
  const rows = (data?.strategies ?? []).slice(0, 5);
  if (!rows.length) return null;

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
        <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest">
          // TOP 5 STRATEGIES (30d)
        </p>
        <Link to="/strategy/leaderboard" className="text-[10px] text-violet-400 hover:text-violet-300">
          See full leaderboard →
        </Link>
      </div>
      {rows.map((r, i) => (
        <div key={r.strategy_id} className="flex items-center gap-3 px-4 py-2.5 border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/20">
          <span className="text-zinc-600 text-xs w-4">{i + 1}</span>
          <span className="text-white text-xs flex-1 truncate">{r.strategy_name}</span>
          <span className={cn("font-mono text-xs", pColor(r.total_pnl_usd))}>
            {fmt$(r.total_pnl_usd, 0)}
          </span>
          <span className={cn("font-mono text-xs w-14 text-right", pColor(r.weighted_return_pct))}>
            {fmtPct(r.weighted_return_pct)}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Tab: Portfolio ─────────────────────────────────────────────────────────────

function PortfolioTab({ period }: { period: Period }) {
  const { data: metrics, isLoading, isError } = useQuery({
    queryKey: ["perf-portfolio", period],
    queryFn: () => getPortfolioPerformance(period),
    staleTime: 300_000,
    retry: 0,
  });

  const curveDays = period === "7d" ? 7 : period === "30d" ? 30 : period === "90d" ? 90 : 365;
  const { data: curveData } = useQuery({
    queryKey: ["perf-portfolio-curve", curveDays],
    queryFn: () =>
      getBotEquityCurve("crypto_quant_scalper", curveDays).catch(() => ({ curve: [] })),
    staleTime: 3_600_000,
    retry: 0,
    enabled: !isError,
  });

  const { data: monthlyData } = useQuery({
    queryKey: ["perf-portfolio-monthly"],
    queryFn: () =>
      getBotMonthlyReturns("crypto_quant_scalper").catch(() => ({ monthly: [] })),
    staleTime: 3_600_000,
    retry: 0,
    enabled: !isError,
  });

  if (isError) return (
    <BracketFrame className="px-5 py-12 text-center">
      <p className="text-zinc-400 font-semibold mb-1">Performance analytics not enabled</p>
      <p className="text-zinc-600 text-sm">Set ENABLE_PERFORMANCE_ANALYTICS=true to activate.</p>
    </BracketFrame>
  );

  if (isLoading) return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[0,1,2,3].map((i) => <div key={i} className="h-20 bg-zinc-900 border border-zinc-800 rounded-2xl animate-pulse" />)}
      </div>
      <div className="h-52 bg-zinc-900 border border-zinc-800 rounded-2xl animate-pulse" />
    </div>
  );

  return (
    <div className="space-y-5">
      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Total Return" value={fmtPct(metrics?.total_return_pct)}
          sub={fmt$(metrics?.total_return_usd ?? null)} valueClass={pColor(metrics?.total_return_pct)} />
        <KpiCard label="Sharpe" value={fmtNum(metrics?.sharpe)}
          valueClass={metrics?.sharpe != null && metrics.sharpe >= 1 ? "text-emerald-400" : "text-white"} />
        <KpiCard label="Max Drawdown" value={fmtPct(metrics?.max_drawdown_pct)}
          sub={fmt$(metrics?.max_drawdown_usd ?? null)} valueClass="text-red-400" />
        <KpiCard label="Win Rate" value={metrics?.win_rate != null ? `${(metrics.win_rate * 100).toFixed(0)}%` : "—"}
          sub={metrics?.total_trades ? `${metrics.total_trades} trades` : undefined} />
      </div>

      {/* Secondary metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Sortino" value={fmtNum(metrics?.sortino)} />
        <KpiCard label="Profit Factor" value={fmtNum(metrics?.profit_factor)} />
        <KpiCard label="Avg Win" value={fmt$(metrics?.avg_win_usd ?? null)} valueClass="text-emerald-400" />
        <KpiCard label="Avg Loss" value={fmt$(metrics?.avg_loss_usd ?? null)} valueClass="text-red-400" />
      </div>

      {/* Equity curve */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4">
        <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest mb-3">
          // EQUITY CURVE
        </p>
        <EquityCurve curve={curveData?.curve ?? []} />
      </div>

      {/* Monthly heatmap */}
      {monthlyData?.monthly && monthlyData.monthly.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4">
          <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest mb-3">
            // MONTHLY RETURNS
          </p>
          <MonthlyHeatmap monthly={monthlyData.monthly} />
        </div>
      )}

      {/* Mini strategy leaderboard */}
      <MiniLeaderboard />
    </div>
  );
}

// ── Tab: By Bot ────────────────────────────────────────────────────────────────

const ALL_BOTS = Object.keys(BOT_DISPLAY);

function ByBotTab({ period }: { period: Period }) {
  const [selectedBot, setSelectedBot] = useState(ALL_BOTS[6]); // default: crypto_quant_scalper
  const [attrSort, setAttrSort] = useState<AttrSort>("contrib");
  const [attrSortDir, setAttrSortDir] = useState<SortDir>("desc");
  function onAttrSort(col: AttrSort) {
    if (col === attrSort) {
      setAttrSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setAttrSort(col);
      setAttrSortDir("desc");
    }
  }
  const curveDays = period === "7d" ? 7 : period === "30d" ? 30 : period === "90d" ? 90 : 365;

  const { data: metrics, isLoading } = useQuery({
    queryKey: ["perf-bot", selectedBot, period],
    queryFn: () => getBotPerformance(selectedBot, period),
    staleTime: 300_000,
    retry: 0,
  });
  const { data: curveData } = useQuery({
    queryKey: ["perf-bot-curve", selectedBot, curveDays],
    queryFn: () => getBotEquityCurve(selectedBot, curveDays),
    staleTime: 3_600_000,
    retry: 0,
    enabled: !!selectedBot,
  });
  const { data: attrData } = useQuery({
    queryKey: ["perf-bot-attr", selectedBot],
    queryFn: () => getBotStrategyAttribution(selectedBot, "all"),
    staleTime: 300_000,
    retry: 0,
    enabled: !!selectedBot,
  });
  const { data: symData } = useQuery({
    queryKey: ["perf-bot-sym", selectedBot],
    queryFn: () => getBotSymbolAttribution(selectedBot),
    staleTime: 300_000,
    retry: 0,
    enabled: !!selectedBot,
  });
  const { data: todData } = useQuery({
    queryKey: ["perf-bot-tod", selectedBot],
    queryFn: () => getBotTimeOfDay(selectedBot),
    staleTime: 300_000,
    retry: 0,
    enabled: !!selectedBot,
  });

  return (
    <div className="space-y-5">
      {/* Bot selector */}
      <div className="flex flex-wrap gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1 w-fit">
        {ALL_BOTS.map((b) => (
          <button
            key={b}
            onClick={() => setSelectedBot(b)}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors",
              selectedBot === b ? "bg-zinc-700 text-white" : "text-zinc-500 hover:text-zinc-300"
            )}
          >
            {BOT_DISPLAY[b] ?? b}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[0,1,2,3].map((i) => <div key={i} className="h-20 bg-zinc-900 border border-zinc-800 rounded-2xl animate-pulse" />)}
          </div>
        </div>
      ) : metrics?.total_trades === 0 && metrics?.data_days === 0 ? (
        <BracketFrame className="px-5 py-12 text-center">
          <p className="text-zinc-400 font-semibold">Bot hasn't traded yet</p>
          <p className="text-zinc-600 text-sm mt-1">Performance data appears after the first closed trade.</p>
        </BracketFrame>
      ) : (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard label="Total Return" value={fmtPct(metrics?.total_return_pct)}
              sub={fmt$(metrics?.total_return_usd ?? null)} valueClass={pColor(metrics?.total_return_pct)} />
            <KpiCard label="Sharpe" value={fmtNum(metrics?.sharpe)}
              valueClass={metrics?.sharpe != null && metrics.sharpe >= 1 ? "text-emerald-400" : "text-white"} />
            <KpiCard label="Max Drawdown" value={fmtPct(metrics?.max_drawdown_pct)}
              sub={fmt$(metrics?.max_drawdown_usd ?? null)} valueClass="text-red-400" />
            <KpiCard label="Win Rate" value={metrics?.win_rate != null ? `${(metrics.win_rate * 100).toFixed(0)}%` : "—"}
              sub={metrics?.total_trades ? `${metrics.total_trades} trades` : undefined} />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard label="Sortino" value={fmtNum(metrics?.sortino)} />
            <KpiCard label="Profit Factor" value={fmtNum(metrics?.profit_factor)} />
            <KpiCard label="Best Trade" value={fmt$(metrics?.best_trade_usd ?? null)} valueClass="text-emerald-400" />
            <KpiCard label="Worst Trade" value={fmt$(metrics?.worst_trade_usd ?? null)} valueClass="text-red-400" />
          </div>

          {/* Equity curve */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4">
            <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest mb-3">// EQUITY CURVE</p>
            <EquityCurve curve={curveData?.curve ?? []} />
          </div>

          {/* Strategy attribution */}
          {attrData && (
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4">
              <div className="flex items-center justify-between mb-3">
                <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest">
                  // STRATEGY ATTRIBUTION
                </p>
                <button
                  onClick={() => onAttrSort(attrSort === "contrib" ? "raw_return" : "contrib")}
                  className="text-[10px] text-zinc-500 hover:text-zinc-300 border border-zinc-700 rounded px-2 py-0.5"
                >
                  Sort: {attrSort === "contrib" ? "$ P&L" : "Return %"}
                </button>
              </div>
              <AttributionTable
                rows={attrData.attribution}
                totalCapital={attrData.total_capital_usd}
                sortBy={attrSort}
                sortDir={attrSortDir}
                onSort={onAttrSort}
              />
            </div>
          )}

          {/* Symbol attribution */}
          {symData && symData.symbols.length > 0 && (
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4">
              <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest mb-3">
                // TOP SYMBOLS
              </p>
              <div className="space-y-2">
                {symData.symbols.map((s) => (
                  <div key={s.symbol} className="flex items-center gap-3">
                    <span className="font-mono text-xs text-white w-16">{s.symbol}</span>
                    <div className="flex-1 bg-zinc-800 rounded-full h-1.5">
                      <div
                        className={cn("h-1.5 rounded-full", s.pnl_usd >= 0 ? "bg-emerald-500" : "bg-red-500")}
                        style={{ width: `${Math.min(100, Math.abs(s.pnl_usd) / Math.max(...symData.symbols.map((x) => Math.abs(x.pnl_usd))) * 100)}%` }}
                      />
                    </div>
                    <span className={cn("font-mono text-xs w-20 text-right", pColor(s.pnl_usd))}>
                      {fmt$(s.pnl_usd, 0)}
                    </span>
                    <span className="text-zinc-600 text-xs w-12 text-right">{s.num_trades}t</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Time of day */}
          {todData && todData.time_of_day.length > 0 && (
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4">
              <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest mb-3">
                // TIME OF DAY (avg P&L by hour)
              </p>
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={todData.time_of_day} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
                  <XAxis dataKey="hour" tick={{ fontSize: 9, fill: "#52525b" }} tickLine={false} axisLine={false}
                    tickFormatter={(h) => `${h}h`} />
                  <YAxis tick={{ fontSize: 9, fill: "#52525b" }} tickLine={false} axisLine={false}
                    tickFormatter={(v) => `$${v.toFixed(0)}`} width={40} />
                  <Tooltip
                    contentStyle={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, fontSize: 11 }}
                    formatter={(v: number) => [`$${v.toFixed(2)}`, "Avg P&L"]}
                  />
                  <ReferenceLine y={0} stroke="#3f3f46" />
                  <Bar dataKey="avg_pnl_usd" radius={[2,2,0,0]}>
                    {todData.time_of_day.map((row) => (
                      <Cell key={row.hour} fill={row.avg_pnl_usd >= 0 ? "#34d399" : "#f87171"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Tab: Leaderboard ───────────────────────────────────────────────────────────

const LEADERBOARD_METRICS: { key: LeaderboardMetric; label: string }[] = [
  { key: "sharpe", label: "Sharpe" },
  { key: "total_return_pct", label: "Return" },
  { key: "win_rate", label: "Win Rate" },
  { key: "profit_factor", label: "Profit Factor" },
  { key: "today_pnl_usd", label: "Today" },
];

function LeaderboardTab({ period }: { period: Period }) {
  const navigate = useNavigate();
  const [metric, setMetric] = useState<LeaderboardMetric>("sharpe");

  const { data, isLoading } = useQuery({
    queryKey: ["bot-leaderboard", metric, period],
    queryFn: () => getBotLeaderboard(metric, period),
    staleTime: 300_000,
    retry: 0,
  });

  const rows = data?.leaderboard ?? [];

  return (
    <div className="space-y-4">
      {/* Metric selector */}
      <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1 w-fit">
        {LEADERBOARD_METRICS.map((m) => (
          <button key={m.key} onClick={() => setMetric(m.key)}
            className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors",
              metric === m.key ? "bg-zinc-700 text-white" : "text-zinc-500 hover:text-zinc-300")}>
            {m.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[0,1,2,3,4].map((i) => <div key={i} className="h-12 bg-zinc-900 border border-zinc-800 rounded-xl animate-pulse" />)}
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
          <div className="grid grid-cols-7 px-4 py-2 border-b border-zinc-800">
            {["Rank","Bot","Sharpe","Return","Win Rate","Trades","Today"].map((h) => (
              <span key={h} className="text-[10px] font-semibold text-zinc-600 uppercase">{h}</span>
            ))}
          </div>
          {rows.map((row, i) => (
            <div
              key={row.allocation_id}
              className="grid grid-cols-7 px-4 py-3 border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/40 cursor-pointer transition-colors"
              onClick={() => navigate("/strategy/performance?tab=bybot&bot=" + row.bot_name)}
            >
              <span className="text-zinc-600 text-xs">{i + 1}</span>
              <span className="text-white text-xs font-semibold truncate">
                {BOT_DISPLAY[row.bot_name] ?? row.bot_name}
              </span>
              <span className="font-mono text-xs text-white">{fmtNum(row.sharpe)}</span>
              <span className={cn("font-mono text-xs", pColor(row.total_return_pct))}>
                {fmtPct(row.total_return_pct)}
              </span>
              <span className="font-mono text-xs text-white">
                {row.win_rate != null ? `${(row.win_rate * 100).toFixed(0)}%` : "—"}
              </span>
              <span className="font-mono text-xs text-zinc-400">{row.total_trades}</span>
              <span className={cn("font-mono text-xs", pColor(row.today_pnl_usd))}>
                {fmt$(row.today_pnl_usd ?? null)}
              </span>
            </div>
          ))}
          {rows.length === 0 && (
            <div className="px-5 py-10 text-center text-zinc-600 text-sm">No data yet</div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

type MainTab = "portfolio" | "bybot" | "leaderboard";

export default function PerformancePage() {
  const [tab, setTab] = useState<MainTab>("portfolio");
  const [period, setPeriod] = useState<Period>("30d");

  const tabs: { key: MainTab; label: string }[] = [
    { key: "portfolio", label: "// PORTFOLIO" },
    { key: "bybot", label: "// BY BOT" },
    { key: "leaderboard", label: "// LEADERBOARD" },
  ];

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 pb-24 md:pb-6 space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest mb-0.5">
            // PERFORMANCE ANALYTICS
          </p>
          <h1 className="text-2xl font-bold text-white">Performance</h1>
          <p className="text-zinc-500 text-sm mt-1">Sharpe, drawdown, win rate — every bot, measured against the data.</p>
        </div>
        <Link to="/strategy/leaderboard" className="text-xs text-violet-400 hover:text-violet-300 transition-colors">
          Strategy Leaderboard →
        </Link>
      </div>

      {/* Tab + period row */}
      <div className="flex flex-col sm:flex-row gap-2 items-start">
        <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1">
          {tabs.map((t) => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors",
                tab === t.key ? "bg-zinc-700 text-white" : "text-zinc-500 hover:text-zinc-300")}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1">
          {PERIODS.map((p) => (
            <button key={p} onClick={() => setPeriod(p)}
              className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors uppercase",
                period === p ? "bg-zinc-700 text-white" : "text-zinc-500 hover:text-zinc-300")}>
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      {tab === "portfolio"   && <PortfolioTab period={period} />}
      {tab === "bybot"       && <ByBotTab period={period} />}
      {tab === "leaderboard" && <LeaderboardTab period={period} />}

      <p className="text-xs text-zinc-700 text-center">Paper trading only. Not investment advice.</p>
    </div>
  );
}

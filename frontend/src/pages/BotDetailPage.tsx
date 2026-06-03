import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import {
  getBot,
  allocateBot,
  joinWaitlist,
  leaveWaitlist,
  type BotPosition,
  type BotSignal,
} from "@/api/bots";
import { cn } from "@/lib/utils";

// ─── Bot metadata ─────────────────────────────────────────────────────────────

const BOT_META: Record<
  string,
  { displayName: string; description: string; assetClass: "stock" | "crypto" }
> = {
  stock_swing: {
    displayName: "Stock Swing",
    description: "Russell 1000 momentum plays, 1-30 day holds",
    assetClass: "stock",
  },
  stock_day: {
    displayName: "Stock Day",
    description: "Intraday gappers & earnings momentum, EOD flat",
    assetClass: "stock",
  },
  stock_lt: {
    displayName: "Stock Long-Term",
    description: "S&P 500 factor model, monthly rebalance",
    assetClass: "stock",
  },
  crypto_swing: {
    displayName: "Crypto Swing",
    description: "Top 20 crypto by mcap, 1-30 day holds",
    assetClass: "crypto",
  },
  crypto_day: {
    displayName: "Crypto Day",
    description: "BTC/ETH/SOL intraday momentum, 24h force-close",
    assetClass: "crypto",
  },
  crypto_lt: {
    displayName: "Crypto L-T DCA",
    description: "BTC/ETH + majors, weekly DCA & monthly rebalance",
    assetClass: "crypto",
  },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function displayName(name: string): string {
  return (
    BOT_META[name]?.displayName ??
    name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

function formatPnl(val: number): string {
  const abs = Math.abs(val);
  const sign = val >= 0 ? "+" : "-";
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(2)}`;
}

function formatPct(val: number): string {
  const sign = val >= 0 ? "+" : "";
  return `${sign}${val.toFixed(2)}%`;
}

function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

// ─── Side badge ───────────────────────────────────────────────────────────────

function SideBadge({ side }: { side: "buy" | "sell" | "hold" }) {
  const styles = {
    buy: "bg-lime-500/15 text-lime-400 border-lime-500/30",
    sell: "bg-red-500/15 text-red-400 border-red-500/30",
    hold: "bg-zinc-800 text-zinc-400 border-zinc-700",
  };
  return (
    <span
      className={cn(
        "text-xs font-bold px-2 py-0.5 rounded-full border",
        styles[side]
      )}
    >
      {side.toUpperCase()}
    </span>
  );
}

// ─── Equity curve placeholder ─────────────────────────────────────────────────

interface EquityPoint {
  date: string;
  portfolio: number;
  benchmark: number;
}

function EquityCurve({
  data,
  isCrypto,
}: {
  data: EquityPoint[];
  isCrypto: boolean;
}) {
  const benchmarkLabel = isCrypto ? "BTC" : "SPY";

  if (!data || data.length === 0) {
    return (
      <div className="h-48 flex items-center justify-center bg-zinc-900/50 rounded-xl border border-zinc-800">
        <p className="text-zinc-600 text-sm">No equity data yet</p>
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
        <XAxis
          dataKey="date"
          tick={{ fill: "#71717a", fontSize: 10 }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          tick={{ fill: "#71717a", fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v: number) => `${v.toFixed(1)}%`}
        />
        <Tooltip
          contentStyle={{
            background: "#18181b",
            border: "1px solid #3f3f46",
            borderRadius: 8,
            fontSize: 12,
          }}
          labelStyle={{ color: "#a1a1aa" }}
        />
        <Line
          type="monotone"
          dataKey="portfolio"
          stroke="#84cc16"
          strokeWidth={2}
          dot={false}
          name="Portfolio"
        />
        <Line
          type="monotone"
          dataKey="benchmark"
          stroke="#52525b"
          strokeWidth={2}
          dot={false}
          name={benchmarkLabel}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function BotDetailPage() {
  const { botName = "" } = useParams<{ botName: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const meta = BOT_META[botName];
  const isCrypto = (meta?.assetClass ?? botName.startsWith("crypto") ? "crypto" : "stock") === "crypto";

  const { data, isLoading } = useQuery({
    queryKey: ["bot", botName],
    queryFn: () => getBot(botName),
    enabled: !!botName,
    retry: 1,
  });

  const profile = data?.profile;
  const allocation = data?.allocation;
  const positions: BotPosition[] = data?.positions ?? [];
  const signals: BotSignal[] = data?.signals ?? [];
  const stats = (data?.stats ?? {}) as {
    return_30d_pct?: number;
    today_pnl?: number;
    open_positions?: number;
    win_rate_pct?: number;
    equity_curve?: EquityPoint[];
  };

  // Local allocation state
  const [capitalPct, setCapitalPct] = useState<number>(
    allocation?.capital_pct ?? 10
  );
  const [riskProfile, setRiskProfile] = useState<
    "conservative" | "standard" | "aggressive"
  >(allocation?.risk_profile ?? "standard");

  const isEnabled = allocation?.enabled ?? false;
  const isOnWaitlist = allocation?.go_live_requested ?? false;

  const allocateMut = useMutation({
    mutationFn: (overrides: Partial<{ capital_pct: number; risk_profile: string; enabled: boolean }> | undefined) =>
      allocateBot(botName, {
        capital_pct: overrides?.capital_pct ?? capitalPct,
        risk_profile: overrides?.risk_profile ?? riskProfile,
        enabled: overrides?.enabled ?? isEnabled,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", botName] });
      qc.invalidateQueries({ queryKey: ["bots"] });
      toast.success("Allocation saved");
    },
    onError: () => toast.error("Failed to save allocation"),
  });

  const waitlistMut = useMutation({
    mutationFn: (joining: boolean) =>
      joining ? joinWaitlist(botName) : leaveWaitlist(botName),
    onSuccess: (_data, joining) => {
      qc.invalidateQueries({ queryKey: ["bot", botName] });
      toast.success(joining ? "Added to live waitlist" : "Removed from waitlist");
    },
    onError: () => toast.error("Failed to update waitlist"),
  });

  const equityCurve: EquityPoint[] = stats.equity_curve ?? [];

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      {/* Back nav */}
      <button
        onClick={() => navigate("/strategy")}
        className="flex items-center gap-1.5 text-zinc-500 hover:text-white text-sm transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Strategy Lab
      </button>

      {/* Paper-only banner */}
      <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 flex items-center gap-3">
        <span className="text-amber-400 text-sm font-semibold">📄 Paper trading only.</span>
        <span className="text-amber-300 text-xs">
          Live trading unlocks Q3 2026 when BMG completes RIA registration.
        </span>
        <button
          onClick={() => waitlistMut.mutate(!isOnWaitlist)}
          disabled={waitlistMut.isPending}
          className="ml-auto text-xs text-amber-400 underline whitespace-nowrap"
        >
          {isOnWaitlist ? "✓ On waitlist" : "Join the waitlist →"}
        </button>
      </div>

      {/* Hero card */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
        {isLoading ? (
          <div className="animate-pulse space-y-4">
            <div className="h-7 w-48 bg-zinc-800 rounded" />
            <div className="h-4 w-64 bg-zinc-800 rounded" />
            <div className="grid grid-cols-4 gap-4 mt-4">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-14 bg-zinc-800 rounded-xl" />
              ))}
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-start justify-between mb-1">
              <div>
                <h1 className="text-xl font-bold text-white">
                  {meta?.displayName ?? displayName(botName)}
                </h1>
                <p className="text-zinc-500 text-sm mt-0.5">
                  {meta?.description ?? profile?.description ?? ""}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "text-xs font-semibold px-2 py-0.5 rounded-full",
                    isEnabled
                      ? "bg-lime-500/15 text-lime-400 border border-lime-500/30"
                      : "bg-zinc-800 text-zinc-500 border border-zinc-700"
                  )}
                >
                  {isEnabled ? "ACTIVE" : "DISABLED"}
                </span>
              </div>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-5 mb-6">
              {[
                {
                  label: "30d Return",
                  value: formatPct(stats?.return_30d_pct ?? 0),
                  positive: (stats?.return_30d_pct ?? 0) >= 0,
                  colored: true,
                },
                {
                  label: "Today P&L",
                  value: formatPnl(stats?.today_pnl ?? 0),
                  positive: (stats?.today_pnl ?? 0) >= 0,
                  colored: true,
                },
                {
                  label: "Open Positions",
                  value: String(stats?.open_positions ?? 0),
                  positive: true,
                  colored: false,
                },
                {
                  label: "Win Rate",
                  value: `${(stats?.win_rate_pct ?? 0).toFixed(1)}%`,
                  positive: (stats?.win_rate_pct ?? 0) >= 50,
                  colored: true,
                },
              ].map((s) => (
                <div
                  key={s.label}
                  className="bg-zinc-950 rounded-xl px-4 py-3 border border-zinc-800"
                >
                  <p className="text-zinc-600 text-xs mb-1">{s.label}</p>
                  <p
                    className={cn(
                      "text-lg font-bold",
                      s.colored
                        ? s.positive
                          ? "text-lime-400"
                          : "text-red-400"
                        : "text-white"
                    )}
                  >
                    {s.value}
                  </p>
                </div>
              ))}
            </div>

            {/* Allocation */}
            <div className="border-t border-zinc-800 pt-5">
              <h2 className="text-sm font-semibold text-zinc-300 mb-4">
                Allocation Settings
              </h2>
              <div className="flex flex-col sm:flex-row gap-6">
                {/* Capital slider */}
                <div className="flex-1">
                  <label className="text-xs text-zinc-500 mb-1 block">
                    Capital Allocated — {capitalPct}%
                  </label>
                  <input
                    type="range"
                    min={10}
                    max={100}
                    step={10}
                    value={capitalPct}
                    onChange={(e) => setCapitalPct(Number(e.target.value))}
                    className="w-full accent-lime-500"
                  />
                  <div className="flex justify-between text-xs text-zinc-700 mt-0.5">
                    <span>10%</span>
                    <span>100%</span>
                  </div>
                </div>

                {/* Risk profile */}
                <div>
                  <label className="text-xs text-zinc-500 mb-1 block">
                    Risk Profile
                  </label>
                  <div className="flex gap-2">
                    {(
                      ["conservative", "standard", "aggressive"] as const
                    ).map((r) => (
                      <button
                        key={r}
                        onClick={() => setRiskProfile(r)}
                        className={cn(
                          "text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors capitalize",
                          riskProfile === r
                            ? "bg-lime-500/15 border-lime-500/40 text-lime-400"
                            : "bg-zinc-800 border-zinc-700 text-zinc-500 hover:text-zinc-300"
                        )}
                      >
                        {r}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3 mt-4">
                <button
                  onClick={() => allocateMut.mutate(undefined)}
                  disabled={allocateMut.isPending}
                  className="px-4 py-2 rounded-lg bg-lime-500 text-black text-sm font-bold hover:bg-lime-400 transition-colors disabled:opacity-50"
                >
                  {allocateMut.isPending ? "Saving…" : "Save"}
                </button>
                <button
                  onClick={() =>
                    allocateMut.mutate({ enabled: !isEnabled })
                  }
                  disabled={allocateMut.isPending}
                  className={cn(
                    "px-4 py-2 rounded-lg border text-sm font-semibold transition-colors",
                    isEnabled
                      ? "border-zinc-700 text-zinc-400 hover:border-red-600 hover:text-red-400"
                      : "border-lime-600/50 text-lime-400 hover:bg-lime-500/10"
                  )}
                >
                  {isEnabled ? "Disable Bot" : "Enable Bot"}
                </button>

                {/* Go Live — disabled */}
                <div className="relative ml-auto">
                  <button
                    disabled
                    className="opacity-50 cursor-not-allowed px-4 py-2 rounded-lg border border-zinc-700 text-sm text-zinc-400"
                  >
                    Go Live
                  </button>
                  <div className="absolute -top-8 left-0 bg-zinc-800 text-xs text-zinc-300 px-2 py-1 rounded whitespace-nowrap pointer-events-none">
                    Live trading unlocks Q3 2026. Join the waitlist above.
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Equity curve */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
        <h2 className="text-sm font-semibold text-zinc-300 mb-4">
          Equity Curve vs {isCrypto ? "BTC" : "SPY"}
        </h2>
        <EquityCurve data={equityCurve} isCrypto={isCrypto} />
        <div className="flex gap-4 mt-2">
          <div className="flex items-center gap-1.5 text-xs text-zinc-500">
            <span className="w-3 h-0.5 bg-[#84cc16] inline-block rounded" />
            Portfolio
          </div>
          <div className="flex items-center gap-1.5 text-xs text-zinc-500">
            <span className="w-3 h-0.5 bg-zinc-600 inline-block rounded" />
            {isCrypto ? "BTC" : "SPY"}
          </div>
        </div>
      </div>

      {/* Paper Positions */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
        <h2 className="text-sm font-semibold text-zinc-300 mb-4">
          Paper Positions
        </h2>
        {positions.length === 0 ? (
          <p className="text-zinc-600 text-sm py-4 text-center">
            No open positions
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-zinc-600 border-b border-zinc-800">
                  <th className="text-left pb-2 font-medium">Symbol</th>
                  <th className="text-right pb-2 font-medium">Qty</th>
                  <th className="text-right pb-2 font-medium">Avg Cost</th>
                  <th className="text-right pb-2 font-medium">Current Price</th>
                  <th className="text-right pb-2 font-medium">P&L</th>
                  <th className="text-right pb-2 font-medium">Opened</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => {
                  const avgCost = pos.avg_cost_cents / 100;
                  return (
                    <tr
                      key={pos.id}
                      className="border-b border-zinc-800/50 last:border-0"
                    >
                      <td className="py-2.5 font-semibold text-white">
                        {pos.symbol}
                      </td>
                      <td className="py-2.5 text-right text-zinc-300">
                        {pos.qty}
                      </td>
                      <td className="py-2.5 text-right text-zinc-300">
                        {formatCents(pos.avg_cost_cents)}
                      </td>
                      <td className="py-2.5 text-right text-zinc-500">—</td>
                      <td className="py-2.5 text-right text-zinc-500">—</td>
                      <td className="py-2.5 text-right text-zinc-500 text-xs">
                        {formatTime(pos.opened_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recent Signals */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
        <h2 className="text-sm font-semibold text-zinc-300 mb-4">
          Recent Signals
        </h2>
        {signals.length === 0 ? (
          <p className="text-zinc-600 text-sm py-4 text-center">
            No recent signals
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-zinc-600 border-b border-zinc-800">
                  <th className="text-left pb-2 font-medium">Time</th>
                  <th className="text-left pb-2 font-medium">Symbol</th>
                  <th className="text-left pb-2 font-medium">Side</th>
                  <th className="text-right pb-2 font-medium">Confidence</th>
                  <th className="text-left pb-2 font-medium">Strategy</th>
                  <th className="text-left pb-2 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((sig) => (
                  <tr
                    key={sig.id}
                    className="border-b border-zinc-800/50 last:border-0"
                  >
                    <td className="py-2.5 text-zinc-500 text-xs">
                      {formatTime(sig.ts)}
                    </td>
                    <td className="py-2.5 font-semibold text-white">
                      {sig.symbol}
                    </td>
                    <td className="py-2.5">
                      <SideBadge side={sig.side} />
                    </td>
                    <td className="py-2.5 text-right text-zinc-300">
                      {sig.confidence.toFixed(0)}%
                    </td>
                    <td className="py-2.5 text-zinc-400 text-xs">
                      {sig.strategy}
                    </td>
                    <td className="py-2.5 text-zinc-500 text-xs max-w-xs truncate">
                      {sig.reason}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Footer */}
      <p className="text-xs text-center text-zinc-600 mt-8">
        Paper trading. Not investment advice. Not a registered investment adviser.
      </p>
    </div>
  );
}

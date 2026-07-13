import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import client from "@/api/client";

type Verdict =
  | "significant_positive"
  | "significant_inverse"
  | "weak_signal"
  | "weak_signal_after_dsr"
  | "no_signal"
  | "insufficient_data"
  | "no_valid_forward_returns"
  | "error";

interface Scorecard {
  bot_id: number;
  bot_name: string;
  verdict: Verdict;
  verdict_original?: Verdict;
  n_rebalances?: number;
  min_required?: number;
  forward_days?: number;
  ic_mean?: number;
  ic_std?: number;
  ic_tstat?: number;
  quintile_spread_pct?: number;
  survives_dsr?: boolean | null;
  per_rebal_sample?: Array<{
    rebal_date: string;
    n_symbols_scored: number;
    ic: number;
    quintile_spread_pct: number;
  }>;
  error?: string;
}

interface DsrSummary {
  n_tested: number;
  threshold: number;
  n_survived: number;
  explanation: string;
}

interface ScorecardResponse {
  as_of: string;
  forward_days: number;
  n_bots: number;
  dsr?: DsrSummary;
  scorecards: Scorecard[];
}

const VERDICT_COLORS: Record<Verdict, string> = {
  significant_positive: "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40",
  significant_inverse: "bg-purple-500/20 text-purple-300 border border-purple-500/40",
  weak_signal: "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40",
  weak_signal_after_dsr: "bg-amber-500/20 text-amber-300 border border-amber-500/40",
  no_signal: "bg-slate-500/20 text-slate-300 border border-slate-500/40",
  insufficient_data: "bg-slate-700 text-slate-400 border border-slate-600",
  no_valid_forward_returns: "bg-amber-500/20 text-amber-300 border border-amber-500/40",
  error: "bg-red-500/20 text-red-300 border border-red-500/40",
};

const VERDICT_LABELS: Record<Verdict, string> = {
  significant_positive: "REAL SIGNAL",
  significant_inverse: "INVERSE — FLIP OR HALT",
  weak_signal: "WEAK",
  weak_signal_after_dsr: "FAILS DSR",
  no_signal: "NOISE",
  insufficient_data: "NOT ENOUGH DATA",
  no_valid_forward_returns: "NO BARS",
  error: "ERROR",
};

function fmt(v: number | undefined, digits = 2): string {
  if (v === undefined || v === null || Number.isNaN(v)) return "—";
  const s = v >= 0 ? "+" : "";
  return `${s}${v.toFixed(digits)}`;
}

export default function FactorScorecardPage() {
  const [forwardDays, setForwardDays] = useState(21);
  const [sortKey, setSortKey] = useState<"ic_tstat" | "ic_mean" | "quintile_spread_pct" | "n_rebalances">("ic_tstat");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ["factor-scorecard", forwardDays],
    queryFn: async (): Promise<ScorecardResponse> => {
      const res = await client.get<ScorecardResponse>("/admin/factor-scorecard", {
        params: { forward_days: forwardDays },
      });
      return res.data;
    },
    staleTime: 60 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const sortedCards: Scorecard[] = useMemo(() => {
    const cards = data?.scorecards ?? [];
    const dir = sortDir === "asc" ? 1 : -1;
    return [...cards].sort((a, b) => {
      const av = (a as any)[sortKey] ?? -Infinity;
      const bv = (b as any)[sortKey] ?? -Infinity;
      if (av === bv) return 0;
      return av < bv ? -dir : dir;
    });
  }, [data, sortKey, sortDir]);

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
        className={`text-left text-xs uppercase tracking-wider px-3 py-2 ${
          active ? "text-emerald-400" : "text-slate-400"
        }`}
      >
        {label} {active ? (sortDir === "asc" ? "▲" : "▼") : ""}
      </button>
    );
  };

  const buckets = useMemo(() => {
    const b = { real: 0, inverse: 0, weak: 0, noise: 0, insufficient: 0, other: 0 };
    for (const c of data?.scorecards ?? []) {
      if (c.verdict === "significant_positive") b.real++;
      else if (c.verdict === "significant_inverse") b.inverse++;
      else if (c.verdict === "weak_signal") b.weak++;
      else if (c.verdict === "no_signal") b.noise++;
      else if (c.verdict === "insufficient_data") b.insufficient++;
      else b.other++;
    }
    return b;
  }, [data]);

  return (
    <div className="min-h-screen bg-[#040804] text-slate-200 p-6">
      <div className="flex items-baseline justify-between mb-4">
        <div>
          <h1 className="text-2xl font-mono tracking-wider text-emerald-400">FACTOR SCORECARD</h1>
          <p className="text-xs text-slate-500 mt-1">
            alphalens-style · IC + quintile spread per PR bot · yfinance forward returns
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <label className="text-slate-500">
            Forward days:{" "}
            <select
              value={forwardDays}
              onChange={(e) => setForwardDays(parseInt(e.target.value, 10))}
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-200 ml-1"
            >
              <option value={5}>5</option>
              <option value={10}>10</option>
              <option value={21}>21 (1mo)</option>
              <option value={63}>63 (1q)</option>
            </select>
          </label>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="px-3 py-1 border border-slate-700 rounded text-slate-300 hover:border-emerald-500/40 disabled:opacity-50"
          >
            {isFetching ? "computing..." : "recompute"}
          </button>
        </div>
      </div>

      {/* Summary buckets */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
        {[
          { label: "REAL SIGNAL", count: buckets.real, cls: VERDICT_COLORS.significant_positive },
          { label: "INVERSE", count: buckets.inverse, cls: VERDICT_COLORS.significant_inverse },
          { label: "WEAK", count: buckets.weak, cls: VERDICT_COLORS.weak_signal },
          { label: "NOISE", count: buckets.noise, cls: VERDICT_COLORS.no_signal },
          { label: "NEED MORE DATA", count: buckets.insufficient, cls: VERDICT_COLORS.insufficient_data },
        ].map((b) => (
          <div key={b.label} className={`rounded p-3 ${b.cls}`}>
            <div className="text-xs uppercase tracking-wider">{b.label}</div>
            <div className="text-3xl font-mono tabular-nums mt-1">{b.count}</div>
          </div>
        ))}
      </div>

      {/* DSR summary strip */}
      {data?.dsr && (
        <div className="mb-6 border border-slate-800 rounded p-3 bg-slate-950/50 text-xs">
          <div className="flex items-baseline justify-between">
            <div className="text-slate-400 uppercase tracking-wider">
              Deflated Sharpe (Bailey-Prado 2014)
            </div>
            <div className="text-slate-500">
              threshold |t| &gt; {data.dsr.threshold.toFixed(2)} · N tested: {data.dsr.n_tested}
            </div>
          </div>
          <div className="mt-1 text-slate-300">
            <span className="text-emerald-400 font-mono">{data.dsr.n_survived}</span>{" "}
            of {data.dsr.n_tested} factors survive multiple-testing correction. Factors
            marked{" "}
            <span className="inline-block px-2 py-0.5 text-[10px] font-mono rounded bg-amber-500/20 text-amber-300 border border-amber-500/40">
              FAILS DSR
            </span>{" "}
            had positive raw IC but don't clear the corrected significance bar — treat
            as unconfirmed, not noise.
          </div>
        </div>
      )}

      {error ? (
        <div className="border border-red-500/30 bg-red-950/20 rounded p-4 text-red-300 text-sm">
          Failed to load scorecard. Are you admin (user_id=1)?
        </div>
      ) : isLoading ? (
        <div className="text-slate-500 text-sm">Computing — pulls yfinance for every ranked symbol, expect 30-60s...</div>
      ) : (
        <div className="border border-slate-800 rounded-lg bg-slate-950/40">
          <div className="p-3 border-b border-slate-800 text-xs text-slate-500">
            {sortedCards.length} bots · as of{" "}
            {data?.as_of ? new Date(data.as_of).toLocaleString() : "—"} · forward_days={data?.forward_days}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-900/40">
                <tr>
                  <th className="text-left text-xs uppercase tracking-wider px-3 py-2 text-slate-400">
                    Bot
                  </th>
                  <th className="text-left text-xs uppercase tracking-wider px-3 py-2 text-slate-400">
                    Verdict
                  </th>
                  <th>{th("N rebal", "n_rebalances")}</th>
                  <th>{th("IC mean", "ic_mean")}</th>
                  <th>{th("IC t-stat", "ic_tstat")}</th>
                  <th>{th("Q1-Q5 spread %", "quintile_spread_pct")}</th>
                  <th className="text-left text-xs uppercase tracking-wider px-3 py-2 text-slate-400">
                    Last 5 rebal
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedCards.map((c) => (
                  <tr key={c.bot_id} className="border-t border-slate-900 hover:bg-slate-900/40">
                    <td className="px-3 py-2 font-mono text-xs text-slate-200">{c.bot_name}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`inline-block px-2 py-0.5 text-[10px] font-mono rounded ${VERDICT_COLORS[c.verdict]}`}
                      >
                        {VERDICT_LABELS[c.verdict]}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums text-slate-300">
                      {c.n_rebalances ?? "—"}
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums">
                      <span
                        className={
                          c.ic_mean === undefined
                            ? "text-slate-600"
                            : c.ic_mean > 0.02
                            ? "text-emerald-400"
                            : c.ic_mean < -0.02
                            ? "text-red-400"
                            : "text-slate-400"
                        }
                      >
                        {fmt(c.ic_mean, 3)}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums">
                      <span
                        className={
                          c.ic_tstat === undefined
                            ? "text-slate-600"
                            : Math.abs(c.ic_tstat) > 2
                            ? "text-emerald-400"
                            : "text-slate-400"
                        }
                      >
                        {fmt(c.ic_tstat, 2)}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums">
                      <span
                        className={
                          c.quintile_spread_pct === undefined
                            ? "text-slate-600"
                            : c.quintile_spread_pct > 0
                            ? "text-emerald-400"
                            : "text-red-400"
                        }
                      >
                        {fmt(c.quintile_spread_pct, 2)}%
                      </span>
                    </td>
                    <td className="px-3 py-2 text-[10px] text-slate-500 font-mono">
                      {(c.per_rebal_sample ?? [])
                        .map(
                          (r) =>
                            `${r.rebal_date.slice(5)}:${r.ic >= 0 ? "+" : ""}${(r.ic * 100).toFixed(0)}`,
                        )
                        .join(" ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="text-[10px] text-slate-600 text-center mt-6 font-mono">
        IC t-stat &gt; 2.0 = real signal · &lt; -2.0 = inverse (flip or halt) · |mean| &lt; 0.02 = noise
      </div>
    </div>
  );
}

/**
 * LLMUsageCard — SHIP 4 diagnostic card for LLM relay usage.
 * Fetches /admin/diagnostics/llm-usage and renders relay/cache/fallback KPIs.
 */
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Cpu } from "lucide-react";
import { cn } from "@/lib/utils";
import client from "@/api/client";

// ── Types (match backend response shape exactly per known-issue #4) ──────────

interface LLMUsageToday {
  relay_calls: number;
  api_fallback_calls: number;
  cache_hits: number;
  api_fallback_cost_cents: number;
}

interface LLMTopCaller {
  agent_name: string;
  calls: number;
  estimated_cost_cents: number;
}

interface LLMTrendDay {
  date: string;
  relay: number;
  api_fallback: number;
  cents: number;
}

interface LLMUsageData {
  today: LLMUsageToday;
  top_callers_7d: LLMTopCaller[];
  trend_7d: LLMTrendDay[];
  fallback_enabled: boolean;
  budget_remaining_cents: number;
}

// ── API fetcher ──────────────────────────────────────────────────────────────

async function getLLMUsage(): Promise<LLMUsageData> {
  const res = await client.get("/api/admin/diagnostics/llm-usage");
  return res.data as LLMUsageData;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const fmtCents = (c: number | null | undefined): string => {
  if (c == null) return "—";
  return `$${(c / 100).toFixed(2)}`;
};

// ── Component ────────────────────────────────────────────────────────────────

export function LLMUsageCard() {
  const q = useQuery({
    queryKey: ["adm-llm-usage"],
    queryFn: getLLMUsage,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  const d = q.data;
  const today = d?.today;
  const fallbackEnabled = d?.fallback_enabled ?? false;

  return (
    <div className="bg-t-bg1 border border-t-dim rounded-xl p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Cpu size={14} className="text-cyan-400" />
          <span className="text-[11px] uppercase tracking-widest font-bold text-t-hi font-mono-t">
            // LLM USAGE
          </span>
        </div>
        <button
          onClick={() => q.refetch()}
          disabled={q.isFetching}
          className="text-t-muted hover:text-t-hi transition-colors"
          title="Refresh"
        >
          <RefreshCw size={12} className={cn(q.isFetching && "animate-spin")} />
        </button>
      </div>

      {/* Error state */}
      {q.error && (
        <div className="text-[11px] text-red-400 italic">
          Failed to load LLM usage data
        </div>
      )}

      {/* Loading state */}
      {q.isLoading && (
        <div className="text-[11px] text-t-muted italic">Loading...</div>
      )}

      {/* KPI tiles */}
      {today && (
        <div className="grid grid-cols-3 gap-2">
          <div className="bg-t-bg2 border border-t-dim rounded px-2 py-1.5">
            <div className="text-[9px] uppercase text-t-muted tracking-wider">Relay calls today</div>
            <div className="text-sm font-mono-t text-t-hi">{today.relay_calls.toLocaleString()}</div>
          </div>
          <div className="bg-t-bg2 border border-t-dim rounded px-2 py-1.5">
            <div className="text-[9px] uppercase text-t-muted tracking-wider">API fallback today</div>
            <div className={cn(
              "text-sm font-mono-t",
              today.api_fallback_calls > 0 ? "text-amber-300" : "text-t-hi",
            )}>
              {today.api_fallback_calls.toLocaleString()}
            </div>
          </div>
          <div className="bg-t-bg2 border border-t-dim rounded px-2 py-1.5">
            <div className="text-[9px] uppercase text-t-muted tracking-wider">Cache hits today</div>
            <div className="text-sm font-mono-t text-t-hi">{today.cache_hits.toLocaleString()}</div>
          </div>
        </div>
      )}

      {/* Fallback status + budget */}
      {d && (
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-t-muted">
            Fallback enabled:{" "}
            <span className={cn(
              "font-semibold font-mono-t",
              fallbackEnabled ? "text-red-400" : "text-emerald-400",
            )}>
              {fallbackEnabled ? "true" : "false"}
            </span>
          </span>
          <span className="text-t-muted">
            Budget remaining today:{" "}
            <span className="font-mono-t text-t-hi">{fmtCents(d.budget_remaining_cents)}</span>
          </span>
        </div>
      )}

      {/* Top callers table */}
      {d && (d.top_callers_7d ?? []).length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[9px] uppercase tracking-wider text-t-muted font-semibold">Top callers (7d)</div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] font-mono-t">
              <thead>
                <tr className="text-t-muted text-[10px] uppercase tracking-wider border-b border-t-dim">
                  <th className="text-left py-1.5 px-1.5 font-semibold">Agent</th>
                  <th className="text-right py-1.5 px-1.5 font-semibold">Calls</th>
                  <th className="text-right py-1.5 px-1.5 font-semibold">Est cost</th>
                </tr>
              </thead>
              <tbody>
                {(d.top_callers_7d ?? []).map((row) => (
                  <tr key={row.agent_name} className="border-b border-t-dim/30 hover:bg-t-bg2/50">
                    <td className="py-1 px-1.5 text-t-hi">{row.agent_name}</td>
                    <td className="py-1 px-1.5 text-right text-t-mid2">{row.calls.toLocaleString()}</td>
                    <td className="py-1 px-1.5 text-right text-t-mid2">{fmtCents(row.estimated_cost_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 7-day trend sparkline (relay vs fallback) */}
      {d && (d.trend_7d ?? []).length > 0 && (
        <div className="space-y-1">
          <div className="text-[9px] uppercase tracking-wider text-t-muted font-semibold">7-day trend</div>
          <div className="flex items-end gap-1 h-10">
            {(d.trend_7d ?? []).map((day) => {
              const total = day.relay + day.api_fallback;
              const maxVal = Math.max(...(d.trend_7d ?? []).map((x) => x.relay + x.api_fallback), 1);
              const heightPct = total > 0 ? Math.max(10, (total / maxVal) * 100) : 4;
              return (
                <div
                  key={day.date}
                  className="flex-1 flex flex-col justify-end"
                  title={`${day.date}: relay=${day.relay} fallback=${day.api_fallback}`}
                >
                  <div
                    className={cn(
                      "w-full rounded-sm",
                      day.api_fallback > 0 ? "bg-amber-400" : "bg-cyan-500",
                    )}
                    style={{ height: `${heightPct}%` }}
                  />
                </div>
              );
            })}
          </div>
          <div className="flex justify-between text-[9px] text-t-muted">
            <span>{(d.trend_7d ?? [])[0]?.date.slice(5)}</span>
            <span>{(d.trend_7d ?? [])[(d.trend_7d ?? []).length - 1]?.date.slice(5)}</span>
          </div>
        </div>
      )}

      {/* Fallback cost today */}
      {today && today.api_fallback_cost_cents > 0 && (
        <div className="text-[11px] text-amber-300 font-mono-t">
          Fallback cost today: {fmtCents(today.api_fallback_cost_cents)}
        </div>
      )}
    </div>
  );
}

/**
 * SHIP 6 — Auto-Paused Bots diagnostic card.
 *
 * Fetches GET /admin/auto-pause/list and displays bots whose stop-hit rate
 * exceeded 70% over the last 7d and were automatically paused. The only way
 * to re-enable is POST /admin/bots/{bot_id}/enable (existing admin endpoint).
 */
import { PauseCircle, RefreshCw } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { BracketFrame, SectionLabel } from "@/components/design";
import { getAutoPausedBots } from "@/api/adminAutoPause";

interface AutoPausedBotsCardProps {
  qcRefresh: number;
}

const fmtTime = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso ?? "—";
  }
};

export function AutoPausedBotsCard({ qcRefresh }: AutoPausedBotsCardProps) {
  const q = useQuery({
    queryKey: ["adm-auto-paused-bots", qcRefresh],
    queryFn: getAutoPausedBots,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  const rows = q.data?.rows ?? [];
  const lastUpdated = q.data?.as_of;

  return (
    <BracketFrame className="rounded-2xl p-4 bg-t-bg1 border border-t-dim flex flex-col gap-3 min-h-[200px]">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          <PauseCircle size={14} className="text-t-muted mt-0.5 flex-shrink-0" />
          <div className="min-w-0">
            <SectionLabel>// AUTO-PAUSED BOTS</SectionLabel>
            <div className="text-[10px] text-t-faint font-mono-t mt-0.5">
              {lastUpdated ? `updated ${fmtTime(lastUpdated)}` : "—"}
            </div>
          </div>
        </div>
        <button
          onClick={() => q.refetch()}
          disabled={q.isFetching}
          aria-label="Refresh auto-paused bots"
          className="p-1 rounded border border-t-dim hover:border-t-mid text-t-mid2 hover:text-t-hi transition-colors disabled:opacity-50"
        >
          <RefreshCw size={11} className={cn(q.isFetching && "animate-spin")} />
        </button>
      </div>

      {/* Body */}
      {q.isLoading ? (
        <div className="flex-1 flex items-center justify-center text-[11px] text-t-muted font-mono-t">
          loading…
        </div>
      ) : q.error ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center px-3">
          <div className="text-[11px] text-t-red font-mono-t leading-snug">
            {String((q.error as { message?: string }).message ?? q.error)}
          </div>
          <button
            onClick={() => q.refetch()}
            disabled={q.isFetching}
            className="px-3 py-1 rounded-lg border border-t-mid/40 hover:border-t-mid text-t-mid2 hover:text-t-hi text-[11px] font-medium disabled:opacity-50"
          >
            {q.isFetching ? "Retrying…" : "Retry"}
          </button>
        </div>
      ) : rows.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-[11px] text-t-green font-mono-t text-center px-3">
          No bots auto-paused — fleet healthy.
        </div>
      ) : (
        <div className="flex-1 min-w-0 overflow-x-auto -mx-1">
          <table className="w-full text-[11px] font-mono-t">
            <thead>
              <tr className="text-t-muted text-[10px] uppercase tracking-wider border-b border-t-dim">
                <th className="text-left py-1.5 px-1.5 font-semibold whitespace-nowrap">bot</th>
                <th className="text-left py-1.5 px-1.5 font-semibold whitespace-nowrap">reason</th>
                <th className="text-left py-1.5 px-1.5 font-semibold whitespace-nowrap">paused at</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr
                  key={`${r.bot_id}-${i}`}
                  className="border-b border-t-dim/40 bg-t-red/5"
                >
                  <td className="py-1 px-1.5 text-t-hi font-semibold">{r.bot_id}</td>
                  <td className="py-1 px-1.5 text-t-mid2">{r.paused_reason}</td>
                  <td className="py-1 px-1.5 text-t-muted">{fmtTime(r.paused_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </BracketFrame>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Check, X, Minus, Circle } from "lucide-react";
import client from "@/api/client";
import { cn } from "@/lib/utils";

interface ChecklistCondition {
  name: string;
  weight: "primary" | "secondary" | "info";
  passed: boolean;
  display: string;
  distance_pct: number | null;
  value: number | null;
}

interface ChecklistResponse {
  status: "armed" | "not_armed";
  conditions: ChecklistCondition[];
  error?: string;
}

interface SetupChecklistProps {
  ticker: string;
  strategyId: string;
}

function ConditionIcon({ weight, passed }: { weight: ChecklistCondition["weight"]; passed: boolean }) {
  if (weight === "info") {
    return <Circle size={14} className="text-t-blue fill-t-blue/20" strokeWidth={2} />;
  }
  if (weight === "primary") {
    return passed ? (
      <Check size={16} className="text-t-green" strokeWidth={3} />
    ) : (
      <X size={16} className="text-t-red" strokeWidth={3} />
    );
  }
  // secondary
  return passed ? (
    <span className="inline-block w-2 h-2 rounded-full bg-t-green" aria-label="pass" />
  ) : (
    <Minus size={14} className="text-t-amber" strokeWidth={3} />
  );
}

export default function SetupChecklist({ ticker, strategyId }: SetupChecklistProps) {
  const { data, isLoading, isError } = useQuery<ChecklistResponse>({
    queryKey: ["strategy-checklist", strategyId, ticker],
    queryFn: () =>
      client
        .get<ChecklistResponse>(`/strategy/${strategyId}/checklist`, { params: { symbol: ticker } })
        .then((r) => r.data),
    enabled: !!ticker && !!strategyId,
    staleTime: 60_000,
    retry: 1,
  });

  if (isLoading) {
    return (
      <div className="bg-t-bg1 border border-t-dim rounded-2xl p-5 space-y-3">
        <span className="text-[10px] font-mono-t text-t-faint uppercase tracking-widest">
          // SETUP CHECKLIST
        </span>
        <div className="h-32 bg-t-bg0 rounded animate-pulse" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="bg-t-bg1 border border-t-dim rounded-2xl p-5 space-y-2">
        <span className="text-[10px] font-mono-t text-t-faint uppercase tracking-widest">
          // SETUP CHECKLIST
        </span>
        <p className="text-xs font-mono-t text-t-muted">Checklist unavailable for this pairing.</p>
      </div>
    );
  }

  if (data.error || data.conditions.length === 0) {
    return (
      <div className="bg-t-bg1 border border-t-dim rounded-2xl p-5 space-y-2">
        <span className="text-[10px] font-mono-t text-t-faint uppercase tracking-widest">
          // SETUP CHECKLIST
        </span>
        <p className="text-xs font-mono-t text-t-muted">
          {data.error ?? "No conditions declared for this strategy yet."}
        </p>
      </div>
    );
  }

  const armed = data.status === "armed";
  const failingPrimary = data.conditions.filter((c) => c.weight === "primary" && !c.passed);

  return (
    <div className="bg-t-bg1 border border-t-dim rounded-2xl p-5 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <span className="text-[10px] font-mono-t text-t-faint uppercase tracking-widest">
          // SETUP CHECKLIST — {ticker}
        </span>
        <span className="text-[10px] font-mono-t text-t-faint">
          green ✓ primary · yellow – secondary · ⊙ info
        </span>
      </div>

      <table className="w-full text-xs font-mono-t">
        <thead>
          <tr className="text-t-gdim border-b border-t-dim/50">
            <th className="text-left pb-2 font-medium w-6"></th>
            <th className="text-left pb-2 font-medium">Condition</th>
            <th className="text-left pb-2 font-medium hidden sm:table-cell">Current</th>
            <th className="text-right pb-2 font-medium">Weight</th>
          </tr>
        </thead>
        <tbody>
          {data.conditions.map((c, i) => (
            <tr key={i} className="border-b border-t-dim/30 last:border-0">
              <td className="py-2 align-middle">
                <ConditionIcon weight={c.weight} passed={c.passed} />
              </td>
              <td
                className={cn(
                  "py-2 align-middle",
                  c.weight === "primary"
                    ? c.passed
                      ? "text-t-body"
                      : "text-t-hi"
                    : "text-t-body",
                )}
              >
                {c.name}
              </td>
              <td className="py-2 align-middle text-t-muted hidden sm:table-cell">{c.display}</td>
              <td className="py-2 align-middle text-right">
                <span
                  className={cn(
                    "px-1.5 py-0.5 rounded text-[9px] uppercase tracking-wider border",
                    c.weight === "primary"
                      ? "border-t-violet/40 text-t-violet"
                      : c.weight === "secondary"
                        ? "border-t-amber/40 text-t-amber"
                        : "border-t-blue/40 text-t-blue",
                  )}
                >
                  {c.weight}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Mobile: show display row underneath each condition */}
      <div className="sm:hidden space-y-2">
        {data.conditions.map((c, i) => (
          <div key={i} className="text-[11px] font-mono-t text-t-muted pl-6">
            {c.name}: <span className="text-t-body">{c.display}</span>
          </div>
        ))}
      </div>

      <div className="pt-2 border-t border-t-dim/50 space-y-2">
        <div className="flex items-center justify-between gap-3">
          <span className="text-[10px] font-mono-t text-t-faint uppercase tracking-widest">
            Status
          </span>
          <span
            className={cn(
              "text-[11px] font-mono-t font-bold px-2.5 py-1 rounded border",
              armed
                ? "text-t-green border-t-green/40 bg-t-green/10"
                : "text-t-red border-t-red/40 bg-t-red/10",
            )}
          >
            {armed ? "ARMED" : "NOT ARMED"}
          </span>
        </div>

        {!armed && failingPrimary.length > 0 && (
          <ul className="space-y-1 text-[11px] font-mono-t">
            {failingPrimary.map((c, i) => (
              <li key={i} className="text-t-amber">
                {c.distance_pct != null
                  ? `needs ${Math.abs(c.distance_pct).toFixed(2)}% ${c.distance_pct < 0 ? "rally" : "move"} to satisfy "${c.name}"`
                  : `unmet primary: ${c.name}`}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

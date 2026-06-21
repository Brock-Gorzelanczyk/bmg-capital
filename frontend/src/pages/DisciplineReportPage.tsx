import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Ban, RefreshCw, ShieldCheck, Target } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getDisciplineReport,
  getRecentFiltered,
  getSignalTrace,
  type DisciplineGateBreakdown,
  type SignalTrace,
} from "@/api/discipline";

type WindowKey = 1 | 7 | 30;

function TopMetric({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="bg-t-bg1 border border-t-dim rounded-2xl px-6 py-5">
      <div className="text-4xl font-bold font-mono-t text-t-hi tabular-nums">{value}</div>
      <div className="text-[11px] font-bold uppercase tracking-widest text-t-muted mt-1">{label}</div>
    </div>
  );
}

function GateCard({
  index,
  total,
  data,
}: {
  index: number;
  total: number;
  data: DisciplineGateBreakdown;
}) {
  const Icon = data.icon === "block" ? Ban : AlertTriangle;
  return (
    <div className="border border-t-dim bg-t-bg1 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-[10px] font-bold uppercase tracking-widest text-t-muted">
          REASON {String(index).padStart(2, "0")} / {String(total).padStart(2, "0")}
        </div>
        <div className="text-[10px] font-bold uppercase tracking-widest text-t-muted">COUNT</div>
      </div>
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <Icon className="text-amber-400 flex-shrink-0 mt-0.5" size={18} />
          <div>
            <div className="text-sm font-bold uppercase tracking-wider text-t-hi">{data.title}</div>
            <div className="text-xs text-t-muted mt-0.5">{data.description}</div>
          </div>
        </div>
        <div className="text-3xl font-bold font-mono-t text-amber-400 tabular-nums">{data.count}</div>
      </div>
      <div className="flex items-center justify-between text-[10px] uppercase tracking-widest text-t-muted">
        <span>STATUS: <span className="text-amber-400 font-bold">FILTERED</span></span>
        <span>{data.percent}% of analyzed</span>
      </div>
    </div>
  );
}

function SignalTraceModal({ trace, onClose }: { trace: SignalTrace; onClose: () => void }) {
  const g = trace.gate;
  const s = trace.signal;
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-t-bg1 border border-t-dim rounded-2xl max-w-2xl w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-t-muted">SIGNAL TRACE</div>
            <div className="text-xl font-bold text-t-hi">#{trace.signal_id}</div>
          </div>
          <button onClick={onClose} className="text-t-muted hover:text-t-hi text-xl leading-none">×</button>
        </div>

        {s && (
          <div className="space-y-1 text-xs">
            <div className="text-[10px] uppercase tracking-widest text-t-muted">SIGNAL</div>
            <div className="font-mono text-t-hi">
              {s.side?.toUpperCase()} {s.symbol} · {s.strategy ?? "—"}
            </div>
            <div className="text-t-muted">
              confidence {(s.confidence * 100).toFixed(0)}% · entry {s.entry_price ?? "—"} · stop {s.stop_price ?? "—"} · target {s.target_price ?? "—"}
            </div>
          </div>
        )}

        {g && (
          <div className="space-y-2 text-xs">
            <div className="text-[10px] uppercase tracking-widest text-t-muted">GATE EVALUATION</div>
            <div className={cn("flex items-center justify-between p-2 rounded border",
              g.regime_gate_passed
                ? "border-t-green/30 bg-t-green/5"
                : "border-amber-700/30 bg-amber-900/10")}>
              <span>Regime: required <code>{g.regime_required}</code> · current <code>{g.regime_current}</code></span>
              <span className={g.regime_gate_passed ? "text-t-green" : "text-amber-400"}>
                {g.regime_gate_passed ? "PASS" : "FAIL"}
              </span>
            </div>
            <div className={cn("flex items-center justify-between p-2 rounded border",
              g.score_gate_passed
                ? "border-t-green/30 bg-t-green/5"
                : "border-amber-700/30 bg-amber-900/10")}>
              <span>Score: {g.composite_score} / {g.composite_threshold}</span>
              <span className={g.score_gate_passed ? "text-t-green" : "text-amber-400"}>
                {g.score_gate_passed ? "PASS" : "FAIL"}
              </span>
            </div>
            <div className={cn("flex items-center justify-between p-2 rounded border",
              g.confluence_gate_passed
                ? "border-t-green/30 bg-t-green/5"
                : "border-amber-700/30 bg-amber-900/10")}>
              <span>Confluence: {g.confluence_factors_passed} / {g.confluence_required} factors</span>
              <span className={g.confluence_gate_passed ? "text-t-green" : "text-amber-400"}>
                {g.confluence_gate_passed ? "PASS" : "FAIL"}
              </span>
            </div>
            <div className="text-t-muted pt-2">
              Decision: <span className="font-bold text-t-hi">{g.final_decision.toUpperCase()}</span>
              {g.filter_reason && <> · reason <code className="text-amber-400">{g.filter_reason}</code></>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function DisciplineReportPage() {
  const [window, setWindow] = useState<WindowKey>(1);
  const [openTraceId, setOpenTraceId] = useState<number | null>(null);

  const { data: report, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["discipline-report", window],
    queryFn: () => getDisciplineReport(window),
    refetchInterval: 30_000,
    staleTime: 25_000,
  });

  const { data: filteredList } = useQuery({
    queryKey: ["discipline-filtered"],
    queryFn: () => getRecentFiltered(undefined, 50),
    refetchInterval: 60_000,
    staleTime: 55_000,
  });

  const { data: trace } = useQuery({
    queryKey: ["signal-trace", openTraceId],
    queryFn: () => getSignalTrace(openTraceId!),
    enabled: openTraceId != null,
  });

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-12 text-center text-t-muted text-sm">
        <RefreshCw className="animate-spin inline mr-2" size={14} />
        Loading discipline report…
      </div>
    );
  }

  if (!report) {
    return <div className="max-w-7xl mx-auto px-4 py-12 text-center text-t-muted">Failed to load report.</div>;
  }

  const gates = [
    report.breakdown.regime_mismatch,
    report.breakdown.score_below_threshold,
    report.breakdown.insufficient_confluence,
    report.breakdown.multiple,
  ].filter((g) => g.count > 0);

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 pb-24 md:pb-6 space-y-6 animate-page-in">

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <p className="text-[10px] font-semibold text-t-muted uppercase tracking-widest mb-0.5">
            // STRATEGY LAB · DISCIPLINE
          </p>
          <h1 className="text-2xl font-bold text-t-hi flex items-center gap-2">
            <ShieldCheck size={22} className="text-violet-400" /> Discipline Filter Report
          </h1>
          <p className="text-t-muted text-sm mt-1">
            Every signal passes 3 gates before execution. This shows what was filtered and why.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {([
            [1, "TODAY"],
            [7, "7D"],
            [30, "30D"],
          ] as [WindowKey, string][]).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setWindow(k)}
              className={cn(
                "text-[10px] font-bold px-3 py-1.5 rounded border transition-colors",
                window === k
                  ? "bg-t-bg2 border-t-mid text-t-hi"
                  : "border-t-dim text-t-muted hover:text-t-hi",
              )}
            >
              {label}
            </button>
          ))}
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-1.5 bg-t-bg1 border border-t-dim hover:border-t-mid text-t-mid2 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw size={12} className={cn(isFetching && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {/* Top metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <TopMetric value={report.signals_analyzed} label="SCANNED" />
        <TopMetric value={report.trades_executed} label="DISCIPLINED" />
        <TopMetric value={report.signals_filtered} label="FILTERED" />
        <TopMetric value={`${report.gates_triggered}/3`} label="GATES TRIGGERED" />
      </div>

      {/* Gate cards */}
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-t-muted">
          <span>// FILTER REPORT</span>
          <span className="text-t-hi font-bold">{String(report.gates_triggered).padStart(2, "0")} GATES TRIGGERED</span>
        </div>
        {gates.length === 0 ? (
          <div className="border border-t-dim bg-t-bg1 rounded-xl p-6 text-center text-t-muted text-sm">
            <Target className="inline text-t-green mr-2" size={16} />
            No gates triggered in window — every analyzed signal passed all 3 checks.
          </div>
        ) : (
          gates.map((g, i) => (
            <GateCard key={g.title} index={i + 1} total={gates.length} data={g} />
          ))
        )}
      </div>

      {/* Per-strategy table */}
      {report.by_strategy.length > 0 && (
        <div className="border border-t-dim bg-t-bg1 rounded-2xl overflow-hidden">
          <div className="px-5 py-3 border-b border-t-dim text-xs font-bold uppercase tracking-widest text-t-muted">
            By Strategy
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-t-dim bg-t-bg2/40 text-t-muted">
                  <th className="px-4 py-2 text-left">Strategy</th>
                  <th className="px-4 py-2 text-right">Analyzed</th>
                  <th className="px-4 py-2 text-right">Executed</th>
                  <th className="px-4 py-2 text-right">Filtered</th>
                  <th className="px-4 py-2 text-left">Top Filter</th>
                </tr>
              </thead>
              <tbody>
                {report.by_strategy.map((s) => (
                  <tr key={s.strategy} className="border-b border-t-dim/50">
                    <td className="px-4 py-2 font-semibold text-t-hi">{s.strategy}</td>
                    <td className="px-4 py-2 text-right font-mono">{s.analyzed}</td>
                    <td className="px-4 py-2 text-right font-mono text-t-green">{s.executed}</td>
                    <td className="px-4 py-2 text-right font-mono text-amber-400">{s.filtered}</td>
                    <td className="px-4 py-2 text-t-muted">{s.top_filter ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Recent filtered signals */}
      {filteredList && filteredList.items.length > 0 && (
        <div className="border border-t-dim bg-t-bg1 rounded-2xl overflow-hidden">
          <div className="px-5 py-3 border-b border-t-dim text-xs font-bold uppercase tracking-widest text-t-muted">
            Recent Filtered Signals — click to inspect
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-t-dim bg-t-bg2/40 text-t-muted">
                  <th className="px-4 py-2 text-left">Bot</th>
                  <th className="px-4 py-2 text-left">Symbol</th>
                  <th className="px-4 py-2 text-left">Side</th>
                  <th className="px-4 py-2 text-left">Strategy</th>
                  <th className="px-4 py-2 text-right">Score</th>
                  <th className="px-4 py-2 text-right">Confluence</th>
                  <th className="px-4 py-2 text-left">Reason</th>
                </tr>
              </thead>
              <tbody>
                {filteredList.items.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => item.signal_id && setOpenTraceId(item.signal_id)}
                    className={cn(
                      "border-b border-t-dim/50",
                      item.signal_id && "cursor-pointer hover:bg-t-bg2/40",
                    )}
                  >
                    <td className="px-4 py-2 font-semibold text-t-hi">{item.bot_name}</td>
                    <td className="px-4 py-2 font-mono">{item.symbol}</td>
                    <td className="px-4 py-2">{item.side ?? "—"}</td>
                    <td className="px-4 py-2 text-t-muted">{item.strategy ?? "—"}</td>
                    <td className="px-4 py-2 text-right font-mono">
                      {item.composite_score}/{item.composite_threshold}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {item.confluence_factors_passed}/{item.confluence_required}
                    </td>
                    <td className="px-4 py-2 text-amber-400">{item.filter_reason ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Edge quote */}
      <div className="text-center text-xs italic text-t-muted py-4">
        "{report.edge_quote}"
      </div>

      {trace && openTraceId != null && (
        <SignalTraceModal trace={trace} onClose={() => setOpenTraceId(null)} />
      )}
    </div>
  );
}

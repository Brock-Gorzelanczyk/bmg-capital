import { useState, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { X, ChevronDown, ChevronUp, AlertTriangle, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { getSummary } from "@/api/strategy";
import client from "@/api/client";

// ─── Types ────────────────────────────────────────────────────────────────────

interface KellyRequest {
  win_rate: number;
  avg_win_pct: number;
  avg_loss_pct: number;
  account_size: number;
  kelly_fraction: number;
}

interface KellyResponse {
  full_kelly_pct: number;
  recommended_pct: number;
  recommended_dollars: number;
  max_shares_example: null;
  edge: number;
  interpretation: string;
  warning: string | null;
}

interface KellySizerModalProps {
  onClose: () => void;
  initialAccountSize?: number;
}

// ─── Kelly fraction options ────────────────────────────────────────────────────

const FRACTION_OPTIONS: { label: string; value: number }[] = [
  { label: "Full",    value: 1.0 },
  { label: "Half",    value: 0.5 },
  { label: "Quarter", value: 0.25 },
  { label: "Tenth",   value: 0.1 },
];

// ─── Slider row ───────────────────────────────────────────────────────────────

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
  display,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  display: string;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="text-xs text-[var(--text-tertiary)]">{label}</label>
        <span className="text-xs font-mono font-semibold text-[var(--text-primary)]">{display}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none cursor-pointer accent-blue-500 bg-[var(--border-emphasis)]"
      />
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function KellySizerModal({ onClose, initialAccountSize }: KellySizerModalProps) {
  const [winRatePct, setWinRatePct]   = useState(55);           // display as %
  const [avgWinPct, setAvgWinPct]     = useState(15);            // display as %
  const [avgLossPct, setAvgLossPct]   = useState(8);             // display as %
  const [accountSize, setAccountSize] = useState(initialAccountSize ?? 10000);
  const [kellyFraction, setKellyFraction] = useState(0.25);
  const [explainerOpen, setExplainerOpen] = useState(false);
  const [result, setResult] = useState<KellyResponse | null>(null);

  // Pre-fill win_rate from strategy summary if available
  const { data: summaryData } = useQuery({
    queryKey: ["strategy-summary"],
    queryFn: getSummary,
    staleTime: Infinity,
  });

  useEffect(() => {
    const wr = summaryData?.overall?.win_rate;
    if (wr != null && wr > 0) {
      setWinRatePct(Math.min(90, Math.max(10, Math.round(wr))));
    }
  }, [summaryData]);

  const mutation = useMutation({
    mutationFn: (body: KellyRequest) =>
      client.post<KellyResponse>("/portfolio/kelly", body).then((r) => r.data),
    onSuccess: (data) => setResult(data),
  });

  function handleCalculate() {
    mutation.mutate({
      win_rate: winRatePct / 100,
      avg_win_pct: avgWinPct / 100,
      avg_loss_pct: avgLossPct / 100,
      account_size: accountSize,
      kelly_fraction: kellyFraction,
    });
  }

  const fractionLabel = FRACTION_OPTIONS.find((o) => o.value === kellyFraction)?.label ?? "Custom";
  const hasNegativeEdge = result?.warning != null;

  return (
    // Backdrop
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="relative w-full max-w-md mx-4 bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-2xl shadow-2xl overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-emphasis)]">
          <div className="flex items-center gap-2">
            <TrendingUp size={15} className="text-blue-400" />
            <span className="font-semibold text-sm text-[var(--text-primary)]">Kelly Position Sizer</span>
          </div>
          <button onClick={onClose} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">

          {/* Inputs */}
          <SliderRow
            label="Win Rate %"
            value={winRatePct}
            min={10}
            max={90}
            step={1}
            onChange={setWinRatePct}
            display={`${winRatePct}%`}
          />
          <SliderRow
            label="Avg Win %"
            value={avgWinPct}
            min={1}
            max={50}
            step={0.5}
            onChange={setAvgWinPct}
            display={`${avgWinPct}%`}
          />
          <SliderRow
            label="Avg Loss %"
            value={avgLossPct}
            min={1}
            max={30}
            step={0.5}
            onChange={setAvgLossPct}
            display={`${avgLossPct}%`}
          />

          {/* Account size */}
          <div className="space-y-1.5">
            <label className="text-xs text-[var(--text-tertiary)]">Account Size $</label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] text-sm font-mono">$</span>
              <input
                type="number"
                min={100}
                step={1000}
                value={accountSize}
                onChange={(e) => setAccountSize(Math.max(0, parseFloat(e.target.value) || 0))}
                className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-primary)] font-mono text-sm rounded-xl py-2.5 pl-7 pr-3 outline-none focus:border-blue-600 transition-colors"
              />
            </div>
          </div>

          {/* Kelly fraction radio */}
          <div className="space-y-1.5">
            <label className="text-xs text-[var(--text-tertiary)]">Kelly Fraction</label>
            <div className="flex gap-1.5">
              {FRACTION_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setKellyFraction(opt.value)}
                  className={cn(
                    "flex-1 py-1.5 rounded-lg text-xs font-semibold transition-colors",
                    kellyFraction === opt.value
                      ? "bg-blue-600/30 border border-blue-500/50 text-blue-300"
                      : "bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Calculate button */}
          <button
            onClick={handleCalculate}
            disabled={mutation.isPending}
            className="w-full py-2.5 rounded-xl text-sm font-semibold bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {mutation.isPending ? "Calculating…" : "Calculate"}
          </button>

          {/* Results */}
          {result && (
            <div className="space-y-3 pt-1">

              {/* Warning banner */}
              {hasNegativeEdge && (
                <div className="flex items-center gap-2 bg-red-950/40 border border-red-700/40 rounded-xl px-4 py-3">
                  <AlertTriangle size={14} className="text-red-400 shrink-0" />
                  <span className="text-xs text-red-300 font-semibold">{result.warning}</span>
                </div>
              )}

              {/* Big dollar number */}
              {!hasNegativeEdge && (
                <div className="bg-[var(--bg-elevated-2)] border border-[var(--border-emphasis)] rounded-xl px-4 py-4 text-center">
                  <p className="text-3xl font-bold font-mono text-emerald-400">
                    ${result.recommended_dollars.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                  </p>
                  <p className="text-xs text-[var(--text-tertiary)] mt-1">
                    {result.recommended_pct.toFixed(2)}% of your account ({fractionLabel}-Kelly)
                  </p>
                </div>
              )}

              {/* Edge line */}
              <div className={cn(
                "flex items-center gap-2 rounded-xl px-4 py-2.5 border text-xs font-semibold",
                hasNegativeEdge
                  ? "bg-red-950/20 border-red-700/30 text-red-400"
                  : "bg-emerald-900/20 border-emerald-700/30 text-emerald-400"
              )}>
                {hasNegativeEdge ? <AlertTriangle size={12} /> : <TrendingUp size={12} />}
                Expected edge: {hasNegativeEdge ? "" : "+"}{result.edge.toFixed(2)}% per dollar risked
              </div>

              {/* Full kelly note */}
              {!hasNegativeEdge && (
                <p className="text-[10px] text-[var(--text-tertiary)] text-center">
                  Full Kelly: {result.full_kelly_pct.toFixed(2)}% of capital
                </p>
              )}

              {/* Explainer card */}
              <div className="border border-[var(--border-emphasis)] rounded-xl overflow-hidden">
                <button
                  onClick={() => setExplainerOpen((v) => !v)}
                  className="w-full flex items-center justify-between px-4 py-2.5 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
                >
                  <span>Why {fractionLabel}-Kelly?</span>
                  {explainerOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                </button>
                {explainerOpen && (
                  <div className="px-4 pb-3 text-[11px] text-[var(--text-secondary)] leading-relaxed border-t border-[var(--border-emphasis)]">
                    <p className="mt-2">
                      Full Kelly maximizes long-run log-growth in theory, but in practice it causes
                      50–70% drawdowns — brutal even for disciplined traders. Quarter-Kelly captures
                      roughly 80% of the growth rate with far less volatility, keeping drawdowns
                      manageable and letting you stay in the game through losing streaks.
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* API error */}
          {mutation.isError && (
            <p className="text-xs text-red-400 text-center">Calculation failed — please try again.</p>
          )}
        </div>
      </div>
    </div>
  );
}

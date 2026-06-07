import { useState } from "react";
import { useIsViewer } from "@/store/authStore";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getPods,
  getPodSummary,
  createPod,
  deletePod,
  addPodPosition,
  removePodPosition,
  deriskPod,
} from "@/api/pods";
import type { Pod, DeriskResult } from "@/api/pods";
import { cn } from "@/lib/utils";
import {
  Layers,
  Plus,
  X,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  ShieldOff,
  Trash2,
  TrendingUp,
  TrendingDown,
} from "lucide-react";
import { toast } from "sonner";

// ─── Constants ───────────────────────────────────────────────────────────────

const EMOJI_OPTIONS = ["📊", "🚀", "💰", "🧠", "⚡", "🔥", "🌊", "🎯", "💎", "🦅", "🐉", "🌿"];

const COLOR_OPTIONS = [
  "#3B82F6", // blue
  "#10B981", // emerald
  "#F59E0B", // amber
  "#EF4444", // red
  "#8B5CF6", // violet
  "#EC4899", // pink
  "#06B6D4", // cyan
  "#F97316", // orange
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmtCurrency(v: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v);
}

function fmtPct(v: number) {
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

// ─── Drawdown Gauge ───────────────────────────────────────────────────────────

function DrawdownGauge({ drawdownPct, stopPct }: { drawdownPct: number; stopPct: number }) {
  const usedPct = stopPct > 0 ? Math.min(100, (drawdownPct / stopPct) * 100) : 0;
  const color =
    usedPct >= 75
      ? "bg-red-500"
      : usedPct >= 50
      ? "bg-amber-500"
      : "bg-emerald-500";

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-[var(--text-tertiary)]">
        <span>Drawdown gauge</span>
        <span>{drawdownPct.toFixed(2)}% of {stopPct}% stop</span>
      </div>
      <div className="h-1.5 rounded-full bg-[var(--bg-elevated-2)] overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-500", color)}
          style={{ width: `${usedPct}%` }}
        />
      </div>
    </div>
  );
}

// ─── Add Position Form ────────────────────────────────────────────────────────

function AddPositionForm({
  podId,
  onAdded,
}: {
  podId: number;
  onAdded: () => void;
}) {
  const [symbol, setSymbol] = useState("");
  const [shares, setShares] = useState("");
  const [avgCost, setAvgCost] = useState("");
  const qc = useQueryClient();

  const addMut = useMutation({
    mutationFn: () =>
      addPodPosition(podId, {
        symbol,
        shares: parseFloat(shares),
        average_cost: parseFloat(avgCost),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pod-summary", podId] });
      setSymbol("");
      setShares("");
      setAvgCost("");
      toast.success("Position added");
      onAdded();
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to add position";
      toast.error(msg);
    },
  });

  const canSubmit = symbol.trim() && parseFloat(shares) > 0 && parseFloat(avgCost) > 0;

  return (
    <form
      className="mt-3 pt-3 border-t border-[var(--border-subtle)] space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSubmit) addMut.mutate();
      }}
    >
      <p className="text-xs font-semibold text-[var(--text-secondary)]">Add Position</p>
      <div className="flex gap-2">
        <input
          className="flex-1 bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-1.5 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--accent-positive)]"
          placeholder="Symbol (e.g. AAPL)"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
        />
        <input
          className="w-24 bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-1.5 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--accent-positive)]"
          placeholder="Shares"
          type="number"
          min="0"
          step="any"
          value={shares}
          onChange={(e) => setShares(e.target.value)}
        />
        <input
          className="w-28 bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-1.5 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--accent-positive)]"
          placeholder="Avg cost"
          type="number"
          min="0"
          step="any"
          value={avgCost}
          onChange={(e) => setAvgCost(e.target.value)}
        />
        <button
          type="submit"
          disabled={!canSubmit || addMut.isPending}
          className="px-3 py-1.5 bg-[var(--accent-positive)] text-white text-xs font-semibold rounded-lg disabled:opacity-40 hover:opacity-90 transition-opacity"
        >
          {addMut.isPending ? "Adding…" : "Add"}
        </button>
      </div>
    </form>
  );
}

// ─── Pod Card ─────────────────────────────────────────────────────────────────

function PodCard({
  pod,
  onDeriskAlert,
  isViewer = false,
}: {
  pod: Pod;
  onDeriskAlert: (result: DeriskResult) => void;
  isViewer?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const qc = useQueryClient();

  const { data: summary, isLoading } = useQuery({
    queryKey: ["pod-summary", pod.id],
    queryFn: () => getPodSummary(pod.id),
    enabled: expanded,
    staleTime: 55_000,
    refetchInterval: 60_000,
  });

  const deleteMut = useMutation({
    mutationFn: () => deletePod(pod.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pods"] });
      toast.success(`Pod "${pod.name}" deleted`);
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Cannot delete pod";
      toast.error(msg);
    },
  });

  const deriskMut = useMutation({
    mutationFn: () => deriskPod(pod.id),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["pods"] });
      qc.invalidateQueries({ queryKey: ["pod-summary", pod.id] });
      onDeriskAlert(data);
    },
    onError: () => toast.error("De-risk failed"),
  });

  const removeMut = useMutation({
    mutationFn: (symbol: string) => removePodPosition(pod.id, symbol),
    onSuccess: (_data, symbol) => {
      qc.invalidateQueries({ queryKey: ["pod-summary", pod.id] });
      toast.success(`Removed ${symbol}`);
    },
  });

  const s = summary;
  const drawdownPct = s?.drawdown_pct ?? 0;
  const stopPct = pod.drawdown_stop_pct;
  const atRisk = s?.at_risk ?? false;
  const hitStop = drawdownPct >= stopPct;

  return (
    <div
      className={cn(
        "bg-[var(--bg-elevated)] border rounded-xl overflow-hidden transition-all duration-200",
        pod.is_derisked
          ? "border-red-700/60"
          : atRisk
          ? "border-amber-600/60"
          : "border-[var(--border-subtle)]"
      )}
      style={{ borderLeftColor: pod.color, borderLeftWidth: 3 }}
    >
      {/* Card header */}
      <div className="p-4">
        {/* Banners */}
        {pod.is_derisked && (
          <div className="flex items-center gap-1.5 mb-3 px-2.5 py-1.5 bg-red-900/30 border border-red-700/40 rounded-lg">
            <ShieldOff size={13} className="text-red-400 shrink-0" />
            <span className="text-xs font-semibold text-red-400">De-Risked — 50% reduction triggered</span>
          </div>
        )}
        {!pod.is_derisked && atRisk && (
          <div className="flex items-center gap-1.5 mb-3 px-2.5 py-1.5 bg-amber-900/30 border border-amber-600/40 rounded-lg animate-pulse">
            <AlertTriangle size={13} className="text-amber-400 shrink-0" />
            <span className="text-xs font-semibold text-amber-400">At Risk — approaching drawdown stop</span>
          </div>
        )}

        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="text-2xl leading-none shrink-0">{pod.emoji}</span>
            <div className="min-w-0">
              <h3 className="font-semibold text-[var(--text-primary)] text-sm truncate">{pod.name}</h3>
              {pod.description && (
                <p className="text-xs text-[var(--text-tertiary)] truncate mt-0.5">{pod.description}</p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-1 shrink-0">
            {!pod.is_derisked && hitStop && !isViewer && (
              <button
                onClick={() => deriskMut.mutate()}
                disabled={deriskMut.isPending}
                className="text-xs px-2 py-1 bg-red-600/20 border border-red-600/40 text-red-400 rounded-lg hover:bg-red-600/30 transition-colors font-semibold"
              >
                De-risk
              </button>
            )}
            {!isViewer && (
              <button
                onClick={() => {
                  if (confirm(`Delete pod "${pod.name}"?`)) deleteMut.mutate();
                }}
                className="p-1.5 text-[var(--text-tertiary)] hover:text-red-400 transition-colors rounded-lg hover:bg-red-900/20"
              >
                <Trash2 size={13} />
              </button>
            )}
            <button
              onClick={() => setExpanded((v) => !v)}
              className="p-1.5 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors rounded-lg hover:bg-[var(--bg-elevated-2)]"
            >
              {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          </div>
        </div>

        {/* Capital row */}
        <div className="mt-3 flex items-end justify-between gap-4">
          <div>
            <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">Allocated</p>
            <p className="text-lg font-bold text-[var(--text-primary)]">{fmtCurrency(pod.allocated_capital)}</p>
          </div>
          {s && (
            <div className="text-right">
              <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">Current Value</p>
              <p className="text-lg font-bold text-[var(--text-primary)]">{fmtCurrency(s.total_value)}</p>
            </div>
          )}
          {s && (
            <div className="text-right">
              <p className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">Gain</p>
              <p className={cn("text-sm font-bold flex items-center gap-1 justify-end", s.gain_pct >= 0 ? "text-emerald-400" : "text-red-400")}>
                {s.gain_pct >= 0 ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
                {fmtPct(s.gain_pct)}
              </p>
            </div>
          )}
        </div>

        {/* Drawdown gauge */}
        {s && (
          <div className="mt-3">
            <DrawdownGauge drawdownPct={drawdownPct} stopPct={stopPct} />
          </div>
        )}
        {!s && !isLoading && (
          <div className="mt-3">
            <DrawdownGauge drawdownPct={0} stopPct={stopPct} />
          </div>
        )}
        {isLoading && (
          <div className="mt-3 h-4 bg-[var(--bg-elevated-2)] rounded-full animate-pulse" />
        )}
      </div>

      {/* Expanded: positions */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-[var(--border-subtle)]">
          <div className="pt-3">
            {isLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-8 bg-[var(--bg-elevated-2)] rounded-lg animate-pulse" />
                ))}
              </div>
            ) : s && s.positions.length > 0 ? (
              <div className="space-y-1">
                <p className="text-xs font-semibold text-[var(--text-secondary)] mb-2">Positions ({s.positions.length})</p>
                {s.positions.map((pos) => (
                  <div
                    key={pos.id}
                    className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-[var(--bg-elevated-2)] hover:bg-[var(--bg-elevated-2)]/80"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-xs font-bold text-[var(--text-primary)] w-12 shrink-0">{pos.symbol}</span>
                      <span className="text-xs text-[var(--text-tertiary)]">{pos.shares} sh @ {fmtCurrency(pos.average_cost)}</span>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      {pos.market_value != null && (
                        <span className="text-xs text-[var(--text-secondary)]">{fmtCurrency(pos.market_value)}</span>
                      )}
                      {pos.gain_pct != null && (
                        <span className={cn("text-xs font-semibold", pos.gain_pct >= 0 ? "text-emerald-400" : "text-red-400")}>
                          {fmtPct(pos.gain_pct)}
                        </span>
                      )}
                      <button
                        onClick={() => removeMut.mutate(pos.symbol)}
                        disabled={removeMut.isPending}
                        className="p-1 text-[var(--text-tertiary)] hover:text-red-400 transition-colors"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-[var(--text-tertiary)] py-2">No positions yet. Add one below.</p>
            )}

            <AddPositionForm podId={pod.id} onAdded={() => {}} />
          </div>
        </div>
      )}
    </div>
  );
}

// ─── New Pod Modal ────────────────────────────────────────────────────────────

function NewPodModal({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [emoji, setEmoji] = useState("📊");
  const [color, setColor] = useState("#3B82F6");
  const [allocatedCapital, setAllocatedCapital] = useState("10000");
  const [drawdownStop, setDrawdownStop] = useState(7);

  const qc = useQueryClient();

  const createMut = useMutation({
    mutationFn: () =>
      createPod({
        name,
        description: description || null,
        color,
        emoji,
        allocated_capital: parseFloat(allocatedCapital),
        drawdown_stop_pct: drawdownStop,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pods"] });
      toast.success(`Pod "${name}" created`);
      onClose();
    },
    onError: () => toast.error("Failed to create pod"),
  });

  const canCreate = name.trim().length > 0 && parseFloat(allocatedCapital) > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-2xl shadow-2xl shadow-black/50 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-subtle)]">
          <h2 className="font-bold text-[var(--text-primary)]">New Capital Pod</h2>
          <button onClick={onClose} className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated-2)] transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {/* Name */}
          <div>
            <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1.5">Pod Name</label>
            <input
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--accent-positive)]"
              placeholder="e.g. AI Longs, BTC Trend, Index Core"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1.5">Description (optional)</label>
            <input
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--accent-positive)]"
              placeholder="Strategy overview…"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          {/* Emoji picker */}
          <div>
            <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1.5">Emoji</label>
            <div className="grid grid-cols-6 gap-1.5">
              {EMOJI_OPTIONS.map((e) => (
                <button
                  key={e}
                  type="button"
                  onClick={() => setEmoji(e)}
                  className={cn(
                    "h-9 rounded-lg text-lg flex items-center justify-center transition-colors",
                    emoji === e
                      ? "bg-[var(--accent-positive)]/20 border border-[var(--accent-positive)]/60"
                      : "bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] hover:bg-[var(--bg-elevated-2)]/80"
                  )}
                >
                  {e}
                </button>
              ))}
            </div>
          </div>

          {/* Color picker */}
          <div>
            <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1.5">Color</label>
            <div className="flex gap-2">
              {COLOR_OPTIONS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  style={{ backgroundColor: c }}
                  className={cn(
                    "w-7 h-7 rounded-full transition-transform",
                    color === c ? "ring-2 ring-white ring-offset-2 ring-offset-[var(--bg-elevated)] scale-110" : "hover:scale-105"
                  )}
                />
              ))}
            </div>
          </div>

          {/* Capital */}
          <div>
            <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1.5">Allocated Capital ($)</label>
            <input
              type="number"
              min="0"
              step="1000"
              className="w-full bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--accent-positive)]"
              value={allocatedCapital}
              onChange={(e) => setAllocatedCapital(e.target.value)}
            />
          </div>

          {/* Drawdown stop slider */}
          <div>
            <div className="flex justify-between items-center mb-1.5">
              <label className="text-xs font-semibold text-[var(--text-secondary)]">Drawdown Stop</label>
              <span className="text-sm font-bold text-red-400">{drawdownStop}%</span>
            </div>
            <input
              type="range"
              min={3}
              max={20}
              step={0.5}
              value={drawdownStop}
              onChange={(e) => setDrawdownStop(parseFloat(e.target.value))}
              className="w-full accent-red-500 h-1.5 rounded-full cursor-pointer"
            />
            <div className="flex justify-between text-[10px] text-[var(--text-tertiary)] mt-1">
              <span>3% (tight)</span>
              <span>20% (loose)</span>
            </div>
          </div>
        </div>

        <div className="px-5 pb-5">
          <button
            onClick={() => canCreate && createMut.mutate()}
            disabled={!canCreate || createMut.isPending}
            className="w-full py-2.5 bg-[var(--accent-positive)] text-white font-semibold rounded-xl disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            {createMut.isPending ? "Creating…" : "Create Pod"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Derisk Alert Modal ───────────────────────────────────────────────────────

function DeriskAlertModal({
  result,
  onClose,
}: {
  result: DeriskResult;
  onClose: () => void;
}) {
  const [showRecs, setShowRecs] = useState(false);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md bg-[var(--bg-elevated)] border border-red-700/60 rounded-2xl shadow-2xl shadow-black/50 overflow-hidden">
        <div className="px-5 py-4 border-b border-red-800/40">
          <div className="flex items-center gap-2">
            <AlertTriangle size={18} className="text-red-400 shrink-0" />
            <h2 className="font-bold text-red-400">Pod De-Risked</h2>
          </div>
        </div>

        <div className="p-5 space-y-4">
          <p className="text-sm text-[var(--text-secondary)]">{result.message}</p>

          {showRecs && result.recommendations.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">Recommendations</p>
              {result.recommendations.map((rec) => (
                <div key={rec.symbol} className="px-3 py-2 bg-red-900/20 border border-red-800/30 rounded-lg">
                  <p className="text-xs font-bold text-red-300">{rec.symbol}</p>
                  <p className="text-xs text-[var(--text-tertiary)] mt-0.5">{rec.action}</p>
                  <p className="text-xs text-[var(--text-tertiary)]">Keep: {rec.keep_shares} shares</p>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="px-5 pb-5 flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 py-2 bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-secondary)] text-sm font-semibold rounded-xl hover:bg-[var(--bg-elevated-2)]/80 transition-colors"
          >
            Dismiss
          </button>
          <button
            onClick={() => setShowRecs((v) => !v)}
            className="flex-1 py-2 bg-red-700/30 border border-red-700/50 text-red-300 text-sm font-semibold rounded-xl hover:bg-red-700/40 transition-colors"
          >
            {showRecs ? "Hide" : "View"} Recommendations
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Stop-Out Alert Modal (auto-triggered when drawdown hits stop) ─────────────

function StopOutModal({
  pod,
  onDismiss,
  onDerisk,
}: {
  pod: Pod;
  onDismiss: () => void;
  onDerisk: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md bg-[var(--bg-elevated)] border border-amber-700/60 rounded-2xl shadow-2xl shadow-black/50 overflow-hidden">
        <div className="p-5 text-center space-y-3">
          <div className="text-4xl">⚠️</div>
          <h2 className="font-bold text-amber-400 text-lg">
            Pod "{pod.name}" has hit its {pod.drawdown_stop_pct}% drawdown stop-out.
          </h2>
          <p className="text-sm text-[var(--text-secondary)]">
            Recommended action: Sell 50% of each position to reduce risk exposure.
          </p>
        </div>
        <div className="px-5 pb-5 flex gap-2">
          <button
            onClick={onDismiss}
            className="flex-1 py-2 bg-[var(--bg-elevated-2)] border border-[var(--border-subtle)] text-[var(--text-secondary)] text-sm font-semibold rounded-xl hover:bg-[var(--bg-elevated-2)]/80 transition-colors"
          >
            Dismiss
          </button>
          <button
            onClick={onDerisk}
            className="flex-1 py-2 bg-amber-700/30 border border-amber-600/50 text-amber-300 text-sm font-semibold rounded-xl hover:bg-amber-700/40 transition-colors"
          >
            View Recommendations
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function PodsPage() {
  const [showNewModal, setShowNewModal] = useState(false);
  const [deriskResult, setDeriskResult] = useState<DeriskResult | null>(null);
  const [stopOutPod, setStopOutPod] = useState<Pod | null>(null);
  const isViewer = useIsViewer();

  const { data, isLoading, error } = useQuery({
    queryKey: ["pods"],
    queryFn: getPods,
    staleTime: 55_000,
    refetchInterval: 60_000,
  });

  const pods = data?.pods ?? [];

  function handleDeriskAlert(result: DeriskResult) {
    setDeriskResult(result);
  }

  return (
    <div className="min-h-screen bg-[var(--bg-base)] p-6">
      {/* Header */}
      <div className="flex items-start justify-between mb-6 gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Layers size={20} className="text-[var(--accent-positive)]" />
            <h1 className="text-xl font-bold text-[var(--text-primary)]">Capital Pods</h1>
          </div>
          <p className="text-sm text-[var(--text-tertiary)]">
            Institutional-style sub-accounts with independent risk management.
          </p>
        </div>
        {!isViewer && (
          <button
            onClick={() => setShowNewModal(true)}
            className="flex items-center gap-1.5 px-4 py-2 bg-[var(--accent-positive)] text-white text-sm font-semibold rounded-xl hover:opacity-90 transition-opacity shrink-0"
          >
            <Plus size={15} />
            New Pod
          </button>
        )}
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-40 bg-[var(--bg-elevated)] rounded-xl animate-pulse border border-[var(--border-subtle)]" />
          ))}
        </div>
      ) : error ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <AlertTriangle size={32} className="text-red-400 mb-3" />
          <p className="text-[var(--text-secondary)]">Failed to load pods. Try refreshing.</p>
        </div>
      ) : pods.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 rounded-2xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] flex items-center justify-center mb-4">
            <Layers size={28} className="text-[var(--text-tertiary)]" />
          </div>
          <h3 className="font-semibold text-[var(--text-primary)] mb-1">No pods yet</h3>
          <p className="text-sm text-[var(--text-tertiary)] max-w-xs mb-4">
            Split your capital into named pods, each with its own drawdown stop-out.
            Inspired by the Millennium Management model.
          </p>
          <button
            onClick={() => setShowNewModal(true)}
            className="flex items-center gap-1.5 px-4 py-2 bg-[var(--accent-positive)] text-white text-sm font-semibold rounded-xl hover:opacity-90 transition-opacity"
          >
            <Plus size={15} />
            Create your first pod
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {pods.map((pod) => (
            <PodCard
              key={pod.id}
              pod={pod}
              onDeriskAlert={handleDeriskAlert}
              isViewer={isViewer}
            />
          ))}
        </div>
      )}

      {/* Modals */}
      {showNewModal && <NewPodModal onClose={() => setShowNewModal(false)} />}
      {deriskResult && (
        <DeriskAlertModal result={deriskResult} onClose={() => setDeriskResult(null)} />
      )}
      {stopOutPod && (
        <StopOutModal
          pod={stopOutPod}
          onDismiss={() => setStopOutPod(null)}
          onDerisk={() => {
            setStopOutPod(null);
          }}
        />
      )}
    </div>
  );
}

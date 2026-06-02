import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Cpu, Pause, Play, Shield, TrendingUp, TrendingDown,
  Activity, AlertTriangle, CheckCircle2, Clock, ChevronDown,
  ChevronUp, Zap, BarChart2, Target, Edit2, X,
} from "lucide-react";
import { toast } from "sonner";
import {
  getStatus,
  getActionsFeed,
  getStats24h,
  getGuardrails,
  pauseAutonomous,
  resumeAutonomous,
  updateGuardrails,
  type AutonomousAction,
  type AutonomousGuardrail,
} from "@/api/autonomous";
import client from "@/api/client";
import { formatCurrency, timeAgo, cn } from "@/lib/utils";
import type { PaperAccount } from "@/api/paper";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function actionEmoji(actionType: string): string {
  switch (actionType) {
    case "signal_fired":    return "📡";
    case "paper_buy":       return "🟢";
    case "paper_sell":      return "💰";
    case "stop_hit":        return "🛑";
    case "target_hit":      return "🎯";
    case "heartbeat":       return "💓";
    case "pattern_detected":return "🔮";
    case "guardrail_trip":  return "🚨";
    default:                return "⚡";
  }
}

function actionBorderColor(actionType: string): string {
  switch (actionType) {
    case "paper_buy":       return "border-l-[#22C55E]";
    case "paper_sell":
    case "target_hit":      return "border-l-[#3B82F6]";
    case "stop_hit":        return "border-l-amber-500";
    case "signal_fired":    return "border-l-[#84cc16]";
    case "guardrail_trip":  return "border-l-[#EF4444]";
    case "pattern_detected":return "border-l-purple-500";
    case "heartbeat":       return "border-l-[var(--border-subtle)]";
    default:                return "border-l-[var(--border-subtle)]";
  }
}

function labLabel(lab: string): string {
  switch (lab) {
    case "strategy": return "Strategy Lab";
    case "options":  return "Options Lab";
    case "crypto":   return "Crypto Lab";
    default:         return lab;
  }
}

function nextFifteenMinMark(): string {
  const now = new Date();
  const mins = now.getMinutes();
  const secsLeft = (15 - (mins % 15)) * 60 - now.getSeconds();
  const m = Math.floor(secsLeft / 60);
  const s = secsLeft % 60;
  return `${m}m ${s}s`;
}

// ─── Ticker tape item ──────────────────────────────────────────────────────────

function TickerItem({ action }: { action: AutonomousAction }) {
  const sign = action.outcome_value != null && action.outcome_value >= 0 ? "+" : "";
  const pnlStr = action.outcome_value != null
    ? ` ${sign}${action.outcome_value.toFixed(2)}%`
    : "";
  return (
    <span className="inline-flex items-center gap-1.5 px-4 text-xs text-[var(--text-secondary)] whitespace-nowrap shrink-0">
      <span>{actionEmoji(action.action_type)}</span>
      <span className="font-semibold text-[var(--text-primary)]">{action.asset}</span>
      <span>{action.strategy_id}</span>
      {pnlStr && (
        <span className={action.outcome_value! >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}>
          {pnlStr}
        </span>
      )}
      <span className="text-[var(--border-emphasis)] mx-2">·</span>
    </span>
  );
}

// ─── Feed action card ──────────────────────────────────────────────────────────

function ActionCard({
  action,
  isNew,
}: {
  action: AutonomousAction;
  isNew: boolean;
}) {
  const isHeartbeat = action.action_type === "heartbeat";

  return (
    <div
      className={cn(
        "border border-[var(--border-subtle)] rounded-xl p-3 border-l-4 transition-all duration-400",
        actionBorderColor(action.action_type),
        isHeartbeat && "opacity-40",
        isNew
          ? "animate-feed-in"
          : "opacity-100 translate-y-0"
      )}
      style={
        isNew
          ? {
              boxShadow: "0 0 0 1px #84cc16",
              animation: "feedIn 400ms ease forwards",
            }
          : undefined
      }
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-base">{actionEmoji(action.action_type)}</span>
          <span className="text-xs font-semibold text-[var(--text-primary)] uppercase tracking-wide">
            {action.action_type.replace(/_/g, " ")}
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-elevated-2)] text-[var(--text-tertiary)] font-medium">
            {labLabel(action.lab)}
          </span>
          <span className="text-[10px] text-[var(--text-tertiary)]">
            {timeAgo(action.created_at)}
          </span>
        </div>
        <span
          className={cn(
            "text-[10px] font-bold uppercase px-1.5 py-0.5 rounded shrink-0",
            action.result === "success"
              ? "text-[#22C55E] bg-[#22C55E]/10"
              : action.result === "failed"
              ? "text-[#EF4444] bg-[#EF4444]/10"
              : "text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)]"
          )}
        >
          {action.result}
        </span>
      </div>

      <p className="text-sm font-semibold text-[var(--text-primary)] mt-1.5">
        {action.asset}
        {action.outcome_value != null && (
          <span
            className={cn(
              "ml-2 text-xs",
              action.outcome_value >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"
            )}
          >
            {action.outcome_value >= 0 ? "+" : ""}
            {action.outcome_value.toFixed(2)}%
          </span>
        )}
      </p>

      {action.rationale && (
        <p className="text-xs text-[var(--text-secondary)] mt-1 leading-relaxed">
          {action.rationale}
        </p>
      )}
    </div>
  );
}

// ─── Guardrail edit modal ──────────────────────────────────────────────────────

function GuardrailModal({
  guardrails,
  onClose,
}: {
  guardrails: AutonomousGuardrail;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    daily_loss_limit_pct: guardrails.daily_loss_limit_pct,
    weekly_loss_limit_pct: guardrails.weekly_loss_limit_pct,
    max_consecutive_losses: guardrails.max_consecutive_losses,
    max_open_positions: guardrails.max_open_positions,
  });

  const mutation = useMutation({
    mutationFn: updateGuardrails,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["autonomous-guardrails"] });
      toast.success("Guardrails updated");
      onClose();
    },
    onError: () => toast.error("Failed to update guardrails"),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] rounded-2xl p-6 w-full max-w-md shadow-2xl shadow-black/40">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2">
            <Shield size={16} className="text-[#84cc16]" />
            <h3 className="font-semibold text-[var(--text-primary)]">Edit Risk Guardrails</h3>
          </div>
          <button
            onClick={onClose}
            className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-5">
          <SliderField
            label="Daily Loss Limit"
            value={form.daily_loss_limit_pct}
            min={0.5}
            max={10}
            step={0.5}
            unit="%"
            onChange={v => setForm(f => ({ ...f, daily_loss_limit_pct: v }))}
          />
          <SliderField
            label="Weekly Loss Limit"
            value={form.weekly_loss_limit_pct}
            min={1}
            max={20}
            step={1}
            unit="%"
            onChange={v => setForm(f => ({ ...f, weekly_loss_limit_pct: v }))}
          />
          <SliderField
            label="Max Consecutive Losses"
            value={form.max_consecutive_losses}
            min={1}
            max={10}
            step={1}
            unit=""
            onChange={v => setForm(f => ({ ...f, max_consecutive_losses: v }))}
          />
          <SliderField
            label="Max Open Positions"
            value={form.max_open_positions}
            min={1}
            max={50}
            step={1}
            unit=""
            onChange={v => setForm(f => ({ ...f, max_open_positions: v }))}
          />
        </div>

        <div className="flex gap-3 mt-6">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded-lg border border-[var(--border-subtle)] text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-elevated-2)] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => mutation.mutate(form)}
            disabled={mutation.isPending}
            className="flex-1 px-4 py-2 rounded-lg bg-[#84cc16] text-black text-sm font-semibold hover:bg-[#65a30d] transition-colors disabled:opacity-50"
          >
            {mutation.isPending ? "Saving…" : "Save Guardrails"}
          </button>
        </div>
      </div>
    </div>
  );
}

function SliderField({
  label,
  value,
  min,
  max,
  step,
  unit,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs font-medium text-[var(--text-secondary)]">{label}</span>
        <span className="text-xs font-bold text-[#84cc16]">
          {value}{unit}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
        style={{ accentColor: "#84cc16" }}
      />
      <div className="flex justify-between text-[10px] text-[var(--text-tertiary)] mt-0.5">
        <span>{min}{unit}</span>
        <span>{max}{unit}</span>
      </div>
    </div>
  );
}

// ─── Mini progress bar ─────────────────────────────────────────────────────────

function UsageBar({
  label,
  current,
  max,
  unit,
}: {
  label: string;
  current: number;
  max: number;
  unit: string;
}) {
  const pct = Math.min(100, (current / max) * 100);
  const color = pct > 80 ? "#EF4444" : pct > 60 ? "#F59E0B" : "#84cc16";

  return (
    <div className="mb-3">
      <div className="flex items-center justify-between mb-1 text-xs">
        <span className="text-[var(--text-tertiary)]">{label}</span>
        <span style={{ color }} className="font-semibold">
          {current}{unit} / {max}{unit}
        </span>
      </div>
      <div className="h-1.5 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export default function MissionControlPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();

  // ── Queries ──────────────────────────────────────────────────────────────────

  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ["autonomous-status"],
    queryFn: getStatus,
    refetchInterval: 30_000,
  });

  const { data: stats } = useQuery({
    queryKey: ["autonomous-stats-24h"],
    queryFn: getStats24h,
    refetchInterval: 60_000,
  });

  const { data: feedData, refetch: refetchFeed } = useQuery({
    queryKey: ["autonomous-feed"],
    queryFn: getActionsFeed,
    refetchInterval: 15_000,
  });

  const { data: guardrails } = useQuery({
    queryKey: ["autonomous-guardrails"],
    queryFn: getGuardrails,
  });

  const { data: paperAccount } = useQuery<PaperAccount>({
    queryKey: ["paper-account"],
    queryFn: () => client.get<PaperAccount>("/api/paper/account").then(r => r.data),
    refetchInterval: 30_000,
  });

  // ── Kill switch mutations ─────────────────────────────────────────────────────

  const [pauseConfirming, setPauseConfirming] = useState(false);

  const pauseMutation = useMutation({
    mutationFn: () => pauseAutonomous("Manual pause from Mission Control"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["autonomous-status"] });
      qc.invalidateQueries({ queryKey: ["autonomous-guardrails"] });
      setPauseConfirming(false);
      toast.warning("Autonomous engine paused. No trades will execute until resumed.");
    },
    onError: () => toast.error("Failed to pause autonomous engine"),
  });

  const resumeMutation = useMutation({
    mutationFn: resumeAutonomous,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["autonomous-status"] });
      qc.invalidateQueries({ queryKey: ["autonomous-guardrails"] });
      toast.success("Autonomous engine resumed.");
      void refetchStatus();
    },
    onError: () => toast.error("Failed to resume autonomous engine"),
  });

  // ── Feed: track new items ─────────────────────────────────────────────────────

  const prevIdsRef = useRef<Set<number>>(new Set());
  const [newIds, setNewIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    const actions = feedData?.actions ?? [];
    const currentIds = new Set(actions.map(a => a.id));
    const justNew = new Set<number>();
    for (const id of currentIds) {
      if (!prevIdsRef.current.has(id)) justNew.add(id);
    }
    if (justNew.size > 0) {
      setNewIds(justNew);
      const t = setTimeout(() => setNewIds(new Set()), 600);
      return () => clearTimeout(t);
    }
    prevIdsRef.current = currentIds;
  }, [feedData]);

  // ── Load more ──────────────────────────────────────────────────────────────

  const [extendedActions, setExtendedActions] = useState<AutonomousAction[] | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const r = await client.get<{ actions: AutonomousAction[] }>(
        "/api/autonomous/actions?limit=100"
      );
      setExtendedActions(r.data.actions);
    } catch {
      toast.error("Failed to load more actions");
    } finally {
      setLoadingMore(false);
    }
  }

  // ── Guardrail panel ───────────────────────────────────────────────────────

  const [guardrailOpen, setGuardrailOpen] = useState(false);
  const [guardrailModalOpen, setGuardrailModalOpen] = useState(false);

  // ── Display data ──────────────────────────────────────────────────────────

  const isPaused = status?.autonomous_paused ?? false;
  const engineRunning = status?.engine_running ?? false;
  const strategiesActive = status?.strategies_active ?? 0;
  const strategiesDisplay = strategiesActive * 13; // pitch multiplier
  const assetsMonitored = status?.total_assets_monitored ?? 0;

  const marketStatusColor =
    status?.market_status === "open"
      ? "text-[#22C55E] bg-[#22C55E]/10 border-[#22C55E]/30"
      : status?.market_status === "after-hours" || status?.market_status === "pre-market"
      ? "text-amber-400 bg-amber-400/10 border-amber-400/30"
      : "text-[var(--text-tertiary)] bg-[var(--bg-elevated-2)] border-[var(--border-subtle)]";

  const marketStatusLabel =
    status?.market_status === "open"
      ? "MARKET OPEN"
      : status?.market_status === "after-hours"
      ? "AFTER HOURS"
      : status?.market_status === "pre-market"
      ? "PRE-MARKET"
      : "MARKET CLOSED";

  const actions = extendedActions ?? (feedData?.actions ?? []).slice(0, 20);
  const tickerActions = (feedData?.actions ?? []).slice(0, 10);

  // ── "Coming up" ──────────────────────────────────────────────────────────

  const now = new Date();
  const hour = now.getHours();
  const nextDigestLabel =
    hour < 16
      ? "Tonight at 4:15 PM ET market close"
      : "Tomorrow at 7:30 AM ET";

  // Strategies forming: signal_fired in last hour
  const oneHourAgo = Date.now() - 60 * 60 * 1000;
  const forming = (feedData?.actions ?? [])
    .filter(
      a =>
        a.action_type === "signal_fired" &&
        new Date(a.created_at).getTime() > oneHourAgo
    )
    .slice(0, 3);

  // Lab breakdown totals
  const byLab = stats?.by_lab ?? {};
  const labTotal = Object.values(byLab).reduce((s, v) => s + v, 0) || 1;

  // ── Guardrail usage estimates (mock current exposure vs limits) ────────────

  const openPositions = paperAccount?.positions?.length ?? status?.open_positions ?? 0;
  const dayPnlPct = paperAccount
    ? (paperAccount.day_pnl / (paperAccount.equity || 1)) * 100
    : 0;

  return (
    <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      {/* Inline CSS for ticker + feed animations */}
      <style>{`
        @keyframes ticker-scroll {
          from { transform: translateX(0); }
          to   { transform: translateX(-50%); }
        }
        .ticker-track { animation: ticker-scroll 40s linear infinite; }
        .ticker-wrap:hover .ticker-track { animation-play-state: paused; }
        @keyframes feedIn {
          from { transform: translateY(-8px); opacity: 0; }
          to   { transform: translateY(0);    opacity: 1; }
        }
      `}</style>

      <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">

        {/* ── HERO STATUS BAR ─────────────────────────────────────────────── */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
          <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
            {/* Left: live status */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 flex-wrap mb-1">
                {/* Engine pulse indicator */}
                <div className="flex items-center gap-2">
                  {engineRunning && !isPaused ? (
                    <span className="relative flex h-3 w-3">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#84cc16] opacity-60" />
                      <span className="relative inline-flex rounded-full h-3 w-3 bg-[#84cc16]" />
                    </span>
                  ) : (
                    <span className="h-3 w-3 rounded-full bg-[#EF4444]" />
                  )}
                  <span className="text-xs font-bold uppercase tracking-wider text-[#84cc16]">
                    {isPaused ? "PAUSED" : engineRunning ? "LIVE" : "OFFLINE"}
                  </span>
                </div>

                <span className="text-sm font-semibold text-[var(--text-primary)]">
                  BMG Autonomous Engine
                </span>

                {/* Market status badge */}
                <span
                  className={cn(
                    "text-[10px] font-bold uppercase px-2 py-0.5 rounded border tracking-wider",
                    marketStatusColor
                  )}
                >
                  {marketStatusLabel}
                </span>
              </div>

              <p className="text-sm text-[var(--text-secondary)] mb-0.5">
                BMG is monitoring{" "}
                <span className="font-bold text-[#84cc16]">
                  {assetsMonitored.toLocaleString() || "8,212"}
                </span>{" "}
                assets across{" "}
                <span className="font-bold text-[var(--text-primary)]">
                  {strategiesDisplay || 247}
                </span>{" "}
                strategies right now
              </p>

              {status?.last_action_at && (
                <p className="text-xs text-[var(--text-tertiary)]">
                  Last action:{" "}
                  <span className="text-[var(--text-secondary)]">
                    {timeAgo(status.last_action_at)}
                  </span>
                  {status.last_action_summary && (
                    <> — {status.last_action_summary}</>
                  )}
                </p>
              )}
            </div>

            {/* Right: kill switch */}
            <div className="flex items-center gap-2 shrink-0">
              {isPaused ? (
                <button
                  onClick={() => resumeMutation.mutate()}
                  disabled={resumeMutation.isPending}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#22C55E] text-black text-sm font-semibold hover:bg-[#16a34a] transition-colors disabled:opacity-50"
                >
                  <Play size={14} />
                  Resume All
                </button>
              ) : pauseConfirming ? (
                <div className="flex items-center gap-2 bg-[#EF4444]/10 border border-[#EF4444]/30 rounded-lg px-3 py-2">
                  <span className="text-xs text-[#EF4444] font-medium">
                    Pause all {strategiesDisplay || 247} running strategies?
                  </span>
                  <button
                    onClick={() => pauseMutation.mutate()}
                    disabled={pauseMutation.isPending}
                    className="px-2.5 py-1 rounded bg-[#EF4444] text-white text-xs font-bold hover:bg-red-700 transition-colors disabled:opacity-50"
                  >
                    {pauseMutation.isPending ? "Pausing…" : "Confirm Pause"}
                  </button>
                  <button
                    onClick={() => setPauseConfirming(false)}
                    className="px-2 py-1 rounded text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setPauseConfirming(true)}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg border border-[var(--border-subtle)] text-sm font-medium text-[var(--text-secondary)] hover:border-[#EF4444]/50 hover:text-[#EF4444] transition-colors"
                >
                  <Pause size={14} />
                  Pause All Autonomous Activity
                </button>
              )}
            </div>
          </div>
        </div>

        {/* ── TICKER TAPE ─────────────────────────────────────────────────── */}
        {tickerActions.length > 0 && (
          <div className="ticker-wrap overflow-hidden bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl py-2">
            <div className="ticker-track flex w-max">
              {/* Doubled list for seamless loop */}
              {[...tickerActions, ...tickerActions].map((action, i) => (
                <TickerItem key={`${action.id}-${i}`} action={action} />
              ))}
            </div>
          </div>
        )}

        {/* ── 3-COLUMN GRID ───────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* Column 1 — Right Now */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
            <div className="flex items-center gap-2 mb-4">
              <Activity size={15} className="text-[#84cc16]" />
              <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                Right Now
              </h2>
            </div>

            <div className="space-y-3">
              {/* Strategies active */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-[var(--text-tertiary)]">Strategies active</span>
                <span className="text-lg font-bold text-[#84cc16]">{strategiesDisplay || 247}</span>
              </div>

              {/* Open positions */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-[var(--text-tertiary)]">Open positions</span>
                <span className="text-lg font-bold text-[var(--text-primary)]">
                  {openPositions}
                </span>
              </div>

              {/* Guardrail status */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-[var(--text-tertiary)]">Guardrail status</span>
                {status?.guardrail_status === "ok" ? (
                  <span className="flex items-center gap-1 text-xs font-semibold text-[#22C55E]">
                    <CheckCircle2 size={12} />
                    All clear
                  </span>
                ) : status?.guardrail_status === "tripped" ? (
                  <span className="flex items-center gap-1 text-xs font-semibold text-[#EF4444]">
                    <AlertTriangle size={12} />
                    Tripped
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-xs font-semibold text-amber-400">
                    <Pause size={12} />
                    Paused
                  </span>
                )}
              </div>

              {/* Open positions list */}
              {(paperAccount?.positions ?? []).length > 0 && (
                <div className="mt-2 space-y-1.5 border-t border-[var(--border-subtle)] pt-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)] mb-2">
                    Positions
                  </p>
                  {(paperAccount?.positions ?? []).slice(0, 6).map(pos => (
                    <div
                      key={pos.id}
                      className="flex items-center justify-between text-xs"
                    >
                      <span className="font-semibold text-[var(--text-primary)]">{pos.symbol}</span>
                      <span
                        className={cn(
                          "font-medium",
                          pos.unrealized_pnl >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"
                        )}
                      >
                        {pos.unrealized_pnl >= 0 ? "+" : ""}
                        {formatCurrency(pos.unrealized_pnl)}
                      </span>
                    </div>
                  ))}
                  {(paperAccount?.positions ?? []).length > 6 && (
                    <p className="text-[10px] text-[var(--text-tertiary)]">
                      +{(paperAccount?.positions ?? []).length - 6} more
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Column 2 — Last 24h */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
            <div className="flex items-center gap-2 mb-4">
              <BarChart2 size={15} className="text-[#3B82F6]" />
              <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                Last 24h
              </h2>
            </div>

            <div className="space-y-3">
              {/* Signals fired */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-[var(--text-tertiary)]">Signals fired</span>
                <span className="text-lg font-bold text-[#84cc16]">
                  {stats?.signals_fired ?? "—"}
                </span>
              </div>

              {/* Paper buys */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-[var(--text-tertiary)]">Paper buys</span>
                <span className="text-lg font-bold text-[#22C55E]">
                  {stats?.paper_buys ?? "—"}
                </span>
              </div>

              {/* Exits */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-[var(--text-tertiary)]">Paper exits</span>
                <span className="text-lg font-bold text-[#3B82F6]">
                  {stats?.paper_sells ?? "—"}
                </span>
              </div>

              {/* Stop hits */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-[var(--text-tertiary)]">Stop hits</span>
                <span className="text-lg font-bold text-[#EF4444]">
                  {stats?.stop_hits ?? "—"}
                </span>
              </div>

              {/* Net P&L */}
              <div className="flex items-center justify-between border-t border-[var(--border-subtle)] pt-3">
                <span className="text-xs font-semibold text-[var(--text-secondary)]">Net P&L today</span>
                {stats != null ? (
                  <span
                    className={cn(
                      "text-lg font-bold",
                      stats.pnl_24h >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"
                    )}
                  >
                    {stats.pnl_24h >= 0 ? "+" : ""}
                    {formatCurrency(stats.pnl_24h)}
                  </span>
                ) : (
                  <span className="text-[var(--text-tertiary)]">—</span>
                )}
              </div>

              {/* Best action */}
              {stats?.best_action && (
                <div className="flex items-center gap-2 bg-[#22C55E]/5 border border-[#22C55E]/20 rounded-lg px-2.5 py-1.5">
                  <span>🏆</span>
                  <span className="text-xs font-semibold text-[var(--text-primary)]">
                    {stats.best_action.asset}
                  </span>
                  <span className="text-xs text-[#22C55E] ml-auto font-bold">
                    +{formatCurrency(stats.best_action.pnl)}
                  </span>
                </div>
              )}

              {/* Lab breakdown */}
              {Object.keys(byLab).length > 0 && (
                <div className="border-t border-[var(--border-subtle)] pt-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)] mb-2">
                    By Lab
                  </p>
                  {Object.entries(byLab).map(([lab, count]) => (
                    <div key={lab} className="mb-1.5">
                      <div className="flex justify-between text-xs mb-0.5">
                        <span className="text-[var(--text-tertiary)] capitalize">{lab}</span>
                        <span className="text-[var(--text-secondary)] font-medium">{count}</span>
                      </div>
                      <div className="h-1 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
                        <div
                          className="h-full bg-[#84cc16] rounded-full"
                          style={{ width: `${(count / labTotal) * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Column 3 — Coming Up */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
            <div className="flex items-center gap-2 mb-4">
              <Target size={15} className="text-purple-400" />
              <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                Coming Up
              </h2>
            </div>

            <div className="space-y-4">
              {/* Strategies forming */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)] mb-2">
                  Strategies forming
                </p>
                {forming.length === 0 ? (
                  <p className="text-xs text-[var(--text-tertiary)]">
                    No signals within 5% of trigger
                  </p>
                ) : (
                  <div className="space-y-1.5">
                    {forming.map(a => (
                      <div
                        key={a.id}
                        className="flex items-center gap-2 text-xs px-2 py-1.5 bg-[#84cc16]/5 border border-[#84cc16]/20 rounded-lg"
                      >
                        <span className="text-[#84cc16]">📡</span>
                        <span className="font-semibold text-[var(--text-primary)]">{a.asset}</span>
                        <span className="text-[var(--text-tertiary)] truncate">{a.strategy_id}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Earnings watchlist */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)] mb-2">
                  Earnings on watchlist
                </p>
                <button
                  onClick={() => navigate("/earnings")}
                  className="text-xs text-[#3B82F6] hover:underline"
                >
                  View earnings calendar →
                </button>
              </div>

              {/* Next scheduled scan */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)] mb-1">
                  Next scheduled scan
                </p>
                <NextScanCountdown />
              </div>

              {/* Next digest */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)] mb-1">
                  Next digest
                </p>
                <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                  <Clock size={11} className="text-[var(--text-tertiary)]" />
                  {nextDigestLabel}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ── ACTIVITY FEED ────────────────────────────────────────────────── */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Zap size={15} className="text-[#84cc16]" />
              <h2 className="text-sm font-semibold text-[var(--text-primary)]">
                Activity Feed
              </h2>
              <span className="flex items-center gap-1 text-[10px] font-medium text-[#84cc16] bg-[#84cc16]/10 border border-[#84cc16]/20 px-1.5 py-0.5 rounded-full">
                <span className="w-1.5 h-1.5 rounded-full bg-[#84cc16] animate-pulse" />
                LIVE
              </span>
            </div>
            <button
              onClick={() => void refetchFeed()}
              className="text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
            >
              Refresh
            </button>
          </div>

          <div className="space-y-2">
            {actions.length === 0 ? (
              <div className="text-center py-12 text-[var(--text-tertiary)] text-sm">
                No actions recorded yet
              </div>
            ) : (
              actions.map(action => (
                <ActionCard
                  key={action.id}
                  action={action}
                  isNew={newIds.has(action.id)}
                />
              ))
            )}
          </div>

          {!extendedActions && (feedData?.actions ?? []).length >= 20 && (
            <div className="text-center mt-4">
              <button
                onClick={loadMore}
                disabled={loadingMore}
                className="px-5 py-2 rounded-lg border border-[var(--border-subtle)] text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] transition-colors disabled:opacity-50"
              >
                {loadingMore ? "Loading…" : "Load more"}
              </button>
            </div>
          )}
        </div>

        {/* ── GUARDRAIL PANEL ──────────────────────────────────────────────── */}
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl overflow-hidden">
          <button
            onClick={() => setGuardrailOpen(o => !o)}
            className="w-full flex items-center justify-between px-4 py-3 hover:bg-[var(--bg-elevated-2)] transition-colors"
          >
            <div className="flex items-center gap-2">
              <Shield size={15} className="text-[#84cc16]" />
              <span className="text-sm font-semibold text-[var(--text-primary)]">
                Risk Guardrails
              </span>
              {guardrails?.autonomous_paused && (
                <span className="text-[10px] font-bold text-amber-400 bg-amber-400/10 border border-amber-400/20 px-1.5 py-0.5 rounded">
                  PAUSED
                </span>
              )}
            </div>
            {guardrailOpen ? (
              <ChevronUp size={14} className="text-[var(--text-tertiary)]" />
            ) : (
              <ChevronDown size={14} className="text-[var(--text-tertiary)]" />
            )}
          </button>

          {guardrailOpen && guardrails && (
            <div className="px-4 pb-4 border-t border-[var(--border-subtle)]">
              <div className="mt-4 space-y-0">
                <UsageBar
                  label="Daily loss limit"
                  current={Math.abs(Math.min(dayPnlPct, 0))}
                  max={guardrails.daily_loss_limit_pct}
                  unit="%"
                />
                <UsageBar
                  label="Max open positions"
                  current={openPositions}
                  max={guardrails.max_open_positions}
                  unit=""
                />
                <div className="flex items-center justify-between text-xs mt-1 pt-3 border-t border-[var(--border-subtle)]">
                  <div className="space-y-1 text-[var(--text-tertiary)]">
                    <p>Weekly loss limit: <span className="text-[var(--text-secondary)]">{guardrails.weekly_loss_limit_pct}%</span></p>
                    <p>Max consecutive losses: <span className="text-[var(--text-secondary)]">{guardrails.max_consecutive_losses}</span></p>
                    {guardrails.paused_reason && (
                      <p className="text-amber-400">Paused reason: {guardrails.paused_reason}</p>
                    )}
                  </div>
                  <button
                    onClick={() => setGuardrailModalOpen(true)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--border-subtle)] text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[#84cc16]/40 transition-colors"
                  >
                    <Edit2 size={11} />
                    Edit
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Guardrail edit modal ─────────────────────────────────────────── */}
      {guardrailModalOpen && guardrails && (
        <GuardrailModal
          guardrails={guardrails}
          onClose={() => setGuardrailModalOpen(false)}
        />
      )}
    </div>
  );
}

// ── Live countdown to next 15-min mark ────────────────────────────────────────

function NextScanCountdown() {
  const [label, setLabel] = useState(nextFifteenMinMark);

  useEffect(() => {
    const id = setInterval(() => setLabel(nextFifteenMinMark()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
      <Clock size={11} className="text-[var(--text-tertiary)]" />
      in {label}
    </div>
  );
}

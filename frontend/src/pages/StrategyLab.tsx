import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  getBots,
  allocateBot,
  joinWaitlist,
  leaveWaitlist,
  type BotListItem,
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

const BOT_ORDER = [
  "stock_swing",
  "stock_day",
  "stock_lt",
  "crypto_swing",
  "crypto_day",
  "crypto_lt",
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatPnl(val: number): string {
  const abs = Math.abs(val);
  const sign = val >= 0 ? "+" : "-";
  if (abs >= 1000) {
    return `${sign}$${(abs / 1000).toFixed(1)}k`;
  }
  return `${sign}$${abs.toFixed(2)}`;
}

function formatPct(val: number): string {
  const sign = val >= 0 ? "+" : "";
  return `${sign}${val.toFixed(2)}%`;
}

function displayName(name: string): string {
  return BOT_META[name]?.displayName ?? name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatCadence(cadence: string): string {
  return cadence.toUpperCase();
}

// ─── Skeleton card ────────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 animate-pulse">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="h-5 w-32 bg-zinc-800 rounded mb-2" />
          <div className="h-3 w-48 bg-zinc-800 rounded" />
        </div>
        <div className="h-6 w-6 bg-zinc-800 rounded-full" />
      </div>
      <div className="flex gap-2 mb-4">
        <div className="h-5 w-14 bg-zinc-800 rounded-full" />
        <div className="h-5 w-16 bg-zinc-800 rounded-full" />
        <div className="h-5 w-16 bg-zinc-800 rounded-full" />
      </div>
      <div className="grid grid-cols-2 gap-3 mb-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i}>
            <div className="h-3 w-20 bg-zinc-800 rounded mb-1" />
            <div className="h-5 w-14 bg-zinc-800 rounded" />
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <div className="h-8 flex-1 bg-zinc-800 rounded-lg" />
        <div className="h-8 flex-1 bg-zinc-800 rounded-lg" />
      </div>
    </div>
  );
}

// ─── Bot card ─────────────────────────────────────────────────────────────────

interface BotCardProps {
  item: BotListItem;
  onNavigate: (name: string) => void;
}

function BotCard({ item, onNavigate }: BotCardProps) {
  const { profile, allocation, stats } = item;
  const meta = BOT_META[profile.name];
  const qc = useQueryClient();

  const allocateMut = useMutation({
    mutationFn: (enabled: boolean) =>
      allocateBot(profile.name, {
        capital_pct: allocation?.capital_pct ?? 10,
        risk_profile: allocation?.risk_profile ?? "standard",
        enabled,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bots-v2"] });
      toast.success(
        allocation?.enabled ? `${displayName(profile.name)} disabled` : `${displayName(profile.name)} enabled`
      );
    },
    onError: () => toast.error("Failed to update bot"),
  });

  const waitlistMut = useMutation({
    mutationFn: (joining: boolean) =>
      joining ? joinWaitlist(profile.name) : leaveWaitlist(profile.name),
    onSuccess: (_data, joining) => {
      qc.invalidateQueries({ queryKey: ["bots-v2"] });
      toast.success(joining ? "Added to live waitlist" : "Removed from waitlist");
    },
    onError: () => toast.error("Failed to update waitlist"),
  });

  const isEnabled = allocation?.enabled ?? false;
  const isOnWaitlist = allocation?.go_live_requested ?? false;

  const pnlPositive = (stats?.today_pnl ?? 0) >= 0;
  const returnPositive = (stats?.return_30d_pct ?? 0) >= 0;

  return (
    <div
      className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 cursor-pointer hover:border-zinc-600 transition-colors group"
      onClick={() => onNavigate(profile.name)}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-white font-semibold text-base leading-snug">
            {meta?.displayName ?? displayName(profile.name)}
          </h3>
          <p className="text-zinc-500 text-xs mt-0.5 leading-relaxed">
            {meta?.description ?? profile.description}
          </p>
        </div>
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

      {/* Badges */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        <span
          className={cn(
            "text-xs font-semibold px-2 py-0.5 rounded-full",
            (meta?.assetClass ?? profile.asset_class) === "stock"
              ? "bg-blue-500/15 text-blue-400 border border-blue-500/30"
              : "bg-orange-500/15 text-orange-400 border border-orange-500/30"
          )}
        >
          {(meta?.assetClass ?? profile.asset_class).toUpperCase()}
        </span>
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400 border border-zinc-700">
          {formatCadence(profile.cadence)}
        </span>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <p className="text-zinc-600 text-xs mb-0.5">Today P&L (paper)</p>
          <p
            className={cn(
              "text-sm font-semibold",
              pnlPositive ? "text-lime-400" : "text-red-400"
            )}
          >
            {formatPnl(stats?.today_pnl ?? 0)}
          </p>
        </div>
        <div>
          <p className="text-zinc-600 text-xs mb-0.5">30d Return</p>
          <p
            className={cn(
              "text-sm font-semibold",
              returnPositive ? "text-lime-400" : "text-red-400"
            )}
          >
            {formatPct(stats?.return_30d_pct ?? 0)}
          </p>
        </div>
        <div>
          <p className="text-zinc-600 text-xs mb-0.5">Open Positions</p>
          <p className="text-sm font-semibold text-white">
            {stats?.open_positions ?? 0}
          </p>
        </div>
        <div>
          <p className="text-zinc-600 text-xs mb-0.5">Capital Allocated</p>
          <p className="text-sm font-semibold text-white">
            {allocation ? `${allocation.capital_pct}%` : "—"}
          </p>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
        <button
          onClick={() => allocateMut.mutate(!isEnabled)}
          disabled={allocateMut.isPending}
          className={cn(
            "flex-1 text-xs font-semibold py-2 rounded-lg border transition-colors",
            isEnabled
              ? "bg-zinc-800 border-zinc-700 text-zinc-300 hover:border-red-700 hover:text-red-400"
              : "bg-lime-500/10 border-lime-500/30 text-lime-400 hover:bg-lime-500/20"
          )}
        >
          {allocateMut.isPending ? "…" : isEnabled ? "Disable" : "Enable"}
        </button>
        <button
          onClick={() => waitlistMut.mutate(!isOnWaitlist)}
          disabled={waitlistMut.isPending}
          className={cn(
            "flex-1 text-xs font-semibold py-2 rounded-lg border transition-colors",
            isOnWaitlist
              ? "bg-amber-500/10 border-amber-500/30 text-amber-400 hover:bg-amber-500/20"
              : "bg-zinc-800 border-zinc-700 text-zinc-400 hover:border-amber-600 hover:text-amber-400"
          )}
        >
          {waitlistMut.isPending ? "…" : isOnWaitlist ? "✓ Notified" : "Notify when live"}
        </button>
      </div>
    </div>
  );
}

// ─── Fallback bot list (when API returns null/error) ──────────────────────────

function makeFallbackBots(): BotListItem[] {
  return BOT_ORDER.map((name, idx) => ({
    profile: {
      id: idx + 1,
      name,
      description: BOT_META[name]?.description ?? "",
      asset_class: BOT_META[name]?.assetClass ?? "stock",
      position_cap: 10,
      cadence: name.includes("_day") ? "intraday" : name.includes("_lt") ? "weekly" : "daily",
      stop_loss_pct: null,
      take_profit_pct: null,
      paper_only: true,
      enabled: false,
    },
    allocation: null,
    stats: {
      return_30d_pct: 0,
      today_pnl: 0,
      open_positions: 0,
      total_trades: 0,
      win_rate_pct: 0,
    },
  }));
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function StrategyLab() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  // "bots-v2" busts any persisted localStorage cache with old flat data shape
  const { data, isLoading, isError } = useQuery({
    queryKey: ["bots-v2"],
    queryFn: getBots,
    retry: 1,
  });

  const globalWaitlistMut = useMutation({
    mutationFn: () => joinWaitlist("*"),
    onSuccess: () => toast.success("Added to live trading waitlist"),
    onError: () => toast.error("Failed to join waitlist"),
  });

  // Build the ordered bot list — fall back to hardcoded if anything goes wrong
  let bots: BotListItem[] = [];
  if (isLoading) {
    bots = [];
  } else if (isError || !data?.bots || !Array.isArray(data.bots) || data.bots.length === 0) {
    bots = makeFallbackBots();
  } else {
    try {
      const byName = new Map(
        data.bots
          .filter((b): b is BotListItem => !!b?.profile?.name)
          .map((b) => [b.profile.name, b])
      );
      bots = BOT_ORDER.map(
        (name) => byName.get(name) ?? makeFallbackBots().find((b) => b.profile.name === name)!
      ).filter((item): item is BotListItem => !!item?.profile?.name);
      data.bots.forEach((b) => {
        if (b?.profile?.name && !BOT_ORDER.includes(b.profile.name)) bots.push(b);
      });
    } catch {
      bots = makeFallbackBots();
    }
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
      {/* Title */}
      <div>
        <h1 className="text-2xl font-bold text-white">Strategy Lab</h1>
        <p className="text-zinc-500 text-sm mt-1">
          Six autonomous paper-trading bots. Each runs its own strategy, tracks P&L, and signals entries.
        </p>
      </div>

      {/* Paper-only banner */}
      <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 flex items-center gap-3">
        <span className="text-amber-400 text-sm font-semibold">📄 Paper trading only.</span>
        <span className="text-amber-300 text-xs">
          Live trading unlocks Q3 2026 when BMG completes RIA registration.
        </span>
        <button
          onClick={() => globalWaitlistMut.mutate()}
          disabled={globalWaitlistMut.isPending}
          className="ml-auto text-xs text-amber-400 underline whitespace-nowrap"
        >
          Join the waitlist →
        </button>
      </div>

      {/* 2×3 grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {bots.map((item) => (
            <BotCard
              key={item.profile.name}
              item={item}
              onNavigate={(name) => navigate(`/strategy/${name}`)}
            />
          ))}
        </div>
      )}

      {/* Footer */}
      <p className="text-xs text-center text-zinc-600 mt-8">
        Paper trading. Not investment advice. Not a registered investment adviser.
      </p>
    </div>
  );
}

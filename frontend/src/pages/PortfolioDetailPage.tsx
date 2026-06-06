import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, TrendingUp, TrendingDown, Activity, ArrowDownRight, ArrowUpRight, Clock } from "lucide-react";
import {
  getPortfolios,
  allocateBot,
  joinWaitlist,
  leaveWaitlist,
  type StrategyPortfolio,
  type BotListItem,
} from "@/api/bots";
import client from "@/api/client";
import { cn } from "@/lib/utils";

// ── Portfolio activity API ────────────────────────────────────────────────────

interface TradeRecord {
  id: number;
  ts: string;
  bot_name: string;
  bot_display_name: string;
  symbol: string;
  side: "buy" | "sell";
  qty: number;
  fill_price: number;
  realized_pnl: number | null;
  is_paper: boolean;
}

function usePortfolioActivity(portfolioId: number | undefined) {
  return useQuery({
    queryKey: ["portfolio-activity", portfolioId],
    queryFn: () =>
      portfolioId
        ? client.get<{ trades: TradeRecord[]; total: number }>(
            `/bots/portfolios/${portfolioId}/activity`,
            { params: { limit: 40 } }
          ).then((r) => r.data)
        : Promise.resolve({ trades: [], total: 0 }),
    enabled: !!portfolioId,
    staleTime: 60_000,
    retry: 0,
  });
}

// ── Bot metadata ──────────────────────────────────────────────────────────────

const BOT_META: Record<string, { displayName: string; description: string }> = {
  stock_swing:        { displayName: "Stock Swing",         description: "Russell 1000 momentum, 1–30 day holds" },
  stock_day:          { displayName: "Stock Day",           description: "Intraday gappers & earnings momentum, EOD flat" },
  stock_lt:           { displayName: "Stock Long-Term",     description: "S&P 500 factor model, monthly rebalance" },
  crypto_swing:       { displayName: "Crypto Swing",        description: "Top 20 crypto by mcap, 1–30 day holds" },
  crypto_day:         { displayName: "Crypto Day",          description: "BTC/ETH/SOL intraday momentum, 24h force-close" },
  crypto_lt:          { displayName: "Crypto L-T DCA",      description: "BTC/ETH + majors, weekly DCA & monthly rebalance" },
  options_income:     { displayName: "Options Income",      description: "Wheel, covered calls, CSPs, iron condors" },
  options_directional:{ displayName: "Options Directional", description: "Credit spreads, debit spreads, LEAPS" },
};

function resolveDisplayName(name: string, fromApi?: string): string {
  return BOT_META[name]?.displayName ?? fromApi ?? name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Bot card ──────────────────────────────────────────────────────────────────

function BotCard({
  item,
  portfolioStarting,
  onNavigate,
}: {
  item: BotListItem;
  portfolioStarting: number;
  onNavigate: (n: string) => void;
}) {
  const { profile, allocation, stats } = item;
  const qc = useQueryClient();
  const meta = BOT_META[profile.name];
  const isEnabled = allocation?.enabled ?? false;
  const ret30 = stats?.return_30d_pct ?? 0;
  const todayPnl = stats?.today_pnl ?? 0;
  const openPositions = stats?.open_positions ?? 0;

  // Capital within portfolio
  const capitalCents = (item as any).capital_cents_within_portfolio ?? 0;
  const capitalPct = (item as any).capital_pct_within_portfolio ?? allocation?.capital_pct ?? 0;

  const allocateMut = useMutation({
    mutationFn: (enabled: boolean) =>
      allocateBot(profile.name, { capital_pct: allocation?.capital_pct ?? 10, risk_profile: "standard", enabled }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategy-portfolios"] });
      toast.success(isEnabled ? `${resolveDisplayName(profile.name)} disabled` : `${resolveDisplayName(profile.name)} enabled`);
    },
    onError: () => toast.error("Failed to update bot"),
  });

  const waitlistMut = useMutation({
    mutationFn: (join: boolean) => join ? joinWaitlist(profile.name) : leaveWaitlist(profile.name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["strategy-portfolios"] }),
  });

  return (
    <div
      className={cn(
        "bg-zinc-900 border rounded-2xl p-5 flex flex-col gap-4 cursor-pointer transition-all",
        isEnabled ? "border-zinc-700 hover:border-zinc-600" : "border-zinc-800 opacity-60"
      )}
      onClick={() => onNavigate(profile.name)}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="font-bold text-white text-sm">{meta?.displayName ?? resolveDisplayName(profile.name)}</p>
          <p className="text-xs text-zinc-500 mt-0.5">{meta?.description ?? profile.description}</p>
        </div>
        <span className={cn(
          "text-[10px] font-bold px-2 py-0.5 rounded-full border flex-shrink-0 ml-2",
          isEnabled
            ? "bg-lime-500/15 text-lime-400 border-lime-500/30"
            : "bg-zinc-800 text-zinc-500 border-zinc-700"
        )}>
          {isEnabled ? "ACTIVE" : "DISABLED"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Today P&L</p>
          <p className={cn("text-sm font-semibold", todayPnl >= 0 ? "text-lime-400" : "text-red-400")}>
            {todayPnl >= 0 ? "+" : ""}${Math.abs(todayPnl).toFixed(2)}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-zinc-600 uppercase tracking-wide">30d Return</p>
          <p className={cn("text-sm font-semibold", ret30 >= 0 ? "text-lime-400" : "text-red-400")}>
            {ret30 >= 0 ? "+" : ""}{ret30.toFixed(2)}%
          </p>
        </div>
        <div>
          <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Open Positions</p>
          <p className="text-sm font-semibold text-white">{openPositions}</p>
          {openPositions === 0 && (
            <p className="text-[9px] text-zinc-600 mt-0.5 leading-tight">Bot is scanning — positions appear after entry signals</p>
          )}
        </div>
        <div>
          <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Allocated</p>
          <p className="text-sm font-semibold text-white">
            {capitalCents
              ? `$${(capitalCents / 100).toLocaleString("en-US", { maximumFractionDigits: 0 })} (${capitalPct}%)`
              : allocation ? `${allocation.capital_pct ?? 10}%` : "—"}
          </p>
        </div>
      </div>

      <div className="flex gap-2 mt-auto" onClick={(e) => e.stopPropagation()}>
        {isEnabled ? (
          <button
            onClick={() => allocateMut.mutate(false)}
            disabled={allocateMut.isPending}
            className="flex-1 py-1.5 rounded-lg border border-zinc-700 text-xs text-zinc-400 hover:text-white hover:border-zinc-500 transition-colors disabled:opacity-40"
          >
            Disable
          </button>
        ) : (
          <button
            onClick={() => allocateMut.mutate(true)}
            disabled={allocateMut.isPending}
            className="flex-1 py-1.5 rounded-lg bg-lime-500 text-black text-xs font-bold hover:bg-lime-400 transition-colors disabled:opacity-40"
          >
            Enable
          </button>
        )}
        <button
          onClick={() => waitlistMut.mutate(true)}
          disabled={waitlistMut.isPending}
          className="flex-1 py-1.5 rounded-lg border border-zinc-700 text-xs text-zinc-400 hover:text-white hover:border-zinc-500 transition-colors disabled:opacity-40"
        >
          Notify when live
        </button>
      </div>
    </div>
  );
}

// ── Portfolio detail header ───────────────────────────────────────────────────

function PortfolioHeader({ portfolio }: { portfolio: StrategyPortfolio & Record<string, any> }) {
  const startingUsd = portfolio.starting_capital_cents / 100;
  const currentUsd = portfolio.current_value_cents / 100;
  const pnlUsd = portfolio.pnl_cents / 100;
  const isPositive = portfolio.pnl_pct >= 0;
  const todayPnlUsd = ((portfolio as any).today_pnl_cents ?? 0) / 100;
  const todayPositive = todayPnlUsd >= 0;

  const stats = [
    { label: "Starting Capital", value: `$${startingUsd.toLocaleString()}` },
    { label: "Current Value",    value: `$${currentUsd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` },
    { label: "All-Time P&L",     value: `${isPositive ? "+" : ""}$${Math.abs(pnlUsd).toFixed(2)}`, positive: isPositive, hasSign: true },
    { label: "All-Time Return",  value: `${isPositive ? "+" : ""}${portfolio.pnl_pct.toFixed(2)}%`, positive: isPositive, hasSign: true },
    { label: "Today P&L",        value: `${todayPositive ? "+" : ""}$${Math.abs(todayPnlUsd).toFixed(2)}`, positive: todayPositive, hasSign: true },
    { label: "Active Bots",      value: `${portfolio.bots.filter((b: any) => b.allocation?.enabled).length} / ${portfolio.bots.length}` },
  ];

  return (
    <div
      className="rounded-2xl border p-6"
      style={{ borderColor: portfolio.color_hex + "40", background: portfolio.color_hex + "08" }}
    >
      <div className="flex items-center gap-3 mb-5">
        <span className="text-4xl">{portfolio.emoji}</span>
        <div>
          <h1 className="text-2xl font-bold text-white">{portfolio.name} Portfolio</h1>
          <p className="text-zinc-500 text-sm mt-0.5">
            Paper trading · {portfolio.bots.length} dedicated bots · $50,000 starting capital
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {isPositive
            ? <TrendingUp size={20} style={{ color: portfolio.color_hex }} />
            : <TrendingDown size={20} className="text-red-400" />}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
        {stats.map((s) => (
          <div key={s.label}>
            <p className="text-[10px] text-zinc-600 uppercase tracking-wide mb-0.5">{s.label}</p>
            <p className={cn(
              "text-lg font-bold",
              s.hasSign
                ? s.positive ? "text-lime-400" : "text-red-400"
                : "text-white"
            )}>
              {s.value}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Recent Activity ───────────────────────────────────────────────────────────

function RecentActivity({ portfolioId, colorHex }: { portfolioId: number; colorHex: string }) {
  const navigate = useNavigate();
  const { data, isLoading } = usePortfolioActivity(portfolioId);
  const trades = data?.trades ?? [];

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-10 bg-zinc-900 rounded-xl animate-pulse" />
        ))}
      </div>
    );
  }

  if (trades.length === 0) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 text-center">
        <p className="text-zinc-500 text-sm">No trades yet. The execution engine runs daily at 10 AM ET on weekdays.</p>
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
      <div className="divide-y divide-zinc-800">
        {trades.map((t) => {
          const isBuy = t.side === "buy";
          const hasPnl = t.realized_pnl !== null;
          const pnlPositive = (t.realized_pnl ?? 0) >= 0;
          const ts = new Date(t.ts);
          return (
            <div key={t.id} onClick={() => navigate(`/strategy/trade/${t.id}`)} className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/50 transition-colors cursor-pointer">
              <div className={cn(
                "w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0",
                isBuy ? "bg-lime-500/15" : "bg-orange-500/15"
              )}>
                {isBuy
                  ? <ArrowUpRight size={13} className="text-lime-400" />
                  : <ArrowDownRight size={13} className="text-orange-400" />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-white text-sm font-semibold">{t.symbol}</span>
                  <span className={cn(
                    "text-[10px] font-bold px-1.5 py-0.5 rounded uppercase",
                    isBuy ? "bg-lime-500/10 text-lime-400" : "bg-orange-500/10 text-orange-400"
                  )}>
                    {t.side}
                  </span>
                  <span className="text-zinc-600 text-xs">{t.bot_display_name}</span>
                </div>
                <p className="text-zinc-500 text-xs mt-0.5">
                  {t.qty.toFixed(4)} {t.symbol.includes("/") ? t.symbol.split("/")[0] : "shares"} @ ${t.fill_price.toFixed(2)}
                  {hasPnl && (
                    <span className={cn("ml-2 font-semibold", pnlPositive ? "text-lime-400" : "text-red-400")}>
                      · {pnlPositive ? "+" : ""}${(t.realized_pnl!).toFixed(2)} realized
                    </span>
                  )}
                </p>
              </div>
              <div className="flex items-center gap-1 text-zinc-600 text-xs flex-shrink-0">
                <Clock size={10} />
                <span>{ts.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const ASSET_CLASS_ORDER = ["stocks", "crypto", "options"];

export default function PortfolioDetailPage() {
  const { assetClass } = useParams<{ assetClass: string }>();
  const navigate = useNavigate();

  const { data, isLoading } = useQuery({
    queryKey: ["strategy-portfolios"],
    queryFn: getPortfolios,
    staleTime: 60_000,
    retry: 0,
  });

  const portfolios = data?.portfolios ?? [];
  const portfolio = portfolios.find((p) => p.asset_class === assetClass) ?? null;

  const siblings = ASSET_CLASS_ORDER
    .map((ac) => portfolios.find((p) => p.asset_class === ac))
    .filter((p): p is StrategyPortfolio => !!p);

  if (isLoading) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-8 space-y-4">
        <div className="h-8 w-48 bg-zinc-800 rounded animate-pulse" />
        <div className="h-40 bg-zinc-900 rounded-2xl animate-pulse" />
        <div className="grid grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => <div key={i} className="h-48 bg-zinc-900 rounded-2xl animate-pulse" />)}
        </div>
      </div>
    );
  }

  if (!portfolio) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-16 text-center">
        <p className="text-zinc-500 mb-4">Portfolio not found.</p>
        <Link to="/strategy" className="text-lime-400 underline">← Back to Strategy Lab</Link>
      </div>
    );
  }

  const portfolioAny = portfolio as any;

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 pb-20 md:pb-6 space-y-6">
      {/* Back + sibling tabs */}
      <div className="flex items-center gap-4 flex-wrap">
        <button
          onClick={() => navigate("/strategy")}
          className="flex items-center gap-1.5 text-sm text-zinc-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={14} />
          Strategy Lab
        </button>
        <div className="flex items-center gap-2 ml-auto">
          {siblings.map((sib) => (
            <button
              key={sib.asset_class}
              onClick={() => navigate(`/strategy/portfolio/${sib.asset_class}`)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all border",
                sib.asset_class === assetClass
                  ? "text-black font-bold border-transparent"
                  : "bg-zinc-900 border-zinc-700 text-zinc-400 hover:text-white hover:border-zinc-600"
              )}
              style={sib.asset_class === assetClass ? { background: sib.color_hex, borderColor: sib.color_hex } : undefined}
            >
              {sib.emoji} {sib.name}
            </button>
          ))}
        </div>
      </div>

      {/* Portfolio hero */}
      <PortfolioHeader portfolio={portfolio as any} />

      {/* Bot grid */}
      <div>
        <div className="flex items-center gap-2 mb-4">
          <Activity size={14} style={{ color: portfolio.color_hex }} />
          <h2 className="text-sm font-semibold text-zinc-300">Active Bots</h2>
        </div>
        <div className={cn(
          "grid gap-4",
          portfolio.bots.length === 2
            ? "grid-cols-1 sm:grid-cols-2"
            : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
        )}>
          {portfolio.bots.map((item) => (
            <BotCard
              key={item.profile.name}
              item={item}
              portfolioStarting={portfolio.starting_capital_cents}
              onNavigate={(name) => navigate(`/strategy/${name}`)}
            />
          ))}
        </div>
      </div>

      {/* Recent Activity */}
      <div>
        <div className="flex items-center gap-2 mb-4">
          <Clock size={14} style={{ color: portfolio.color_hex }} />
          <h2 className="text-sm font-semibold text-zinc-300">Recent Trades</h2>
          <span className="text-xs text-zinc-600 ml-1">— every P&L dollar backed by a trade</span>
        </div>
        <RecentActivity portfolioId={portfolioAny.id} colorHex={portfolio.color_hex} />
      </div>

      {/* Footer */}
      <p className="text-xs text-zinc-600 pt-4">
        Paper trading only. Not investment advice. Not a registered investment adviser.
      </p>
    </div>
  );
}

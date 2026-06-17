import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Clock, ArrowDownRight, ArrowUpRight } from "lucide-react";
import {
  getPortfolios,
  allocateBot,
  joinWaitlist,
  leaveWaitlist,
  type StrategyPortfolio,
  type BotListItem,
} from "@/api/bots";
import { usePortfolioSnapshot } from "@/hooks/usePortfolioSnapshot";
import { botStatusBadge, BADGE_CLASSES } from "@/lib/botStatus";
import type { BotSnap } from "@/api/portfolioSnapshot";
import client from "@/api/client";
import { cn } from "@/lib/utils";
import { formatTradeSize } from "@/lib/formatTradeSize";

// ── Per-sleeve accent config ──────────────────────────────────────────────────

const SLEEVE_ACCENT: Record<string, { color: string; glyph: string; label: string }> = {
  stocks:  { color: "#9fb0cf", glyph: "S", label: "STOCKS" },
  crypto:  { color: "#f0b35a", glyph: "C", label: "CRYPTO" },
  options: { color: "#c79bf0", glyph: "O", label: "OPTIONS" },
  quant:   { color: "#38bdf8", glyph: "Q", label: "QUANT" },
};

const ASSET_CLASS_ORDER = ["stocks", "crypto", "options", "quant"] as const;

function hexRgba(hex: string, alpha: number): string {
  const m = hex.replace("#", "");
  const r = parseInt(m.slice(0, 2), 16);
  const g = parseInt(m.slice(2, 4), 16);
  const b = parseInt(m.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ── Value colour helpers ──────────────────────────────────────────────────────

function pnlColor(val: number): string {
  if (val > 0) return "#4ade80";
  if (val < 0) return "#f87171";
  return "#7e8e7e";
}

function fmtUsd(cents: number): string {
  const usd = Math.abs(cents / 100);
  const sign = cents >= 0 ? "+" : "-";
  return `${sign}$${usd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(pct: number): string {
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

// ── Bot display names & descriptions ─────────────────────────────────────────

const BOT_META: Record<string, { displayName: string; description: string }> = {
  stock_swing:                  { displayName: "Stock Swing",           description: "Russell 1000 momentum, 1–30 day holds" },
  stock_day:                    { displayName: "Stock Day",             description: "Intraday gappers & earnings momentum, EOD flat" },
  stock_lt:                     { displayName: "Stock Long-Term",       description: "S&P 500 factor model, monthly rebalance" },
  crypto_swing:                 { displayName: "Crypto Swing",          description: "3–7 day trend follow, majors only" },
  crypto_day:                   { displayName: "Crypto Day",            description: "Intraday momentum across 28 pairs, 5m candles" },
  crypto_lt:                    { displayName: "Crypto L-T DCA",        description: "Trend-weighted accumulation, weekly" },
  crypto_onchain:               { displayName: "Crypto On-Chain",       description: "Whale-flow & DEX signal following" },
  options_income:               { displayName: "Options Income",        description: "Theta harvest — credit spreads on SPY/QQQ" },
  options_directional:          { displayName: "Options Directional",   description: "Delta-1 swing — momentum calls & puts" },
  crypto_quant_aggressive:      { displayName: "Quant Aggressive",      description: "Multi-factor, high turnover · cross-asset" },
  crypto_quant_scalper:         { displayName: "Quant Scalper",         description: "0DTE micro-cycle · ultra short hold" },
  crypto_quant_mean_reversion:  { displayName: "Quant Mean Reversion",  description: "Bollinger fade on 1h bands" },
  crypto_meanrev_2163:          { displayName: "Mean Rev 2163",         description: "Experimental mean-reversion variant, paper-only" },
};

function resolveName(name: string, fromApi?: string): string {
  return BOT_META[name]?.displayName ?? fromApi ?? name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function resolveDesc(name: string, fromApi?: string): string {
  return BOT_META[name]?.description ?? fromApi ?? "";
}

// ── Portfolio activity ────────────────────────────────────────────────────────

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
  // Options-specific (null for stock/crypto trades)
  option_type?: string | null;
  strike_price?: number | null;
  expiration_date?: string | null;
  underlying_symbol?: string | null;
  contract_count?: number | null;
  contract_premium_cents?: number | null;
}

function usePortfolioActivity(portfolioId: number | undefined) {
  return useQuery({
    queryKey: ["portfolio-activity", portfolioId],
    queryFn: () =>
      portfolioId
        ? client
            .get<{ trades: TradeRecord[]; total: number }>(`/bots/portfolios/${portfolioId}/activity`, { params: { limit: 40 } })
            .then((r) => r.data)
        : Promise.resolve({ trades: [], total: 0 }),
    enabled: !!portfolioId,
    staleTime: 60_000,
    retry: 0,
  });
}

// ── Bot card ──────────────────────────────────────────────────────────────────

function BotCard({
  item,
  accent,
  onNavigate,
  snapBot,
}: {
  item: BotListItem;
  accent: string;
  onNavigate: (n: string) => void;
  snapBot?: BotSnap;
}) {
  const { profile, allocation, stats } = item;
  const qc = useQueryClient();

  const isEnabled = snapBot ? snapBot.enabled : (allocation?.enabled ?? false);
  const isAdminLocked = snapBot
    ? snapBot.is_admin_locked
    : allocation?.paused_reason === "admin_lock" || allocation?.paused_reason === "health_halt";
  const ret30 = snapBot ? snapBot.return_30d_pct : (stats?.return_30d_pct ?? 0);
  const todayPnlUsd = snapBot ? snapBot.today_pnl_cents / 100 : (stats?.today_pnl ?? 0);
  const openPositions = stats?.open_positions ?? 0;
  const capitalPct = (item as any).capital_pct_within_portfolio ?? allocation?.capital_pct ?? 0;

  const allocateMut = useMutation({
    mutationFn: (enabled: boolean) =>
      allocateBot(profile.name, { capital_pct: allocation?.capital_pct ?? 10, risk_profile: "standard", enabled }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategy-portfolios"] });
      toast.success(isEnabled ? `${resolveName(profile.name)} disabled` : `${resolveName(profile.name)} enabled`);
    },
    onError: () => toast.error("Failed to update bot"),
  });

  const waitlistMut = useMutation({
    mutationFn: (join: boolean) => (join ? joinWaitlist(profile.name) : leaveWaitlist(profile.name)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["strategy-portfolios"] }),
  });

  const badge = snapBot ? botStatusBadge(snapBot) : null;
  const live = isEnabled && !isAdminLocked;
  const dot = live ? "#4ade80" : "#fbbf24";
  const dotGlow = live ? "0 0 7px rgba(74,222,128,0.9)" : "none";
  const cardOpacity = live ? "1" : "0.62";

  // Note line
  let note = "";
  if (openPositions === 0 && live) note = "// scanning — positions appear after entry signals";
  else if (openPositions > 0) note = `${openPositions} position${openPositions !== 1 ? "s" : ""} open`;

  return (
    <div
      onClick={() => onNavigate(profile.name)}
      className="flex flex-col gap-0 cursor-pointer transition-all"
      style={{
        border: `1px solid ${live ? "rgba(74,222,128,0.14)" : "rgba(74,222,128,0.07)"}`,
        borderLeft: `3px solid ${accent}`,
        borderRadius: "6px",
        background: live ? "#0a100a" : "#080c08",
        padding: "18px",
        opacity: cardOpacity,
      }}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1.5">
            <span
              className="w-[7px] h-[7px] rounded-full flex-shrink-0"
              style={{ background: dot, boxShadow: dotGlow }}
            />
            <span className="font-semibold text-[15px]" style={{ color: live ? "#eafbe9" : "#9fb0a0" }}>
              {resolveName(profile.name, undefined)}
            </span>
          </div>
          <p className="font-mono text-[11px] leading-relaxed" style={{ color: "#7e8e7e" }}>
            {resolveDesc(profile.name, profile.description)}
          </p>
        </div>
        {badge ? (
          <span className={cn("text-[9px] font-bold px-2 py-0.5 rounded border flex-shrink-0 font-mono tracking-wider", BADGE_CLASSES[badge.variant])}>
            {badge.text}
          </span>
        ) : (
          <span
            className="text-[9px] font-mono tracking-[0.08em] rounded border flex-shrink-0 px-2 py-0.5"
            style={{
              color: isAdminLocked ? "#fbbf24" : live ? "#4ade80" : "#fbbf24",
              background: isAdminLocked ? "rgba(251,191,36,0.07)" : live ? "rgba(74,222,128,0.08)" : "rgba(251,191,36,0.07)",
              borderColor: isAdminLocked ? "rgba(251,191,36,0.3)" : live ? "rgba(74,222,128,0.3)" : "rgba(251,191,36,0.3)",
            }}
          >
            {isAdminLocked ? "FROZEN" : live ? "ACTIVE" : "PAUSED"}
          </span>
        )}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-3.5 mt-4">
        <div>
          <div className="font-mono text-[9px] tracking-[0.1em]" style={{ color: "#50604f" }}>TODAY P&amp;L</div>
          <div className="font-mono text-[15px] mt-1" style={{ color: pnlColor(todayPnlUsd) }}>
            {todayPnlUsd >= 0 ? "+" : ""}${Math.abs(todayPnlUsd).toFixed(2)}
          </div>
        </div>
        <div>
          <div className="font-mono text-[9px] tracking-[0.1em]" style={{ color: "#50604f" }}>30D RETURN</div>
          <div className="font-mono text-[15px] mt-1" style={{ color: pnlColor(ret30) }}>
            {fmtPct(ret30)}
          </div>
        </div>
        <div>
          <div className="font-mono text-[9px] tracking-[0.1em]" style={{ color: "#50604f" }}>OPEN POSITIONS</div>
          <div className="font-mono text-[15px] mt-1" style={{ color: "#dce8dc" }}>{openPositions}</div>
        </div>
        <div>
          <div className="font-mono text-[9px] tracking-[0.1em]" style={{ color: "#50604f" }}>ALLOCATED</div>
          <div className="font-mono text-[15px] mt-1" style={{ color: "#dce8dc" }}>
            {capitalPct ? `${capitalPct}%` : allocation ? `${allocation.capital_pct ?? 10}%` : "—"}
          </div>
        </div>
      </div>

      {/* Note */}
      <div className="min-h-[18px] mt-3">
        {note && (
          <span className="font-mono text-[10px]" style={{ color: "#50604f" }}>
            {note}
          </span>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-2 mt-3" onClick={(e) => e.stopPropagation()}>
        {live ? (
          <button
            onClick={() => allocateMut.mutate(false)}
            disabled={allocateMut.isPending}
            className="flex-1 py-2 text-xs font-medium rounded transition-all disabled:opacity-40"
            style={{
              color: "#7e8e7e",
              background: "#121a12",
              border: "1px solid rgba(74,222,128,0.14)",
              fontFamily: "'Space Grotesk', sans-serif",
            }}
          >
            Disable
          </button>
        ) : (
          <button
            onClick={() => allocateMut.mutate(true)}
            disabled={allocateMut.isPending}
            className="flex-1 py-2 text-xs font-medium rounded transition-all disabled:opacity-40"
            style={{
              color: "#4ade80",
              background: "transparent",
              border: "1px solid #4ade80",
              fontFamily: "'Space Grotesk', sans-serif",
            }}
          >
            Enable
          </button>
        )}
        <button
          onClick={() => waitlistMut.mutate(true)}
          disabled={waitlistMut.isPending}
          className="flex-1 py-2 text-xs font-medium rounded transition-all disabled:opacity-40 hover:opacity-80"
          style={{
            color: accent,
            background: "transparent",
            border: `1px solid ${hexRgba(accent, 0.4)}`,
            fontFamily: "'Space Grotesk', sans-serif",
          }}
        >
          Notify when live
        </button>
      </div>
    </div>
  );
}

// ── Recent Activity ───────────────────────────────────────────────────────────

function RecentActivity({
  portfolioId,
  accent,
  assetClass,
}: {
  portfolioId: number;
  accent: string;
  assetClass: string;
}) {
  const navigate = useNavigate();
  const { data, isLoading } = usePortfolioActivity(portfolioId);
  const trades = data?.trades ?? [];

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-10 rounded animate-pulse" style={{ background: "#0a100a" }} />
        ))}
      </div>
    );
  }

  if (trades.length === 0) {
    return (
      <div
        className="rounded p-6 text-center font-mono text-[11px]"
        style={{ border: "1px solid rgba(74,222,128,0.1)", background: "#070d07", color: "#50604f" }}
      >
        {["crypto", "quant"].includes(assetClass)
          ? "Bots scan continuously. Next scan: within 1 minute."
          : "No trades yet. Execution engine runs at market open (Mon–Fri 9:30 AM ET)."}
      </div>
    );
  }

  return (
    <div className="rounded overflow-hidden" style={{ border: "1px solid rgba(74,222,128,0.1)", background: "#070d07" }}>
      {trades.map((t, idx) => {
        const isBuy = t.side === "buy";
        const hasPnl = t.realized_pnl !== null;
        const pnlPositive = (t.realized_pnl ?? 0) >= 0;
        const ts = new Date(t.ts);
        const isOptions = assetClass === "options" && t.contract_count != null;
        const premium = t.contract_premium_cents != null ? t.contract_premium_cents / 100 : null;
        const totalCost = premium != null && t.contract_count != null ? premium * 100 * t.contract_count : null;
        return (
          <div
            key={t.id}
            onClick={() => navigate(`/strategy/trade/${t.id}`)}
            className="flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors hover:bg-white/[0.02]"
            style={{ borderBottom: idx < trades.length - 1 ? "1px solid rgba(74,222,128,0.08)" : undefined }}
          >
            <div
              className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
              style={{ background: isBuy ? "rgba(74,222,128,0.12)" : "rgba(248,113,113,0.10)" }}
            >
              {isBuy
                ? <ArrowUpRight size={13} className="text-lime-400" />
                : <ArrowDownRight size={13} className="text-red-400" />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-semibold" style={{ color: "#eafbe9" }}>{t.underlying_symbol ?? t.symbol}</span>
                {isOptions && t.option_type && (
                  <span
                    className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded uppercase"
                    style={{
                      background: t.option_type.includes("call") ? "rgba(74,222,128,0.1)" : "rgba(248,113,113,0.1)",
                      color: t.option_type.includes("call") ? "#4ade80" : "#f87171",
                    }}
                  >
                    {t.option_type}
                  </span>
                )}
                <span
                  className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded uppercase"
                  style={{
                    background: isBuy ? "rgba(74,222,128,0.1)" : "rgba(248,113,113,0.1)",
                    color: isBuy ? "#4ade80" : "#f87171",
                  }}
                >
                  {isOptions ? (isBuy ? "buy to open" : "sell to close") : t.side}
                </span>
                <span className="text-[11px] font-mono" style={{ color: "#50604f" }}>{t.bot_display_name}</span>
              </div>
              {isOptions ? (
                <p className="text-xs font-mono mt-0.5" style={{ color: "#7e8e7e" }}>
                  {t.contract_count} contract{(t.contract_count ?? 0) > 1 ? "s" : ""}
                  {t.strike_price != null && <span> · <span style={{ color: "#9ca3af" }}>$</span>{t.strike_price.toFixed(0)} strike</span>}
                  {premium != null && <span> · <span style={{ color: "#9ca3af" }}>$</span>{premium.toFixed(2)}/contract</span>}
                  {totalCost != null && <span style={{ color: "#50604f" }}> (${totalCost.toLocaleString("en-US", { maximumFractionDigits: 0 })} total)</span>}
                  {t.expiration_date && <span style={{ color: "#50604f" }}> · exp {t.expiration_date}</span>}
                  {hasPnl && (
                    <span className="ml-2 font-semibold" style={{ color: pnlPositive ? "#4ade80" : "#f87171" }}>
                      · {pnlPositive ? "+" : ""}${(t.realized_pnl!).toFixed(2)} realized
                    </span>
                  )}
                </p>
              ) : (
                <p className="text-xs font-mono mt-0.5" style={{ color: "#7e8e7e" }}>
                  {formatTradeSize(t.qty, t.symbol, Math.abs(t.qty) * t.fill_price)}
                  {hasPnl && (
                    <span className="ml-2 font-semibold" style={{ color: pnlPositive ? "#4ade80" : "#f87171" }}>
                      · {pnlPositive ? "+" : ""}${(t.realized_pnl!).toFixed(2)} realized
                    </span>
                  )}
                </p>
              )}
            </div>
            <div className="flex items-center gap-1 text-xs flex-shrink-0 font-mono" style={{ color: "#50604f" }}>
              <Clock size={10} />
              <span>{ts.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
            </div>
          </div>
        );
      })}
    </div>
              </div>
              <div className="font-mono text-[20px] font-medium leading-none" style={{ color: s.color }}>
                {s.value}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PortfolioDetailPage() {
  const { assetClass } = useParams<{ assetClass: string }>();
  const navigate = useNavigate();

  const { data, isLoading } = useQuery({
    queryKey: ["strategy-portfolios"],
    queryFn: getPortfolios,
    staleTime: 60_000,
    retry: 0,
  });

  const { snap } = usePortfolioSnapshot();
  const snapBotMap = Object.fromEntries(snap.bots.map((b) => [b.id, b]));

  const portfolios = data?.portfolios ?? [];
  const portfolio = portfolios.find((p) => p.asset_class === assetClass) ?? null;

  const siblings = ASSET_CLASS_ORDER.map((ac) => portfolios.find((p) => p.asset_class === ac)).filter(
    (p): p is StrategyPortfolio => !!p
  );

  const accentMeta = SLEEVE_ACCENT[assetClass ?? "stocks"] ?? SLEEVE_ACCENT.stocks;
  const accent = portfolio?.color_hex ?? accentMeta.color;

  if (isLoading) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-8 space-y-4">
        <div className="h-8 w-48 rounded animate-pulse" style={{ background: "#0a100a" }} />
        <div className="h-44 rounded animate-pulse" style={{ background: "#0a100a" }} />
        <div className="grid grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-52 rounded animate-pulse" style={{ background: "#0a100a" }} />
          ))}
        </div>
      </div>
    );
  }

  if (!portfolio) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-16 text-center">
        <p className="font-mono text-sm mb-4" style={{ color: "#7e8e7e" }}>
          Portfolio not found.
        </p>
        <Link to="/strategy" className="text-sm" style={{ color: accent }}>
          ← Strategy Lab
        </Link>
      </div>
    );
  }

  const portfolioAny = portfolio as any;

  // Enrich with real-time snapshot values
  const sleeveKey = assetClass as keyof typeof snap.by_sleeve;
  const sleeve = snap.by_sleeve[sleeveKey];
  const enriched: any = sleeve
    ? {
        ...portfolio,
        starting_capital_cents:
          sleeve.starting_capital_cents || sleeve.reserved_capital_cents || portfolioAny.starting_capital_cents,
        reserved_capital_cents: sleeve.reserved_capital_cents ?? 0,
        current_value_cents: sleeve.current_value_cents || portfolioAny.current_value_cents,
        pnl_cents: sleeve.alltime_pnl_cents,
        pnl_pct: sleeve.alltime_return_pct,
        today_pnl_cents: sleeve.today_pnl_cents,
      }
    : portfolio;

  return (
    <>
      {/* Inline keyframe for hero glow — inserted once */}
      <style>{`
        @keyframes bmgGlow {
          0%,100% { box-shadow: 0 0 24px ${hexRgba(accent, 0.12)}, inset 0 0 26px ${hexRgba(accent, 0.03)}; }
          50%      { box-shadow: 0 0 38px ${hexRgba(accent, 0.24)}, inset 0 0 30px ${hexRgba(accent, 0.06)}; }
        }
      `}</style>

      <div
        className="min-h-screen pb-24"
        style={{ background: "#040804", color: "#dce8dc" }}
      >
        <div className="max-w-5xl mx-auto px-6 py-5">

          {/* Breadcrumb + sleeve tabs */}
          <div className="flex items-center gap-4 mb-5">
            <div className="flex items-center gap-2 font-mono text-[11px]" style={{ color: "#50604f" }}>
              <button
                onClick={() => navigate("/strategy")}
                className="transition-colors hover:opacity-80"
                style={{ color: "#7e8e7e" }}
              >
                Strategy Lab
              </button>
              <span>/</span>
              <span style={{ color: accent }}>{portfolio.name}</span>
            </div>

            <div className="flex items-center gap-2 ml-auto">
              {siblings.map((sib) => {
                const sibAccent = SLEEVE_ACCENT[sib.asset_class]?.color ?? sib.color_hex ?? "#4ade80";
                const isActive = sib.asset_class === assetClass;
                return (
                  <button
                    key={sib.asset_class}
                    onClick={() => navigate(`/strategy/portfolio/${sib.asset_class}`)}
                    className="flex items-center gap-1.5 font-mono text-[11px] tracking-[0.06em] rounded transition-all"
                    style={{
                      padding: "7px 13px",
                      color: isActive ? "#040804" : sibAccent,
                      background: isActive ? sibAccent : "transparent",
                      border: `1px solid ${isActive ? sibAccent : "rgba(74,222,128,0.16)"}`,
                    }}
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-[1px] flex-shrink-0"
                      style={{ background: isActive ? "#040804" : sibAccent }}
                    />
                    {SLEEVE_ACCENT[sib.asset_class]?.label ?? sib.name.toUpperCase()}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Hero card */}
          <HeroCard
            portfolio={enriched}
            accent={accent}
            glyph={accentMeta.glyph}
          />

          {/* Active bots header */}
          <div className="flex items-center gap-3 mt-7 mb-4">
            <span className="font-mono text-[11px] tracking-[0.16em]" style={{ color: "#4ade80", opacity: 0.85 }}>
              // ACTIVE BOTS · {portfolio.bots.length} DEDICATED
            </span>
            <span
              className="flex-1 h-px"
              style={{ background: "linear-gradient(90deg,rgba(74,222,128,0.22),transparent)" }}
            />
          </div>

          {/* Bot grid */}
          {portfolio.bots.length === 0 ? (
            <div
              className="flex flex-col items-center justify-center py-16 gap-3 text-center rounded"
              style={{ border: "1px dashed rgba(74,222,128,0.1)", background: "rgba(74,222,128,0.02)" }}
            >
              <p className="font-semibold text-sm" style={{ color: "#7e8e7e" }}>No bots configured for this sleeve</p>
              <p className="font-mono text-xs" style={{ color: "#50604f" }}>
                Visit{" "}
                <a href="/candidates" style={{ color: accent }}>
                  /candidates
                </a>{" "}
                to track strategies moving through the pipeline.
              </p>
            </div>
          ) : (
            <div
              className={cn(
                "grid gap-4",
                portfolio.bots.length === 2
                  ? "grid-cols-1 sm:grid-cols-2"
                  : portfolio.bots.length >= 4
                  ? "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
                  : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
              )}
            >
              {portfolio.bots.map((item) => (
                <BotCard
                  key={item.profile.name}
                  item={item}
                  accent={accent}
                  onNavigate={(name) => navigate(`/strategy/${name}`)}
                  snapBot={snapBotMap[item.profile.name]}
                />
              ))}
            </div>
          )}

          {/* Recent trades */}
          {portfolioAny.id && (
            <>
              <div className="flex items-center gap-3 mt-8 mb-4">
                <span className="font-mono text-[11px] tracking-[0.16em]" style={{ color: accent, opacity: 0.85 }}>
                  // RECENT TRADES
                </span>
                <span
                  className="flex-1 h-px"
                  style={{ background: `linear-gradient(90deg,${hexRgba(accent, 0.22)},transparent)` }}
                />
              </div>
              <RecentActivity
                portfolioId={portfolioAny.id}
                accent={accent}
                assetClass={portfolio.asset_class}
              />
            </>
          )}

          {/* Footer */}
          <p className="font-mono text-[10px] mt-8" style={{ color: "#50604f" }}>
            Paper trading only. Not investment advice. Not a registered investment adviser.
          </p>
        </div>
      </div>
    </>
  );
}

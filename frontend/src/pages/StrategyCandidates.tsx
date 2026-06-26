import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { getStrategyLabCandidates } from "@/api/bots";

// ─── Types ────────────────────────────────────────────────────────────────────

type CandidateAssetClass = "equity" | "crypto" | "multi";
type CandidateStyle =
  | "momentum"
  | "mean_reversion"
  | "event_driven"
  | "arbitrage"
  | "cross_asset_momentum"
  | "quality_momentum"
  | "short_volatility";

interface CandidateEntry {
  id: string;
  name: string;
  assetClass: CandidateAssetClass;
  style: CandidateStyle;
  reference: string;
  expectedSharpe: string;
  description: string;
}

// ─── Candidate metadata (copied verbatim from StrategyLab.tsx) ───────────────

const CANDIDATE_META: CandidateEntry[] = [
  {
    id: "cross_sectional_momentum",
    name: "Cross-Sectional Momentum",
    assetClass: "equity",
    style: "momentum",
    reference: "Jegadeesh & Titman (1993)",
    expectedSharpe: "0.4–0.8",
    description: "Ranks universe by 12-1M return, buys top quintile, sells bottom quintile.",
  },
  {
    id: "time_series_momentum",
    name: "Time-Series Momentum",
    assetClass: "multi",
    style: "momentum",
    reference: "Moskowitz, Ooi & Pedersen (2012)",
    expectedSharpe: "0.5–1.0",
    description: "Each asset evaluated independently; long if 12M trailing return positive. Sized by inverse vol.",
  },
  {
    id: "crypto_dual_momentum",
    name: "Crypto Dual Momentum",
    assetClass: "crypto",
    style: "momentum",
    reference: "Liu & Tsyvinski (2021) + Antonacci (2014)",
    expectedSharpe: "0.6–1.2",
    description: "Combines absolute momentum vs. cash with relative momentum across top-N crypto. Long-only.",
  },
  {
    id: "overnight_gap_fade",
    name: "Overnight Gap Fade",
    assetClass: "equity",
    style: "mean_reversion",
    reference: "Branch & Ma (2008)",
    expectedSharpe: "0.3–0.7",
    description: "Fades overnight gaps > 1.5%. Gap-up stocks tend to pull back; gap-down stocks tend to recover.",
  },
  {
    id: "rsi2_mean_reversion",
    name: "RSI-2 Mean Reversion",
    assetClass: "equity",
    style: "mean_reversion",
    reference: "Connors & Alvarez (2009)",
    expectedSharpe: "0.4–0.9",
    description: "Buys when RSI(2) < 10 above the 200-day MA. Exits when RSI(2) closes above 70.",
  },
  {
    id: "cash_and_carry",
    name: "Cash-and-Carry Basis",
    assetClass: "crypto",
    style: "arbitrage",
    reference: "Futures basis trade",
    expectedSharpe: "1.0–2.5",
    description: "Delta-neutral: long spot + short perp. Collects positive funding rate as carry.",
  },
  {
    id: "liquidation_cascade",
    name: "Liquidation Cascade",
    assetClass: "crypto",
    style: "event_driven",
    reference: "Coinglass heatmap + Binance forceOrders",
    expectedSharpe: "0.6–1.4",
    description: "Ride mode follows cascades at heatmap clusters; fade mode fades exhausted cascades.",
  },
  {
    id: "insider_cluster_buying",
    name: "Insider Cluster Buying",
    assetClass: "equity",
    style: "event_driven",
    reference: "Lakonishok & Lee (2001) — SEC Form 4",
    expectedSharpe: "0.5–1.1",
    description: "Detects 3+ insiders buying open-market (≥$500k) within a 30-day window.",
  },
  {
    id: "cross_asset_momentum",
    name: "Cross-Asset Momentum",
    assetClass: "multi",
    style: "cross_asset_momentum",
    reference: "Antonacci (2014) Global Equities Momentum",
    expectedSharpe: "0.7–1.0",
    description: "10-ETF monthly rotation into top-3 by blended momentum. Only holds assets above absolute trend filter. Credit spread gate cuts sizing in stress.",
  },
  {
    id: "earnings_vol_premium",
    name: "Earnings Vol Premium",
    assetClass: "equity",
    style: "short_volatility",
    reference: "Augustin, Brenner & Subrahmanyam (2014)",
    expectedSharpe: "1.0–1.6",
    description: "Sells iron condors 7 days before earnings on stocks where IV rank ≥ 70% and implied move ≥ 5%. Captures post-earnings IV crush.",
  },
  {
    id: "quality_momentum_screen",
    name: "Quality Momentum Screen",
    assetClass: "equity",
    style: "quality_momentum",
    reference: "Asness, Frazzini & Pedersen (2019) QMJ",
    expectedSharpe: "0.7–1.5",
    description: "Monthly rebalance into top-25 stocks ranked by QMJ quality (SimFin), 12-1M momentum, and low beta. Flattens to cash when credit spreads are red.",
  },
  {
    id: "options_iv_premium_filter",
    name: "Options IV Premium Filter",
    assetClass: "equity",
    style: "short_volatility",
    reference: "Israelov & Nielsen (2014)",
    expectedSharpe: "0.7–1.1",
    description: "Sells cash-secured puts or covered calls only when IV Rank ≥ 50. Captures the volatility risk premium with an IVR gate to avoid selling into low-vol regimes.",
  },
];

const _ASSET_CHIP: Record<CandidateAssetClass, string> = {
  equity: "bg-t-cyan/10 text-t-cyan border-t-cyan/20",
  crypto: "bg-t-amber/10 text-t-amber border-t-amber/20",
  multi:  "bg-violet-500/10 text-violet-400 border-violet-500/20",
};
const _ASSET_LABEL: Record<CandidateAssetClass, string> = {
  equity: "Equity",
  crypto: "Crypto",
  multi:  "Multi-Asset",
};
const _STYLE_CHIP: Record<CandidateStyle, string> = {
  momentum:             "bg-t-green/10 text-t-green border-t-green/20",
  mean_reversion:       "bg-t-cyan/10 text-t-cyan border-t-cyan/20",
  event_driven:         "bg-t-amber/10 text-t-amber border-t-amber/20",
  arbitrage:            "bg-pink-500/10 text-pink-400 border-pink-500/20",
  cross_asset_momentum: "bg-violet-500/10 text-violet-400 border-violet-500/20",
  quality_momentum:     "bg-t-bright/10 text-t-bright border-t-bright/20",
  short_volatility:     "bg-t-red/10 text-t-red border-t-red/20",
};
const _STYLE_LABEL: Record<CandidateStyle, string> = {
  momentum:             "Momentum",
  mean_reversion:       "Mean Rev",
  event_driven:         "Event",
  arbitrage:            "Arbitrage",
  cross_asset_momentum: "Cross-Asset",
  quality_momentum:     "Quality",
  short_volatility:     "Short Vol",
};

function CandidateCard({ c }: { c: CandidateEntry }) {
  return (
    <div className="relative rounded-2xl border border-dashed border-t-dim/60 bg-t-bg0/60 p-4 flex flex-col gap-3 hover:border-t-mid/80 transition-colors">
      {/* Watermark */}
      <div className="absolute top-2 right-3 text-[9px] font-bold tracking-widest text-t-gdim uppercase select-none font-ui-t">
        INCUBATING
      </div>

      {/* Header */}
      <div className="flex items-start gap-2 pr-16">
        <div>
          <p className="text-sm font-semibold text-t-mid2 leading-snug font-ui-t">{c.name}</p>
          <p className="text-[10px] text-t-gdim mt-0.5 font-mono-t">{c.reference}</p>
        </div>
      </div>

      {/* Chips */}
      <div className="flex flex-wrap gap-1.5">
        <span className={cn("text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border font-ui-t", _ASSET_CHIP[c.assetClass])}>
          {_ASSET_LABEL[c.assetClass]}
        </span>
        <span className={cn("text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border font-ui-t", _STYLE_CHIP[c.style])}>
          {_STYLE_LABEL[c.style]}
        </span>
        <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border bg-t-amber/10 text-t-amber border-t-amber/20 font-ui-t">
          T0 CANDIDATE
        </span>
      </div>

      {/* Description */}
      <p className="text-xs text-t-dim leading-relaxed font-ui-t">{c.description}</p>

      {/* Sharpe range */}
      <div className="flex items-center justify-between text-[10px]">
        <span className="text-t-gdim font-ui-t">Expected Sharpe</span>
        <span className="font-mono-t tabular-nums text-t-muted">{c.expectedSharpe}</span>
      </div>

      {/* Promotion criteria */}
      <div className="rounded-lg bg-t-bg0/60 border border-t-dim px-3 py-2">
        <p className="text-[9px] font-semibold text-t-gdim uppercase tracking-wider mb-0.5 font-ui-t">Promotes to T1 when</p>
        <p className="text-[10px] text-t-dim font-ui-t">30 days live · 20 trades · Sharpe &gt; 0.3</p>
      </div>
    </div>
  );
}

export default function StrategyCandidates() {
  const { data: candidatesData } = useQuery({
    queryKey: ["strategy-lab-candidates"],
    queryFn: getStrategyLabCandidates,
    staleTime: 300_000,
    retry: 0,
  });
  const incubationCount = candidatesData?.candidates?.length ?? CANDIDATE_META.length;

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 max-w-7xl mx-auto space-y-4">
      {/* Breadcrumb */}
      <Link
        to="/strategy"
        className="inline-flex items-center text-xs text-t-gdim hover:text-t-muted transition-colors font-ui-t"
      >
        ← Back to Strategy Lab
      </Link>

      {/* Section header */}
      <div className="flex items-center gap-3 mb-3">
        <div className="flex-1 h-px border-t border-dashed border-t-dim" />
        <p className="text-[10px] font-semibold text-t-dim uppercase tracking-widest whitespace-nowrap font-ui-t">
          // CANDIDATES (paper-shadow, not live)
        </p>
        <div className="flex-1 h-px border-t border-dashed border-t-dim" />
      </div>
      <p className="text-xs text-t-gdim mb-4 font-ui-t">
        {incubationCount} strategies in incubation. Tracked in paper mode only.
        Manual graduation required to promote to live trading.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {CANDIDATE_META.map((c) => (
          <CandidateCard key={c.id} c={c} />
        ))}
      </div>
    </div>
  );
}

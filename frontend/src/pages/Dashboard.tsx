import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getMarketOverview, getSectorPerformance, getNews } from "@/api/market";
import { getPortfolios } from "@/api/portfolio";
import { getTrades } from "@/api/strategy";
import { getAccount } from "@/api/paper";
import { getLatestRecap } from "@/api/recap";
import { useMarketStore } from "@/store";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import { TrendingUp, TrendingDown, ExternalLink, ArrowRight, Briefcase, FlaskConical, RefreshCw, LineChart, Calendar } from "lucide-react";
import SectorPill from "@/components/ui/SectorPill";
import { Skeleton, SkeletonCard } from "@/components/ui/Skeleton";
import { generateMorningBrief } from "@/lib/demoBrief";
import DailyRecapCard from "@/components/recap/DailyRecapCard";
import { Card, CardLabel } from "@/components/ui/Card";

const INDEX_NAMES: Record<string, string> = {
  SPY: "S&P 500", QQQ: "NASDAQ 100", DIA: "Dow Jones", IWM: "Russell 2000",
  VXX: "Volatility", GLD: "Gold", TLT: "10Y Treasury",
};

// ── Morning Brief ─────────────────────────────────────────────────────────────

function MorningBrief({
  indices,
  sectors,
  news,
  isLoading,
}: {
  indices: any[];
  sectors: any[];
  news: any[];
  isLoading: boolean;
}) {
  const [displayText, setDisplayText] = useState("");
  const [briefText, setBriefText] = useState("");
  const [animKey, setAnimKey] = useState(0);

  const buildBrief = useCallback(() => {
    if (!indices.length) return "";
    const date = new Date();
    return generateMorningBrief(
      {
        indices: indices.map((i: any) => ({
          symbol: i.symbol,
          name: INDEX_NAMES[i.symbol] ?? i.symbol,
          change_pct: i.change_pct,
          price: i.price,
        })),
        sectors: sectors.map((s: any) => ({
          sector: s.sector,
          change_pct: s.change_pct,
        })),
        topNews: news.map((a: any) => a.headline).filter(Boolean),
      },
      date
    );
  }, [indices, sectors, news]);

  useEffect(() => {
    if (isLoading || !indices.length) return;
    const text = buildBrief();
    setBriefText(text);
    setDisplayText("");

    let i = 0;
    let lastTime = 0;
    let rafId: number;
    const CHAR_INTERVAL = 18;

    const tick = (timestamp: number) => {
      if (timestamp - lastTime >= CHAR_INTERVAL) {
        i++;
        setDisplayText(text.slice(0, i));
        lastTime = timestamp;
      }
      if (i < text.length) {
        rafId = requestAnimationFrame(tick);
      }
    };

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [animKey, isLoading, buildBrief, indices.length]);

  const now = new Date();
  const dateLabel = now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  const timeLabel = now.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

  return (
    <div className="relative rounded-xl overflow-hidden border border-[var(--border-subtle)] card-glow"
      style={{
        background: "linear-gradient(135deg, var(--bg-elevated) 0%, var(--bg-elevated-2) 100%)",
        borderLeft: "3px solid var(--accent-positive)",
      }}
    >
      <div className="px-5 py-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-base shrink-0">🌅</span>
            <h2 className="text-sm font-semibold text-[var(--text-primary)] shrink-0">Morning Brief</h2>
            <span className="text-xs text-[var(--text-tertiary)] font-mono truncate hidden sm:block">
              {dateLabel} · {timeLabel}
            </span>
            <span className="text-xs text-[var(--text-tertiary)] font-mono truncate sm:hidden">
              {timeLabel}
            </span>
          </div>
          <button
            onClick={() => setAnimKey((k) => k + 1)}
            title="Regenerate brief"
            className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors duration-150 p-1 rounded cursor-pointer"
          >
            <RefreshCw size={14} />
          </button>
        </div>

        {isLoading || !indices.length ? (
          <Skeleton rows={3} height={14} className="mb-1" />
        ) : (
          <p className="text-[var(--text-secondary)] text-sm leading-relaxed min-h-[3.5rem]">
            {displayText}
            {displayText.length < briefText.length && (
              <span className="inline-block w-0.5 h-4 bg-[var(--accent-positive)] ml-0.5 animate-pulse align-middle" />
            )}
          </p>
        )}

        <div className="mt-3 pt-3 border-t border-[var(--border-subtle)]">
          <span className="text-[10px] text-[var(--text-tertiary)] font-medium tracking-wide">
            Powered by BMG Intelligence
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Index Card ────────────────────────────────────────────────────────────────

function IndexCard({ symbol, price, change, change_pct }: {
  symbol: string; price: number; change: number; change_pct: number;
}) {
  const navigate = useNavigate();
  const isPos = change_pct >= 0;
  const accentColor = isPos ? "var(--accent-positive)" : "var(--accent-negative)";
  return (
    <div
      onClick={() => navigate(`/chart?symbol=${symbol}`)}
      className="relative rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-5 flex flex-col gap-2 hover:border-[var(--border-emphasis)] transition-colors duration-150 cursor-pointer overflow-hidden group card-glow"
      style={{ borderTop: `2px solid ${accentColor}` }}
    >
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest">
          {INDEX_NAMES[symbol] ?? symbol}
        </span>
        <div className="flex items-center gap-1.5">
          <span className="text-[var(--text-tertiary)] text-xs font-mono">{symbol}</span>
          <LineChart size={11} className="text-[var(--text-tertiary)] group-hover:text-[var(--accent-positive)] transition-colors" />
        </div>
      </div>
      <div className="text-xl font-semibold text-[var(--text-primary)] tracking-tight font-mono">
        {formatCurrency(price)}
      </div>
      <div className="flex items-center gap-2">
        <span className={cn(
          "text-xs font-semibold px-2 py-0.5 rounded-full",
          isPos
            ? "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)]"
            : "bg-[var(--accent-negative-bg)] text-[var(--accent-negative)]"
        )}>
          {isPos ? "+" : ""}{formatPercent(change_pct)}
        </span>
        <span className="text-[var(--text-tertiary)] text-xs font-mono">
          ({isPos ? "+" : ""}{change.toFixed(2)})
        </span>
      </div>
      <div className="h-0.5 rounded-full mt-1 overflow-hidden bg-[var(--bg-elevated-2)]">
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${Math.min(Math.abs(change_pct) * 10, 100)}%`,
            background: isPos ? "var(--accent-positive)" : "var(--accent-negative)",
            opacity: 0.5,
          }}
        />
      </div>
    </div>
  );
}

// ── Sector Row ────────────────────────────────────────────────────────────────

function SectorRow({ sector, symbol, change_pct, max }: { sector: string; symbol?: string; change_pct: number; max: number }) {
  const navigate = useNavigate();
  const isPos = change_pct >= 0;
  const barPct = Math.abs(change_pct) / Math.max(max, 0.1) * 100;
  const label = sector.replace("Select Sector SPDR Fund", "").replace("SPDR", "").trim();
  return (
    <div
      onClick={() => symbol && navigate(`/chart?symbol=${symbol}`)}
      className={cn(
        "flex items-center gap-3 py-2.5 border-b border-[var(--border-subtle)] last:border-0 transition-colors duration-150",
        symbol && "cursor-pointer hover:bg-[var(--bg-elevated-2)]/40 -mx-2 px-2 rounded"
      )}
    >
      <span className="text-xs text-[var(--text-secondary)] w-36 shrink-0 truncate">{label}</span>
      <div className="flex-1 h-1 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${Math.min(barPct, 100)}%`,
            background: isPos ? "var(--accent-positive)" : "var(--accent-negative)",
            opacity: 0.7,
          }}
        />
      </div>
      <span className={cn(
        "text-xs font-mono font-medium w-14 text-right shrink-0",
        isPos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"
      )}>
        {isPos ? "+" : ""}{formatPercent(change_pct)}
      </span>
    </div>
  );
}

// ── News Card ─────────────────────────────────────────────────────────────────

function NewsCard({ article }: { article: any }) {
  const ago = (() => {
    const diff = Date.now() - new Date(article.published_at).getTime();
    const h = Math.floor(diff / 3_600_000);
    const m = Math.floor(diff / 60_000);
    if (h >= 24) return `${Math.floor(h / 24)}d ago`;
    if (h >= 1) return `${h}h ago`;
    return `${m}m ago`;
  })();
  return (
    <a
      href={article.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex items-start gap-3 py-3 border-b border-[var(--border-subtle)] last:border-0 hover:bg-[var(--bg-elevated-2)]/30 -mx-4 px-4 transition-colors duration-150 rounded cursor-pointer"
    >
      <div className="flex-1 min-w-0">
        <p className="text-sm text-[var(--text-secondary)] font-medium line-clamp-2 group-hover:text-[var(--text-primary)] transition-colors">
          {article.headline}
        </p>
        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-[11px] text-[var(--text-tertiary)] font-medium">{article.source}</span>
          <span className="text-[var(--border-emphasis)]">·</span>
          <span className="text-[11px] text-[var(--text-tertiary)]">{ago}</span>
        </div>
      </div>
      <ExternalLink size={13} className="text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)] mt-0.5 shrink-0" />
    </a>
  );
}

// ── Paper Account Widget ──────────────────────────────────────────────────────

function PaperAccountWidget() {
  const navigate = useNavigate();
  const { data: account, isLoading, isError } = useQuery({
    queryKey: ["paper-account"],
    queryFn: getAccount,
    staleTime: 30_000,
    retry: false,
  });

  if (isLoading) return <SkeletonCard className="h-28" />;
  if (isError) return (
    <div className="text-[var(--text-secondary)] text-sm p-4">Failed to load data. Please refresh.</div>
  );
  if (!account) return null;

  const isPos = account.day_pnl >= 0;
  const hasPositions = account.positions.length > 0;

  return (
    <Card glow onClick={() => navigate("/paper")} className="cursor-pointer hover:border-[var(--border-emphasis)] transition-colors duration-150" variant="default">
      <div className="flex items-start justify-between gap-2 mb-4">
        <div>
          <CardLabel className="mb-1">Paper Portfolio</CardLabel>
          <div className="text-2xl font-semibold text-[var(--text-primary)] font-mono leading-none">
            {formatCurrency(account.equity)}
          </div>
        </div>
        <span className="text-[var(--text-tertiary)] text-xs flex items-center gap-1 shrink-0 mt-1">
          View <ArrowRight size={11} />
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="bg-[var(--bg-base)] rounded-lg px-3 py-2">
          <div className="text-[10px] text-[var(--text-tertiary)] mb-0.5">Day P&amp;L</div>
          <span className={cn(
            "text-sm font-semibold font-mono",
            isPos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"
          )}>
            {isPos ? "▲" : "▼"} {formatCurrency(Math.abs(account.day_pnl))}
          </span>
        </div>
        <div className="bg-[var(--bg-base)] rounded-lg px-3 py-2">
          <div className="text-[10px] text-[var(--text-tertiary)] mb-0.5">Positions</div>
          <div className="text-sm font-semibold text-[var(--text-primary)]">
            {hasPositions ? account.positions.length : "—"}
          </div>
        </div>
      </div>
    </Card>
  );
}

// ── Portfolio Widget ──────────────────────────────────────────────────────────

function PortfolioWidget() {
  const navigate = useNavigate();
  const quotes = useMarketStore((s) => s.quotes);
  const { data: rawPortfolios, isLoading } = useQuery({
    queryKey: ["portfolios"],
    queryFn: getPortfolios,
    staleTime: 30_000,
  });
  const portfolios: any[] = Array.isArray(rawPortfolios) ? rawPortfolios : [];

  if (isLoading) {
    return (
      <Card>
        <Skeleton height={14} className="w-24 mb-4" />
        <Skeleton height={32} className="w-36 mb-4" />
        <div className="space-y-2.5">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} height={36} />)}
        </div>
      </Card>
    );
  }

  const allPositions = portfolios.flatMap((p: any) => Array.isArray(p.positions) ? p.positions : []);
  const totalValue = allPositions.reduce((sum, pos) => sum + pos.shares * (quotes[pos.symbol]?.price ?? 0), 0);
  const totalCost = allPositions.reduce((sum, pos) => sum + pos.cost_basis, 0);
  const totalGain = totalValue - totalCost;
  const gainPct = totalCost > 0 ? (totalGain / totalCost) * 100 : 0;
  const isPos = totalGain >= 0;

  const topHoldings = [...allPositions]
    .sort((a, b) => {
      const aVal = a.shares * (quotes[a.symbol]?.price ?? 0);
      const bVal = b.shares * (quotes[b.symbol]?.price ?? 0);
      return bVal - aVal;
    })
    .slice(0, 4);

  return (
    <Card glow>
      <div className="flex items-center justify-between mb-4">
        <CardLabel className="mb-0 flex items-center gap-1.5">
          <Briefcase size={12} /> Portfolio
        </CardLabel>
        <button
          onClick={() => navigate("/portfolio")}
          className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-xs flex items-center gap-1 transition-colors duration-150 cursor-pointer"
        >
          View all <ArrowRight size={11} />
        </button>
      </div>
      {allPositions.length === 0 ? (
        <div className="py-4 text-center text-[var(--text-tertiary)] text-sm">
          No positions yet.{" "}
          <button onClick={() => navigate("/portfolio")} className="text-[var(--text-primary)] hover:underline cursor-pointer">Add one →</button>
        </div>
      ) : (
        <>
          <div className="mb-4 pb-4 border-b border-[var(--border-subtle)]">
            <div className="text-2xl font-semibold text-[var(--text-primary)] font-mono">{formatCurrency(totalValue)}</div>
            {totalCost > 0 && (
              <div className="flex items-center gap-2 mt-1.5">
                <span className={cn(
                  "text-xs font-semibold px-2 py-0.5 rounded-full",
                  isPos
                    ? "bg-[var(--accent-positive-bg)] text-[var(--accent-positive)]"
                    : "bg-[var(--accent-negative-bg)] text-[var(--accent-negative)]"
                )}>
                  {isPos ? "+" : ""}{formatPercent(gainPct)}
                </span>
                <span className={cn(
                  "text-xs font-mono",
                  isPos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"
                )}>
                  {isPos ? "+" : ""}{formatCurrency(totalGain)}
                </span>
              </div>
            )}
          </div>
          <div className="space-y-1">
            {topHoldings.map((pos) => {
              const price = quotes[pos.symbol]?.price ?? 0;
              const mv = pos.shares * price;
              const pnl = mv - pos.cost_basis;
              const isPosRow = pnl >= 0;
              return (
                <div
                  key={pos.symbol}
                  className="flex items-center justify-between cursor-pointer hover:bg-[var(--bg-elevated-2)]/50 -mx-2 px-2 py-1.5 rounded transition-colors duration-150"
                  onClick={() => navigate(`/chart?symbol=${pos.symbol}`)}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-[var(--text-primary)] text-sm">{pos.symbol}</span>
                    <SectorPill symbol={pos.symbol} />
                  </div>
                  <div className="text-right">
                    <div className="text-sm text-[var(--text-primary)] font-mono">{price > 0 ? formatCurrency(mv) : "—"}</div>
                    {price > 0 && (
                      <div className={cn(
                        "text-xs font-mono",
                        isPosRow ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]"
                      )}>
                        {formatPercent((pnl / pos.cost_basis) * 100)}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </Card>
  );
}

// ── Strategy Widget ───────────────────────────────────────────────────────────

function StrategyWidget() {
  const navigate = useNavigate();
  const { data: tradesData, isLoading } = useQuery({
    queryKey: ["strategy-trades"],
    queryFn: getTrades,
    staleTime: 55_000,
  });
  const trades: any[] = Array.isArray(tradesData?.trades) ? tradesData.trades : [];

  if (isLoading) {
    return (
      <Card>
        <Skeleton height={14} className="w-32 mb-4" />
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <Skeleton key={i} height={36} />)}
        </div>
      </Card>
    );
  }

  const open = trades.filter((t) => t.status === "open").slice(0, 4);
  const watching = trades.filter((t) => t.status === "candidate").slice(0, 4);

  return (
    <Card glow>
      <div className="flex items-center justify-between mb-4">
        <CardLabel className="mb-0 flex items-center gap-1.5">
          <FlaskConical size={12} /> Strategy Signals
        </CardLabel>
        <button
          onClick={() => navigate("/strategy")}
          className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-xs flex items-center gap-1 transition-colors duration-150 cursor-pointer"
        >
          View all <ArrowRight size={11} />
        </button>
      </div>
      {open.length + watching.length === 0 ? (
        <div className="py-4 text-center text-[var(--text-tertiary)] text-sm">No active signals</div>
      ) : (
        <div className="space-y-1">
          {open.length > 0 && (
            <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1.5">Open</div>
          )}
          {open.map((t: any) => (
            <div
              key={t.id}
              className="flex items-center justify-between cursor-pointer hover:bg-[var(--bg-elevated-2)]/50 -mx-2 px-2 py-1.5 rounded transition-colors duration-150"
              onClick={() => navigate(`/chart?symbol=${t.symbol}`)}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-[var(--text-primary)] text-sm">{t.symbol}</span>
                <SectorPill symbol={t.symbol} />
              </div>
              <span className="text-xs font-semibold text-[var(--accent-positive)] bg-[var(--accent-positive-bg)] border border-[var(--accent-positive)]/20 px-1.5 py-px rounded">
                Open
              </span>
            </div>
          ))}
          {watching.length > 0 && (
            <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mt-2 mb-1.5">Watching</div>
          )}
          {watching.map((t: any) => (
            <div
              key={t.id}
              className="flex items-center justify-between cursor-pointer hover:bg-[var(--bg-elevated-2)]/50 -mx-2 px-2 py-1.5 rounded transition-colors duration-150"
              onClick={() => navigate(`/chart?symbol=${t.symbol}`)}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-[var(--text-primary)] text-sm">{t.symbol}</span>
                <SectorPill symbol={t.symbol} />
              </div>
              <span className="text-xs text-[#F59E0B] bg-[#F59E0B]/10 border border-[#F59E0B]/20 px-1.5 py-px rounded">
                Watch
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ── Latest Recap Widget ───────────────────────────────────────────────────────

function LatestRecapWidget() {
  const { data: recap, isLoading } = useQuery({
    queryKey: ["recap-latest"],
    queryFn: getLatestRecap,
    staleTime: 300_000,
  });

  if (isLoading) {
    return (
      <Card>
        <Skeleton height={12} className="w-28 mb-3" />
        <Skeleton height={36} className="mb-2" />
        <Skeleton height={14} className="w-4/5" />
      </Card>
    );
  }

  return (
    <Card glow>
      <div className="flex items-center justify-between mb-3">
        <CardLabel className="mb-0 flex items-center gap-1.5">
          <Calendar size={12} /> Daily Recap
        </CardLabel>
      </div>
      {recap ? (
        <DailyRecapCard recap={recap} defaultExpanded={false} />
      ) : (
        <div className="flex flex-col items-center justify-center py-5 text-center gap-2">
          <Calendar size={24} className="text-[var(--border-emphasis)]" />
          <p className="text-sm text-[var(--text-tertiary)]">Daily recap generates at 4:15 PM ET</p>
          <p className="text-xs text-[var(--text-tertiary)] opacity-60">Check back after market close</p>
        </div>
      )}
    </Card>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const { data: rawIndices, isLoading: indicesLoading } = useQuery({
    queryKey: ["market-overview"],
    queryFn: getMarketOverview,
    refetchInterval: 60_000,
  });
  const { data: rawSectors, isLoading: sectorsLoading } = useQuery({
    queryKey: ["sectors"],
    queryFn: getSectorPerformance,
    refetchInterval: 60_000,
  });
  const { data: rawNews, isLoading: newsLoading } = useQuery({
    queryKey: ["news"],
    queryFn: () => getNews(),
    staleTime: 300_000,
  });

  const indices: any[] = Array.isArray(rawIndices) ? rawIndices : [];
  const sectors: any[] = Array.isArray(rawSectors) ? rawSectors : [];
  const news: any[] = Array.isArray(rawNews) ? rawNews : [];

  const briefLoading = indicesLoading || sectorsLoading;
  const maxSectorMove = Math.max(...sectors.map((s: any) => Math.abs(s.change_pct)), 0.1);
  const advancers = sectors.filter((s: any) => s.change_pct > 0).length;
  const decliners = sectors.filter((s: any) => s.change_pct < 0).length;

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-20 md:pb-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight font-display">Market Overview</h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5 truncate">
            {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
          </p>
        </div>
        {sectors.length > 0 && (
          <div className="flex items-center gap-2 text-xs shrink-0 mt-1">
            <span className="text-[var(--accent-positive)] font-medium">
              {advancers}<span className="hidden sm:inline"> advancing</span><span className="sm:hidden">↑</span>
            </span>
            <span className="text-[var(--border-emphasis)]">·</span>
            <span className="text-[var(--accent-negative)] font-medium">
              {decliners}<span className="hidden sm:inline"> declining</span><span className="sm:hidden">↓</span>
            </span>
          </div>
        )}
      </div>

      {/* AI Morning Brief */}
      <MorningBrief indices={indices} sectors={sectors} news={news} isLoading={briefLoading} />

      {/* Paper Account Widget */}
      <PaperAccountWidget />

      {/* Index cards */}
      {indicesLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[1, 2, 3, 4].map((i) => <SkeletonCard key={i} />)}
        </div>
      ) : indices.length > 0 ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {indices.map((idx: any) => <IndexCard key={idx.symbol} {...idx} />)}
        </div>
      ) : null}

      {/* Portfolio + Strategy row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PortfolioWidget />
        <StrategyWidget />
      </div>

      {/* Latest Recap */}
      <LatestRecapWidget />

      {/* Sectors + News */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Sector Performance */}
        <Card glow>
          <CardLabel className="flex items-center gap-1.5">Sector Performance</CardLabel>
          {sectorsLoading ? (
            <div className="space-y-3">
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <div key={i} className="flex items-center gap-3 py-1">
                  <Skeleton height={12} className="w-28 shrink-0" />
                  <Skeleton height={6} className="flex-1" />
                  <Skeleton height={12} className="w-12 shrink-0" />
                </div>
              ))}
            </div>
          ) : (
            <div>
              {[...sectors]
                .sort((a: any, b: any) => b.change_pct - a.change_pct)
                .map((s: any) => (
                  <SectorRow key={s.sector} sector={s.sector} symbol={s.symbol} change_pct={s.change_pct} max={maxSectorMove} />
                ))}
            </div>
          )}
        </Card>

        {/* Market News */}
        <Card glow>
          <CardLabel>Market News</CardLabel>
          {newsLoading ? (
            <div className="space-y-4">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="flex flex-col gap-1.5 py-2 border-b border-[var(--border-subtle)] last:border-0">
                  <Skeleton height={14} />
                  <Skeleton height={14} className="w-4/5" />
                  <Skeleton height={11} className="w-28" />
                </div>
              ))}
            </div>
          ) : (
            <div>
              {news.slice(0, 8).map((article: any) => (
                <NewsCard key={article.id} article={article} />
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

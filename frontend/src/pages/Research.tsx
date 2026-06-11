import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getFundamentals } from "@/api/research";
import { getNews } from "@/api/market";
import { useMarketStore } from "@/store";
import { formatCurrency, formatPercent, formatVolume, timeAgo, cn } from "@/lib/utils";
import { LineChart, ExternalLink, Search, Building2, Globe, Users, Bot } from "lucide-react";
import SectorPill from "@/components/ui/SectorPill";
import ExplainButton from "@/components/explain/ExplainButton";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import ReadingLevelSlider, { type ReadingLevel } from "@/components/ui/ReadingLevelSlider";
import client from "@/api/client";
import { EmptyState } from "@/components/design";

// Labels that have glossary entries — gets an ExplainButton
const EXPLAINABLE = new Set([
  "P/E Ratio", "EPS (TTM)", "Beta", "Dividend Yield", "P/B Ratio",
  "Free Cash Flow", "ROE", "ROA", "Profit Margin", "Debt/Equity",
  "Market Cap", "Short % of Float",
]);

function StatCard({ label, value, sub }: { label: string; value: string | null; sub?: string }) {
  if (value == null) return null;
  return (
    <div className="bg-t-bg2/50 rounded-lg p-3">
      <div className="flex items-center gap-1 text-[10px] text-t-muted uppercase tracking-wider mb-1 font-ui-t">
        <span>{label}</span>
        {EXPLAINABLE.has(label) && (
          <ExplainButton term={label} context="Research fundamentals panel" />
        )}
      </div>
      <div className="text-t-hi font-semibold text-sm font-mono-t tabular-nums">{value}</div>
      {sub && <div className="text-[10px] text-t-muted mt-0.5 font-ui-t">{sub}</div>}
    </div>
  );
}

function fmt(v?: number | null, fn: (n: number) => string = String): string | null {
  return v != null ? fn(v) : null;
}

function fmtLarge(v?: number | null): string | null {
  if (v == null) return null;
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  return `$${v.toLocaleString()}`;
}

function fmtPct(v?: number | null): string | null {
  if (v == null) return null;
  return `${(v * 100).toFixed(2)}%`;
}

function fmtNum(v?: number | null, decimals = 2): string | null {
  if (v == null) return null;
  return v.toFixed(decimals);
}

// ── Financials tab ────────────────────────────────────────────────────────────

interface QuarterRow {
  period: string;
  revenue: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  net_income: number | null;
  eps: number | null;
}

interface FinancialsTabProps {
  financials: { quarterly: QuarterRow[] } | null;
}

function fmtFinVal(v: number | null): string {
  if (v == null) return "—";
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  return `${sign}$${abs.toLocaleString()}`;
}

function fmtEps(v: number | null): string {
  if (v == null) return "—";
  return `$${v.toFixed(2)}`;
}

function pctChange(current: number | null, prior: number | null): number | null {
  if (current == null || prior == null || prior === 0) return null;
  return ((current - prior) / Math.abs(prior)) * 100;
}

function FinancialsTab({ financials }: FinancialsTabProps) {
  if (!financials || !financials.quarterly || financials.quarterly.length === 0) {
    return (
      <EmptyState
        icon="📊"
        title="NO FINANCIAL DATA"
        description="Financial statement data is unavailable for this symbol."
      />
    );
  }

  const quarters = financials.quarterly; // newest first

  const rows: { key: keyof QuarterRow; label: string; fmt: (v: number | null) => string }[] = [
    { key: "revenue", label: "Revenue", fmt: fmtFinVal },
    { key: "gross_profit", label: "Gross Profit", fmt: fmtFinVal },
    { key: "operating_income", label: "Operating Income", fmt: fmtFinVal },
    { key: "net_income", label: "Net Income", fmt: fmtFinVal },
    { key: "eps", label: "EPS", fmt: fmtEps },
  ];

  return (
    <div className="bg-t-bg1 border border-t-dim rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-t-dim">
        <h2 className="text-xs font-semibold text-t-muted uppercase tracking-widest font-ui-t">Income Statement — Last {quarters.length} Quarters</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-t-dim text-[11px] text-t-muted uppercase tracking-wide font-ui-t">
              <th className="text-left px-4 py-2 whitespace-nowrap">Metric</th>
              {quarters.map((q) => (
                <th key={q.period} className="text-right px-4 py-2 whitespace-nowrap font-mono-t">{q.period}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, label, fmt }) => (
              <tr key={key} className="border-b border-t-dim/50">
                <td className="px-4 py-3 text-t-muted text-xs font-medium whitespace-nowrap font-ui-t">{label}</td>
                {quarters.map((q, qi) => {
                  const val = q[key] as number | null;
                  const prior = quarters[qi + 1]?.[key] as number | null | undefined;
                  const chg = pctChange(val, prior ?? null);
                  const isUp = chg != null && chg > 0;
                  const isDown = chg != null && chg < 0;
                  return (
                    <td key={q.period} className="px-4 py-3 text-right">
                      <div className={cn(
                        "font-semibold text-sm font-mono-t tabular-nums",
                        isUp ? "text-t-green" : isDown ? "text-t-red" : "text-t-hi"
                      )}>
                        {fmt(val)}
                      </div>
                      {chg != null && (
                        <div className={cn("text-[10px] mt-0.5 font-mono-t tabular-nums", isUp ? "text-t-green" : "text-t-red")}>
                          {isUp ? "+" : ""}{chg.toFixed(1)}% YoY
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const RECOMMENDATION_COLOR: Record<string, string> = {
  "strong_buy": "text-t-green",
  "buy": "text-t-green",
  "hold": "text-t-amber",
  "sell": "text-t-red",
  "strong_sell": "text-t-red",
};

async function rewriteContent(content: string, level: ReadingLevel, context: string): Promise<string> {
  const res = await client.post("/api/copilot/rewrite-level", {
    content,
    level,
    context,
  });
  return res.data.rewritten as string;
}

// ── BMG Score Badge ───────────────────────────────────────────────────────────

const BMG_GRADE_COLOR: Record<string, string> = {
  A: "#26a69a",
  B: "#3b82f6",
  C: "#f59e0b",
  D: "#ef5350",
  F: "#ef5350",
};

const COMPONENT_LABELS: Record<string, string> = {
  value: "Value",
  growth: "Growth",
  profitability: "Profitability",
  momentum: "Momentum",
  analyst: "Analyst",
};

function BmgScoreBadge({
  score,
  grade,
  components,
}: {
  score: number;
  grade: string;
  components: Record<string, number>;
}) {
  const color = BMG_GRADE_COLOR[grade] ?? "#3b82f6";
  const tooltipLines = Object.entries(components)
    .map(([k, v]) => `${COMPONENT_LABELS[k] ?? k}: ${v}/2`)
    .join("\n");

  return (
    <div className="relative mt-3 flex justify-end group">
      <div
        className="flex flex-col items-center justify-center w-16 h-16 rounded-full border-2 cursor-default select-none"
        style={{ borderColor: color, backgroundColor: `${color}18` }}
        title={tooltipLines}
      >
        <span className="text-lg font-bold leading-none font-mono-t tabular-nums" style={{ color }}>{score.toFixed(1)}</span>
        <span className="text-[10px] font-semibold leading-none mt-0.5 font-ui-t" style={{ color }}>{grade}</span>
      </div>
      {/* Hover tooltip */}
      <div className="absolute bottom-full right-0 mb-2 hidden group-hover:block z-10 pointer-events-none">
        <div className="bg-t-bg1 border border-t-mid rounded-lg p-3 shadow-xl min-w-[160px]">
          <div className="text-[11px] font-semibold text-t-muted uppercase tracking-wider mb-2 font-ui-t">BMG Score</div>
          {Object.entries(components).map(([k, v]) => (
            <div key={k} className="flex items-center justify-between gap-4 text-xs py-0.5">
              <span className="text-t-mid2 font-ui-t">{COMPONENT_LABELS[k] ?? k}</span>
              <span className="font-semibold text-t-hi font-mono-t tabular-nums">{v}/2</span>
            </div>
          ))}
          <div className="border-t border-t-dim mt-2 pt-2 flex items-center justify-between text-xs font-bold">
            <span className="text-t-mid2 font-ui-t">Total</span>
            <span className="font-mono-t tabular-nums" style={{ color }}>{score.toFixed(1)}/10 &nbsp;{grade}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

type ResearchTab = "overview" | "financials" | "news";

export default function Research() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [searchInput, setSearchInput] = useState(params.get("symbol") ?? "");
  const [activeSymbol, setActiveSymbol] = useState(params.get("symbol") ?? "");
  const [aiOpen, setAiOpen] = useState(false);
  const [level, setLevel] = useState<ReadingLevel>("investor");
  const [descCache, setDescCache] = useState<Map<string, string>>(new Map());
  const [rewritingDesc, setRewritingDesc] = useState(false);
  const activeRewriteKey = useRef<string | null>(null);
  const [activeTab, setActiveTab] = useState<ResearchTab>("overview");

  const quotes = useMarketStore((s) => s.quotes);
  const liveQuote = activeSymbol ? quotes[activeSymbol] : null;

  const { data: fund, isLoading, error } = useQuery({
    queryKey: ["research", activeSymbol],
    queryFn: () => getFundamentals(activeSymbol),
    enabled: !!activeSymbol,
    staleTime: 300_000,
  });

  const { data: news = [] } = useQuery({
    queryKey: ["news", activeSymbol],
    queryFn: () => getNews([activeSymbol]),
    enabled: !!activeSymbol,
    staleTime: 120_000,
  });

  // Rewrite description when level changes (except investor = default)
  useEffect(() => {
    if (!fund?.description || level === "investor") return;

    const cacheKey = `${activeSymbol}:${level}`;
    if (descCache.has(cacheKey)) return;

    activeRewriteKey.current = cacheKey;
    setRewritingDesc(true);

    rewriteContent(
      fund.description,
      level,
      `Company description for ${fund.symbol} (${fund.name})`
    ).then((rewritten) => {
      if (activeRewriteKey.current === cacheKey) {
        setDescCache((prev) => new Map(prev).set(cacheKey, rewritten));
        setRewritingDesc(false);
      }
    }).catch(() => {
      if (activeRewriteKey.current === cacheKey) setRewritingDesc(false);
    });

    return () => {
      activeRewriteKey.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [level, activeSymbol, fund?.description]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const sym = searchInput.trim().toUpperCase();
    if (sym) {
      setActiveSymbol(sym);
      navigate(`/research?symbol=${sym}`, { replace: true });
    }
  };

  const descCacheKey = `${activeSymbol}:${level}`;
  const displayDescription = level === "investor"
    ? fund?.description
    : (descCache.get(descCacheKey) ?? fund?.description);

  const price = liveQuote?.price ?? fund?.current_price;
  const prevClose = fund?.previous_close;
  const change = price && prevClose ? price - prevClose : null;
  const changePct = change && prevClose ? (change / prevClose) * 100 : null;
  const isPos = (changePct ?? 0) >= 0;

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-page-in">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-t-hi font-ui-t">// COMPANY RESEARCH</h1>
        <ReadingLevelSlider level={level} onChange={setLevel} />
      </div>

      <form onSubmit={handleSearch} className="flex items-center gap-2">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-t-muted" />
          <input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value.toUpperCase())}
            placeholder="Symbol (e.g. AAPL)"
            className="bg-t-bg1 border border-t-mid text-t-hi text-base md:text-sm pl-9 pr-4 py-2 rounded-lg placeholder-t-dim focus:outline-none focus:border-t-hot uppercase w-44 md:w-52 font-mono-t"
          />
        </div>
        <button
          type="submit"
          className="bg-t-green/20 text-t-green border border-t-green/30 font-semibold text-sm px-4 py-2 rounded-lg hover:brightness-110 font-ui-t"
        >
          Research
        </button>
      </form>

      {!activeSymbol && (
        <EmptyState
          icon="🏢"
          title="ENTER A SYMBOL"
          description="Search for a stock symbol to view fundamentals, financials, and news"
          size="lg"
        />
      )}

      {isLoading && (
        <div className="space-y-4">
          <div className="h-28 bg-t-bg1 border border-t-dim rounded-xl animate-pulse" />
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {[...Array(8)].map((_, i) => <div key={i} className="h-16 bg-t-bg1 border border-t-dim rounded-lg animate-pulse" />)}
          </div>
        </div>
      )}

      {error && (
        <div className="bg-t-red/10 border border-t-red/30 rounded-xl p-4 text-t-red text-sm font-ui-t">
          Could not load data for <strong>{activeSymbol}</strong>. Check the symbol and try again.
        </div>
      )}

      {!isLoading && !error && !fund && activeSymbol && (
        <EmptyState
          icon="🔍"
          title={`NO DATA FOR ${activeSymbol}`}
          description="Check the symbol and try again, or tap Retry below."
          size="lg"
          cta={
            <button
              onClick={() => navigate(`/research?symbol=${activeSymbol}`, { replace: true })}
              className="text-xs text-t-green hover:brightness-110 font-semibold font-ui-t"
            >
              Retry ↺
            </button>
          }
        />
      )}

      {fund && !error && (
        <div className="space-y-5">
          {/* Tab row */}
          <div className="flex items-center gap-1 border-b border-t-dim pb-0">
            {(["overview", "financials", "news"] as ResearchTab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={cn(
                  "px-4 py-2 text-sm font-medium capitalize border-b-2 -mb-px transition-colors font-ui-t",
                  activeTab === tab
                    ? "border-t-green text-t-hi"
                    : "border-transparent text-t-muted hover:text-t-mid2"
                )}
              >
                {tab}
              </button>
            ))}
          </div>

          {/* ── OVERVIEW TAB ── */}
          {activeTab === "overview" && <>
          {/* Header */}
          <div className="bg-t-bg1 border border-t-dim rounded-xl p-5">
            <div className="flex items-start justify-between gap-4 flex-wrap sm:flex-nowrap">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-3xl font-bold text-t-hi font-mono-t tabular-nums">{fund.symbol}</span>
                  <SectorPill symbol={fund.symbol} className="text-xs" />
                </div>
                <div className="text-t-mid2 text-sm font-ui-t">{fund.name}</div>
                {fund.industry && <div className="text-t-muted text-xs mt-0.5 font-ui-t">{fund.industry}</div>}
                <div className="flex items-center gap-3 mt-2 flex-wrap">
                  {fund.country && (
                    <span className="flex items-center gap-1 text-xs text-t-muted font-ui-t">
                      <Globe size={11} /> {fund.country}
                    </span>
                  )}
                  {fund.employees && (
                    <span className="flex items-center gap-1 text-xs text-t-muted font-ui-t">
                      <Users size={11} /> {fund.employees.toLocaleString()} employees
                    </span>
                  )}
                  {fund.website && (
                    <a href={fund.website} target="_blank" rel="noopener noreferrer"
                      className="flex items-center gap-1 text-xs text-t-muted hover:text-t-hi transition-colors font-ui-t">
                      <ExternalLink size={11} /> Website
                    </a>
                  )}
                </div>
              </div>
              <div className="text-right">
                {price && (
                  <div className="text-3xl font-bold text-t-hi font-mono-t tabular-nums">{formatCurrency(price)}</div>
                )}
                {changePct != null && (
                  <div className={cn("text-sm font-medium mt-1 font-mono-t tabular-nums", isPos ? "text-t-green" : "text-t-red")}>
                    {formatPercent(changePct)}
                    {change != null && <span className="ml-1 text-xs opacity-75">({change >= 0 ? "+" : ""}{change.toFixed(2)})</span>}
                  </div>
                )}
                <div className="mt-2 flex items-center gap-2 justify-end">
                  <button
                    onClick={() => navigate(`/chart?symbol=${fund.symbol}`)}
                    className="flex items-center gap-1.5 bg-t-green/20 text-t-green border border-t-green/30 text-xs font-semibold px-3 py-1.5 rounded-lg hover:brightness-110 transition-colors font-ui-t"
                  >
                    <LineChart size={12} /> View Chart
                  </button>
                  <button
                    onClick={() => setAiOpen(true)}
                    className="flex items-center gap-1.5 bg-t-cyan/20 hover:bg-t-cyan/30 text-t-cyan border border-t-cyan/30 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors font-ui-t"
                  >
                    <Bot size={12} /> Ask AI
                  </button>
                </div>
                {fund.bmg_score && (
                  <BmgScoreBadge
                    score={fund.bmg_score.score}
                    grade={fund.bmg_score.grade}
                    components={fund.bmg_score.components}
                  />
                )}
              </div>
            </div>
          </div>

          {/* Key stats */}
          <div>
            <h2 className="text-xs font-semibold text-t-muted uppercase tracking-widest mb-3 font-ui-t">Key Statistics</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              <StatCard label="Market Cap" value={fmtLarge(fund.market_cap)} />
              <StatCard label="P/E Ratio" value={fmtNum(fund.pe_ratio)} sub={`Forward: ${fmtNum(fund.forward_pe) ?? "—"}`} />
              <StatCard label="EPS (TTM)" value={fund.eps != null ? `$${fund.eps.toFixed(2)}` : null} />
              <StatCard label="52W High" value={fund.week_52_high != null ? formatCurrency(fund.week_52_high) : null} />
              <StatCard label="52W Low" value={fund.week_52_low != null ? formatCurrency(fund.week_52_low) : null} />
              <StatCard label="Volume" value={fmt(fund.volume, formatVolume)} sub={`Avg: ${fmt(fund.avg_volume, formatVolume) ?? "—"}`} />
              <StatCard label="Beta" value={fmtNum(fund.beta)} />
              <StatCard label="Dividend Yield" value={fmtPct(fund.dividend_yield)} sub={fund.dividend_rate ? `$${fund.dividend_rate.toFixed(2)}/yr` : undefined} />
              <StatCard label="P/B Ratio" value={fmtNum(fund.price_to_book)} />
              <StatCard label="Revenue" value={fmtLarge(fund.revenue)} />
              <StatCard label="Net Income" value={fmtLarge(fund.net_income)} />
              <StatCard label="Free Cash Flow" value={fmtLarge(fund.free_cashflow)} />
              <StatCard label="ROE" value={fmtPct(fund.return_on_equity)} />
              <StatCard label="ROA" value={fmtPct(fund.return_on_assets)} />
              <StatCard label="Profit Margin" value={fmtPct(fund.profit_margins)} />
              <StatCard label="Debt/Equity" value={fmtNum(fund.debt_to_equity)} />
            </div>
          </div>

          {/* Analyst ratings */}
          {(fund.recommendation || fund.analyst_target) && (
            <div className="bg-t-bg1 border border-t-dim rounded-xl p-4">
              <h2 className="text-xs font-semibold text-t-muted uppercase tracking-widest mb-3 font-ui-t">Analyst Consensus</h2>
              <div className="flex items-center gap-6 flex-wrap">
                {fund.recommendation && (
                  <div>
                    <div className="text-[10px] text-t-muted uppercase tracking-wide mb-1 font-ui-t">Rating</div>
                    <div className={cn("text-lg font-bold uppercase font-ui-t", RECOMMENDATION_COLOR[fund.recommendation] ?? "text-t-mid2")}>
                      {fund.recommendation.replace(/_/g, " ")}
                    </div>
                    {fund.num_analysts && <div className="text-xs text-t-muted mt-0.5 font-ui-t">{fund.num_analysts} analysts</div>}
                  </div>
                )}
                {fund.analyst_target && (
                  <div>
                    <div className="text-[10px] text-t-muted uppercase tracking-wide mb-1 font-ui-t">Price Target</div>
                    <div className="text-lg font-bold text-t-hi font-mono-t tabular-nums">{formatCurrency(fund.analyst_target)}</div>
                    {fund.analyst_low && fund.analyst_high && (
                      <div className="text-xs text-t-muted mt-0.5 font-mono-t tabular-nums">
                        {formatCurrency(fund.analyst_low)} – {formatCurrency(fund.analyst_high)}
                      </div>
                    )}
                  </div>
                )}
                {price && fund.analyst_target && (
                  <div>
                    <div className="text-[10px] text-t-muted uppercase tracking-wide mb-1 font-ui-t">Upside</div>
                    <div className={cn("text-lg font-bold font-mono-t tabular-nums", ((fund.analyst_target - price) / price) >= 0 ? "text-t-green" : "text-t-red")}>
                      {formatPercent(((fund.analyst_target - price) / price) * 100)}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Short interest */}
          {(fund.short_ratio || fund.short_percent) && (
            <div className="bg-t-bg1 border border-t-dim rounded-xl p-4">
              <h2 className="text-xs font-semibold text-t-muted uppercase tracking-widest mb-3 font-ui-t">Short Interest</h2>
              <div className="flex items-center gap-6">
                {fund.short_percent && (
                  <StatCard label="Short % of Float" value={fmtPct(fund.short_percent)} />
                )}
                {fund.short_ratio && (
                  <StatCard label="Short Ratio (Days)" value={fmtNum(fund.short_ratio, 1)} />
                )}
              </div>
            </div>
          )}

          {/* Description */}
          {fund.description && (
            <div className="bg-t-bg1 border border-t-dim rounded-xl p-4">
              <h2 className="text-xs font-semibold text-t-muted uppercase tracking-widest mb-3 font-ui-t">About</h2>
              <p className={cn(
                "text-t-mid2 text-sm leading-relaxed line-clamp-6 font-ui-t",
                rewritingDesc && "opacity-50 animate-pulse"
              )}>
                {rewritingDesc ? "Rewriting…" : displayDescription}
              </p>
            </div>
          )}
          </> /* end overview tab */}

          {/* ── FINANCIALS TAB ── */}
          {activeTab === "financials" && (
            <FinancialsTab financials={fund.financials ?? null} />
          )}

          {/* ── NEWS TAB ── */}
          {activeTab === "news" && (
            <div className="space-y-2">
              {news.length === 0 ? (
                <EmptyState
                  icon="📰"
                  title="NO RECENT NEWS"
                  description={`No news articles found for ${activeSymbol}`}
                />
              ) : (
                news.map((a: any) => (
                  <a
                    key={a.id}
                    href={a.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-start gap-3 p-3 bg-t-bg1 border border-t-dim rounded-lg hover:border-t-mid transition-colors group card-hover"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-t-hi font-medium line-clamp-2 font-ui-t">{a.headline}</div>
                      <div className="flex items-center gap-2 mt-1 text-[11px] text-t-muted font-ui-t">
                        <span>{a.source}</span>
                        <span>·</span>
                        <span>{timeAgo(a.published_at)}</span>
                      </div>
                    </div>
                    <ExternalLink size={13} className="text-t-muted shrink-0 mt-0.5" />
                  </a>
                ))
              )}
            </div>
          )}
        </div>
      )}

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title={activeSymbol ? `Ask BMG about ${activeSymbol}` : "Ask BMG"}
        context={activeSymbol ? `Research page for ${activeSymbol}` : "Research"}
        suggestedQuestions={[
          "What's the bull case?",
          "Any risks I should know?",
          "How does valuation compare to peers?",
          "What do analysts think?",
          "Explain their business model",
        ]}
      />
    </div>
  );
}

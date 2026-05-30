import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getFundamentals } from "@/api/research";
import { getNews } from "@/api/market";
import { useMarketStore } from "@/store";
import { formatCurrency, formatPercent, formatVolume, cn } from "@/lib/utils";
import { LineChart, ExternalLink, Search, Building2, Globe, Users, Bot } from "lucide-react";
import SectorPill from "@/components/ui/SectorPill";
import ExplainButton from "@/components/explain/ExplainButton";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import ReadingLevelSlider, { ReadingLevel } from "@/components/ui/ReadingLevelSlider";
import client from "@/api/client";

// Labels that have glossary entries — gets an ExplainButton
const EXPLAINABLE = new Set([
  "P/E Ratio", "EPS (TTM)", "Beta", "Dividend Yield", "P/B Ratio",
  "Free Cash Flow", "ROE", "ROA", "Profit Margin", "Debt/Equity",
  "Market Cap", "Short % of Float",
]);

function StatCard({ label, value, sub }: { label: string; value: string | null; sub?: string }) {
  if (value == null) return null;
  return (
    <div className="bg-[var(--bg-elevated-2)]/50 rounded-lg p-3">
      <div className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1">
        <span>{label}</span>
        {EXPLAINABLE.has(label) && (
          <ExplainButton term={label} context="Research fundamentals panel" />
        )}
      </div>
      <div className="text-[var(--text-primary)] font-semibold text-sm">{value}</div>
      {sub && <div className="text-[10px] text-[var(--text-tertiary)] mt-0.5">{sub}</div>}
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

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor(diff / 60_000);
  if (h >= 24) return `${Math.floor(h / 24)}d ago`;
  if (h >= 1) return `${h}h ago`;
  return `${m}m ago`;
}

const RECOMMENDATION_COLOR: Record<string, string> = {
  "strong_buy": "text-[var(--accent-positive)]",
  "buy": "text-green-400",
  "hold": "text-yellow-400",
  "sell": "text-[var(--accent-negative)]",
  "strong_sell": "text-red-600",
};

async function rewriteContent(content: string, level: ReadingLevel, context: string): Promise<string> {
  const res = await client.post("/api/copilot/rewrite-level", {
    content,
    level,
    context,
  });
  return res.data.rewritten as string;
}

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
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-[var(--text-primary)]">Company Research</h1>
        <ReadingLevelSlider level={level} onChange={setLevel} />
      </div>

      <form onSubmit={handleSearch} className="flex items-center gap-2">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
          <input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value.toUpperCase())}
            placeholder="Enter symbol (e.g. AAPL)"
            className="bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-base md:text-sm pl-9 pr-4 py-2 rounded-lg placeholder-zinc-600 focus:outline-none focus:border-zinc-600 uppercase w-52"
          />
        </div>
        <button
          type="submit"
          className="bg-[var(--accent-positive)] text-[var(--text-primary)] font-semibold text-sm px-4 py-2 rounded-lg hover:brightness-110"
        >
          Research
        </button>
      </form>

      {!activeSymbol && (
        <div className="text-center py-20 text-[var(--text-tertiary)]">
          <Building2 size={40} className="mx-auto mb-4 text-zinc-800" />
          <p>Enter a stock symbol to view fundamentals, financials, and news</p>
        </div>
      )}

      {isLoading && (
        <div className="space-y-4">
          <div className="h-28 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl animate-pulse" />
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {[...Array(8)].map((_, i) => <div key={i} className="h-16 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg animate-pulse" />)}
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-950/30 border border-red-800/50 rounded-xl p-4 text-[var(--accent-negative)] text-sm">
          Could not load data for <strong>{activeSymbol}</strong>. Check the symbol and try again.
        </div>
      )}

      {fund && !error && (
        <div className="space-y-5">
          {/* Header */}
          <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-5">
            <div className="flex items-start justify-between gap-4 flex-wrap sm:flex-nowrap">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-3xl font-bold text-[var(--text-primary)] font-mono">{fund.symbol}</span>
                  <SectorPill symbol={fund.symbol} className="text-xs" />
                </div>
                <div className="text-[var(--text-secondary)] text-sm">{fund.name}</div>
                {fund.industry && <div className="text-[var(--text-tertiary)] text-xs mt-0.5">{fund.industry}</div>}
                <div className="flex items-center gap-3 mt-2 flex-wrap">
                  {fund.country && (
                    <span className="flex items-center gap-1 text-xs text-[var(--text-tertiary)]">
                      <Globe size={11} /> {fund.country}
                    </span>
                  )}
                  {fund.employees && (
                    <span className="flex items-center gap-1 text-xs text-[var(--text-tertiary)]">
                      <Users size={11} /> {fund.employees.toLocaleString()} employees
                    </span>
                  )}
                  {fund.website && (
                    <a href={fund.website} target="_blank" rel="noopener noreferrer"
                      className="flex items-center gap-1 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors">
                      <ExternalLink size={11} /> Website
                    </a>
                  )}
                </div>
              </div>
              <div className="text-right">
                {price && (
                  <div className="text-3xl font-bold text-[var(--text-primary)]">{formatCurrency(price)}</div>
                )}
                {changePct != null && (
                  <div className={cn("text-sm font-medium mt-1", isPos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                    {isPos ? "+" : ""}{formatPercent(changePct)}
                    {change != null && <span className="ml-1 text-xs opacity-75">({isPos ? "+" : ""}{change.toFixed(2)})</span>}
                  </div>
                )}
                <div className="mt-2 flex items-center gap-2 justify-end">
                  <button
                    onClick={() => navigate(`/chart?symbol=${fund.symbol}`)}
                    className="flex items-center gap-1.5 bg-[var(--accent-positive)] text-[var(--text-primary)] text-xs font-semibold px-3 py-1.5 rounded-lg hover:brightness-110 transition-colors"
                  >
                    <LineChart size={12} /> View Chart
                  </button>
                  <button
                    onClick={() => setAiOpen(true)}
                    className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
                  >
                    <Bot size={12} /> Ask AI
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Key stats */}
          <div>
            <h2 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-widest mb-3">Key Statistics</h2>
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
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
              <h2 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-widest mb-3">Analyst Consensus</h2>
              <div className="flex items-center gap-6 flex-wrap">
                {fund.recommendation && (
                  <div>
                    <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wide mb-1">Rating</div>
                    <div className={cn("text-lg font-bold uppercase", RECOMMENDATION_COLOR[fund.recommendation] ?? "text-[var(--text-secondary)]")}>
                      {fund.recommendation.replace(/_/g, " ")}
                    </div>
                    {fund.num_analysts && <div className="text-xs text-[var(--text-tertiary)] mt-0.5">{fund.num_analysts} analysts</div>}
                  </div>
                )}
                {fund.analyst_target && (
                  <div>
                    <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wide mb-1">Price Target</div>
                    <div className="text-lg font-bold text-[var(--text-primary)]">{formatCurrency(fund.analyst_target)}</div>
                    {fund.analyst_low && fund.analyst_high && (
                      <div className="text-xs text-[var(--text-tertiary)] mt-0.5">
                        {formatCurrency(fund.analyst_low)} – {formatCurrency(fund.analyst_high)}
                      </div>
                    )}
                  </div>
                )}
                {price && fund.analyst_target && (
                  <div>
                    <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wide mb-1">Upside</div>
                    <div className={cn("text-lg font-bold", ((fund.analyst_target - price) / price) >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                      {formatPercent(((fund.analyst_target - price) / price) * 100)}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Short interest */}
          {(fund.short_ratio || fund.short_percent) && (
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
              <h2 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-widest mb-3">Short Interest</h2>
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
            <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4">
              <h2 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-widest mb-3">About</h2>
              <p className={cn(
                "text-[var(--text-secondary)] text-sm leading-relaxed line-clamp-6",
                rewritingDesc && "opacity-50 animate-pulse"
              )}>
                {rewritingDesc ? "Rewriting…" : displayDescription}
              </p>
            </div>
          )}

          {/* News */}
          {news.length > 0 && (
            <div>
              <h2 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-widest mb-3">Recent News</h2>
              <div className="space-y-2">
                {news.slice(0, 5).map((a: any) => (
                  <a
                    key={a.id}
                    href={a.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-start gap-3 p-3 bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-lg hover:border-[var(--border-emphasis)] transition-colors group"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-[var(--text-primary)] font-medium line-clamp-2 group-hover:text-[var(--text-primary)]">{a.headline}</div>
                      <div className="flex items-center gap-2 mt-1 text-[11px] text-[var(--text-tertiary)]">
                        <span>{a.source}</span>
                        <span>·</span>
                        <span>{timeAgo(a.published_at)}</span>
                      </div>
                    </div>
                    <ExternalLink size={13} className="text-[var(--text-tertiary)] group-hover:text-[var(--text-tertiary)] shrink-0 mt-0.5" />
                  </a>
                ))}
              </div>
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

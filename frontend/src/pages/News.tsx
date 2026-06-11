import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getNews } from "@/api/market";
import { ExternalLink, RefreshCw, X, Bot } from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { COMPANY_INFO } from "@/data/companyInfo";
import SectorPill from "@/components/ui/SectorPill";
import GlossaryTooltip from "@/components/explain/GlossaryTooltip";
import ReadingLevelSlider, { type ReadingLevel } from "@/components/ui/ReadingLevelSlider";
import client from "@/api/client";
import AskAIDrawer from "@/components/ui/AskAIDrawer";
import { EmptyState } from "@/components/design";

function SymbolChip({ symbol, onClick }: { symbol: string; onClick: () => void }) {
  const _name = COMPANY_INFO[symbol]?.name;
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-1 text-[10px] font-mono-t font-semibold px-2 py-0.5 rounded-full bg-t-bg2 text-t-muted hover:bg-t-bg2 hover:text-t-hi transition-colors duration-150 cursor-pointer"
    >
      {symbol}
    </button>
  );
}

async function rewriteContent(content: string, level: ReadingLevel): Promise<string> {
  const res = await client.post("/api/copilot/rewrite-level", {
    content,
    level,
    context: "Financial news article summary",
  });
  return res.data.rewritten as string;
}

interface AnalysisResult {
  sentiment: "bullish" | "bearish" | "neutral";
  tldr: string;
  tier: "major" | "notable" | "standard";
}

async function analyzeArticle(
  headline: string,
  summary: string,
  symbol?: string,
): Promise<AnalysisResult> {
  const res = await client.post("/api/news/analyze", { headline, summary, symbol });
  return res.data as AnalysisResult;
}

function TierPill({ tier }: { tier: "major" | "notable" | "standard" }) {
  if (tier === "standard") return null;
  if (tier === "major") {
    return (
      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wide bg-t-red/20 text-t-red border border-t-red/30">
        MAJOR
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wide bg-t-amber/20 text-t-amber border border-t-amber/30">
      NOTABLE
    </span>
  );
}

function SentimentBadge({ sentiment }: { sentiment: "bullish" | "bearish" | "neutral" }) {
  if (sentiment === "bullish") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-medium text-t-green font-ui-t">
        🟢 Bullish
      </span>
    );
  }
  if (sentiment === "bearish") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-medium text-t-red font-ui-t">
        🔴 Bearish
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-t-dim font-ui-t">
      ⚪ Neutral
    </span>
  );
}

function NewsCard({
  article,
  level,
  rewriteCache,
  analyzeCache,
  onSymbolClick,
  onCacheUpdate,
  onAnalyzeCacheUpdate,
}: {
  article: any;
  level: ReadingLevel;
  rewriteCache: Map<string, string>;
  analyzeCache: Map<string, AnalysisResult>;
  onSymbolClick: (s: string) => void;
  onCacheUpdate: (key: string, value: string) => void;
  onAnalyzeCacheUpdate: (key: string, value: AnalysisResult) => void;
}) {
  const ago = timeAgo(article.published_at);
  const cacheKey = `${article.id}:${level}`;
  const cached = rewriteCache.get(cacheKey);

  const [rewriting, setRewriting] = useState(false);
  const [showTldr, setShowTldr] = useState(false);
  const activeKey = useRef<string | null>(null);

  const analysis = analyzeCache.get(String(article.id));

  // Rewrite effect (existing logic unchanged)
  useEffect(() => {
    // "investor" is the default API level — no rewrite needed
    if (level === "investor" || !article.summary) return;
    if (rewriteCache.has(cacheKey)) return;

    activeKey.current = cacheKey;
    setRewriting(true);

    rewriteContent(article.summary, level).then((rewritten) => {
      // Only update if the key is still current (level didn't change while loading)
      if (activeKey.current === cacheKey) {
        onCacheUpdate(cacheKey, rewritten);
        setRewriting(false);
      }
    }).catch(() => {
      if (activeKey.current === cacheKey) setRewriting(false);
    });

    return () => {
      activeKey.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cacheKey]);

  // Analyze effect — fires once per article, lazy/silent
  useEffect(() => {
    const id = String(article.id);
    if (analyzeCache.has(id)) return;
    if (!article.headline) return;

    const primarySymbol: string | undefined = article.symbols?.[0];

    analyzeArticle(article.headline, article.summary ?? "", primarySymbol)
      .then((result) => {
        onAnalyzeCacheUpdate(id, result);
      })
      .catch(() => {
        // Silently fail — UI shows nothing until result arrives
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [article.id]);

  const displaySummary = level === "investor"
    ? article.summary
    : cached ?? article.summary;

  return (
    <div className="bg-t-bg1 border border-t-dim rounded-xl p-4 hover:border-t-mid transition-colors duration-150 group card-hover">
      <div className="flex gap-4">
        <div className="flex-1 min-w-0">
          {/* Header row: headline + tier pill (top-right, only when loaded + non-standard) */}
          <div className="flex items-start justify-between gap-2">
            <a
              href={article.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 min-w-0 text-t-hi font-medium text-sm leading-snug hover:text-t-mid2 transition-colors duration-150 line-clamp-2 group-hover:underline font-ui-t"
            >
              {article.headline}
            </a>
            {analysis && (
              <div className="shrink-0 mt-0.5">
                <TierPill tier={analysis.tier} />
              </div>
            )}
          </div>

          {/* Summary */}
          {displaySummary && (
            <p className={cn(
              "mt-1.5 text-t-muted text-xs leading-relaxed line-clamp-2 font-ui-t",
              rewriting && "opacity-50 animate-pulse"
            )}>
              {rewriting ? "Rewriting…" : <GlossaryTooltip>{displaySummary}</GlossaryTooltip>}
            </p>
          )}

          {/* TL;DR toggle */}
          {!rewriting && article.summary && (
            <div className="mt-1.5">
              {!showTldr ? (
                <button
                  onClick={() => setShowTldr(true)}
                  className="text-[10px] font-semibold text-t-muted hover:text-t-mid2 transition-colors duration-150 cursor-pointer underline decoration-dotted font-ui-t"
                >
                  TL;DR
                </button>
              ) : (
                <div className="flex items-start gap-1.5">
                  <p className="flex-1 text-[11px] text-t-mid2 leading-relaxed italic font-ui-t">
                    {analysis?.tldr ?? "Loading…"}
                  </p>
                  <button
                    onClick={() => setShowTldr(false)}
                    className="shrink-0 text-t-muted hover:text-t-hi transition-colors duration-150 cursor-pointer mt-0.5"
                    aria-label="Close TL;DR"
                  >
                    <X size={11} />
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Footer: source · time · sentiment badge · symbol chips */}
          <div className="mt-2.5 flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2 text-[11px] text-t-muted font-ui-t">
              <span className="font-medium text-t-muted">{article.source}</span>
              <span className="text-t-dim">·</span>
              <span>{ago}</span>
            </div>
            {analysis && (
              <SentimentBadge sentiment={analysis.sentiment} />
            )}
            {article.symbols?.length > 0 && (
              <div className="flex items-center gap-1.5 flex-wrap">
                {article.symbols.slice(0, 5).map((s: string) => (
                  <SymbolChip key={s} symbol={s} onClick={() => onSymbolClick(s)} />
                ))}
              </div>
            )}
          </div>
        </div>
        <a
          href={article.url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 mt-0.5"
        >
          <ExternalLink size={14} className="text-t-muted group-hover:text-t-mid2 transition-colors duration-150" />
        </a>
      </div>
    </div>
  );
}

export default function News() {
  const navigate = useNavigate();
  const [filterSymbol, setFilterSymbol] = useState("");
  const [inputVal, setInputVal] = useState("");
  const [level, setLevel] = useState<ReadingLevel>("investor");
  const [rewriteCache, setRewriteCache] = useState<Map<string, string>>(new Map());
  const [analyzeCache, setAnalyzeCache] = useState<Map<string, AnalysisResult>>(new Map());
  const [aiOpen, setAiOpen] = useState(false);

  const symbols = filterSymbol ? [filterSymbol] : undefined;

  const { data: articles = [], isLoading, refetch, isFetching } = useQuery({
    queryKey: ["news", filterSymbol],
    queryFn: () => getNews(symbols),
    staleTime: 120_000,
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setFilterSymbol(inputVal.trim().toUpperCase());
  };

  const clearFilter = () => {
    setFilterSymbol("");
    setInputVal("");
  };

  const handleCacheUpdate = (key: string, value: string) => {
    setRewriteCache((prev) => new Map(prev).set(key, value));
  };

  const handleAnalyzeCacheUpdate = (key: string, value: AnalysisResult) => {
    setAnalyzeCache((prev) => new Map(prev).set(key, value));
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-page-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-t-hi font-ui-t">// MARKET NEWS</h1>
          <p className="text-t-muted text-sm mt-0.5 font-ui-t">Latest financial news and market updates</p>
        </div>
        <div className="flex items-center gap-3">
          <ReadingLevelSlider level={level} onChange={setLevel} />
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-1.5 text-t-muted hover:text-t-hi transition-colors duration-150 text-sm cursor-pointer font-ui-t"
          >
            <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      <form onSubmit={handleSearch} className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 max-w-xs">
          <input
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value.toUpperCase())}
            placeholder="Filter by symbol (e.g. AAPL)"
            className="w-full bg-t-bg1 border border-t-mid text-t-hi text-base md:text-sm px-3 py-2 rounded-lg placeholder-t-dim focus:outline-none focus:border-t-hot uppercase transition-colors duration-150 font-mono-t"
          />
          {filterSymbol && (
            <button
              type="button"
              onClick={clearFilter}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-t-muted hover:text-t-hi cursor-pointer transition-colors duration-150"
            >
              <X size={13} />
            </button>
          )}
        </div>
        <button
          type="submit"
          className="bg-t-green/20 text-t-green border border-t-green/30 font-semibold text-sm px-4 py-2 rounded-lg hover:brightness-110 transition-colors duration-150 cursor-pointer font-ui-t"
        >
          Filter
        </button>
        {filterSymbol && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-t-muted text-sm font-ui-t">Showing news for</span>
            <span className="font-mono-t font-bold text-t-hi tabular-nums">{filterSymbol}</span>
            {COMPANY_INFO[filterSymbol] && (
              <span className="text-t-muted text-sm font-ui-t">{COMPANY_INFO[filterSymbol].name}</span>
            )}
            <SectorPill symbol={filterSymbol} />
            <button
              onClick={() => navigate(`/chart?symbol=${filterSymbol}`)}
              className="text-xs text-t-muted hover:text-t-hi underline cursor-pointer transition-colors duration-150 font-ui-t"
            >
              View chart →
            </button>
            <button
              onClick={() => setAiOpen(true)}
              className="flex items-center gap-1 text-xs bg-t-cyan/20 hover:bg-t-cyan/30 text-t-cyan border border-t-cyan/30 font-semibold px-2.5 py-1 rounded-lg transition-colors font-ui-t"
            >
              <Bot size={11} /> Ask AI
            </button>
          </div>
        )}
      </form>

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="bg-t-bg1 border border-t-dim rounded-xl p-4 animate-pulse">
              <div className="h-4 bg-t-bg2 rounded w-3/4 mb-2" />
              <div className="h-3 bg-t-bg2/60 rounded w-full mb-1" />
              <div className="h-3 bg-t-bg2/60 rounded w-2/3" />
            </div>
          ))}
        </div>
      ) : articles.length === 0 ? (
        <EmptyState
          icon="📰"
          title={filterSymbol ? `NO NEWS FOR ${filterSymbol}` : "NO NEWS AVAILABLE"}
          description={filterSymbol ? `No articles found matching symbol ${filterSymbol}` : "No market news is currently available"}
        />
      ) : (
        <div className="space-y-3">
          {articles.map((a: any) => (
            <NewsCard
              key={a.id}
              article={a}
              level={level}
              rewriteCache={rewriteCache}
              analyzeCache={analyzeCache}
              onSymbolClick={(s) => { setInputVal(s); setFilterSymbol(s); }}
              onCacheUpdate={handleCacheUpdate}
              onAnalyzeCacheUpdate={handleAnalyzeCacheUpdate}
            />
          ))}
        </div>
      )}

      <AskAIDrawer
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title={filterSymbol ? `Ask BMG about ${filterSymbol}` : "Ask BMG about News"}
        context={filterSymbol ? `News feed filtered for ${filterSymbol}` : "Market News"}
        suggestedQuestions={
          filterSymbol
            ? [
                `What's the sentiment on ${filterSymbol} this week?`,
                "Summarize the recent news",
                "Is this news bullish or bearish?",
                "How should I interpret these headlines?",
              ]
            : [
                "What are the biggest market stories today?",
                "Summarize recent market news",
                "Which sectors are in the news most?",
              ]
        }
      />
    </div>
  );
}

import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getNews } from "@/api/market";
import { ExternalLink, RefreshCw, X, Bot } from "lucide-react";
import { cn } from "@/lib/utils";
import { COMPANY_INFO } from "@/data/companyInfo";
import SectorPill from "@/components/ui/SectorPill";
import GlossaryTooltip from "@/components/explain/GlossaryTooltip";
import ReadingLevelSlider, { type ReadingLevel } from "@/components/ui/ReadingLevelSlider";
import client from "@/api/client";
import AskAIDrawer from "@/components/ui/AskAIDrawer";

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor(diff / 60_000);
  if (h >= 24) return `${Math.floor(h / 24)}d ago`;
  if (h >= 1) return `${h}h ago`;
  return `${m}m ago`;
}

function SymbolChip({ symbol, onClick }: { symbol: string; onClick: () => void }) {
  const name = COMPANY_INFO[symbol]?.name;
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-1 text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full bg-[var(--bg-elevated-2)] text-[var(--text-secondary)] hover:bg-[#334155] hover:text-[var(--text-primary)] transition-colors duration-150 cursor-pointer"
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

function NewsCard({
  article,
  level,
  rewriteCache,
  onSymbolClick,
  onCacheUpdate,
}: {
  article: any;
  level: ReadingLevel;
  rewriteCache: Map<string, string>;
  onSymbolClick: (s: string) => void;
  onCacheUpdate: (key: string, value: string) => void;
}) {
  const ago = timeAgo(article.published_at);
  const cacheKey = `${article.id}:${level}`;
  const cached = rewriteCache.get(cacheKey);

  const [rewriting, setRewriting] = useState(false);
  const activeKey = useRef<string | null>(null);

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

  const displaySummary = level === "investor"
    ? article.summary
    : cached ?? article.summary;

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 hover:border-[var(--border-emphasis)] transition-colors duration-150 group">
      <div className="flex gap-4">
        <div className="flex-1 min-w-0">
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--text-primary)] font-medium text-sm leading-snug hover:text-[var(--text-secondary)] transition-colors duration-150 line-clamp-2 group-hover:underline"
          >
            {article.headline}
          </a>
          {displaySummary && (
            <p className={cn(
              "mt-1.5 text-[var(--text-tertiary)] text-xs leading-relaxed line-clamp-2",
              rewriting && "opacity-50 animate-pulse"
            )}>
              {rewriting ? "Rewriting…" : <GlossaryTooltip>{displaySummary}</GlossaryTooltip>}
            </p>
          )}
          <div className="mt-2.5 flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2 text-[11px] text-[var(--text-tertiary)]">
              <span className="font-medium text-[var(--text-tertiary)]">{article.source}</span>
              <span className="text-[var(--border-emphasis)]">·</span>
              <span>{ago}</span>
            </div>
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
          <ExternalLink size={14} className="text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)] transition-colors duration-150" />
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

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)]">Market News</h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Latest financial news and market updates</p>
        </div>
        <div className="flex items-center gap-3">
          <ReadingLevelSlider level={level} onChange={setLevel} />
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-1.5 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors duration-150 text-sm cursor-pointer"
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
            className="w-full bg-[var(--bg-elevated)] border border-[var(--border-emphasis)] text-[var(--text-primary)] text-base md:text-sm px-3 py-2 rounded-lg placeholder-[#475569] focus:outline-none focus:border-[#3B82F6] uppercase transition-colors duration-150"
          />
          {filterSymbol && (
            <button
              type="button"
              onClick={clearFilter}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] cursor-pointer transition-colors duration-150"
            >
              <X size={13} />
            </button>
          )}
        </div>
        <button
          type="submit"
          className="bg-[var(--accent-positive)] text-[var(--text-primary)] font-semibold text-sm px-4 py-2 rounded-lg hover:brightness-110 transition-colors duration-150 cursor-pointer"
        >
          Filter
        </button>
        {filterSymbol && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[var(--text-tertiary)] text-sm">Showing news for</span>
            <span className="font-mono font-bold text-[var(--text-primary)]">{filterSymbol}</span>
            {COMPANY_INFO[filterSymbol] && (
              <span className="text-[var(--text-tertiary)] text-sm">{COMPANY_INFO[filterSymbol].name}</span>
            )}
            <SectorPill symbol={filterSymbol} />
            <button
              onClick={() => navigate(`/chart?symbol=${filterSymbol}`)}
              className="text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] underline cursor-pointer transition-colors duration-150"
            >
              View chart →
            </button>
            <button
              onClick={() => setAiOpen(true)}
              className="flex items-center gap-1 text-xs bg-blue-600 hover:bg-blue-500 text-white font-semibold px-2.5 py-1 rounded-lg transition-colors"
            >
              <Bot size={11} /> Ask AI
            </button>
          </div>
        )}
      </form>

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded-xl p-4 animate-pulse">
              <div className="h-4 bg-[var(--bg-elevated-2)] rounded w-3/4 mb-2" />
              <div className="h-3 bg-[var(--bg-elevated-2)]/60 rounded w-full mb-1" />
              <div className="h-3 bg-[var(--bg-elevated-2)]/60 rounded w-2/3" />
            </div>
          ))}
        </div>
      ) : articles.length === 0 ? (
        <div className="text-center py-16 text-[var(--text-tertiary)]">
          {filterSymbol ? `No news found for ${filterSymbol}` : "No news available"}
        </div>
      ) : (
        <div className="space-y-3">
          {articles.map((a: any) => (
            <NewsCard
              key={a.id}
              article={a}
              level={level}
              rewriteCache={rewriteCache}
              onSymbolClick={(s) => { setInputVal(s); setFilterSymbol(s); }}
              onCacheUpdate={handleCacheUpdate}
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

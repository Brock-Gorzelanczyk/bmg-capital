import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getNews } from "@/api/market";
import { ExternalLink, RefreshCw, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { COMPANY_INFO } from "@/data/companyInfo";
import SectorPill from "@/components/ui/SectorPill";
import GlossaryTooltip from "@/components/explain/GlossaryTooltip";

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

function NewsCard({ article, onSymbolClick }: { article: any; onSymbolClick: (s: string) => void }) {
  const ago = timeAgo(article.published_at);
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
          {article.summary && (
            <p className="mt-1.5 text-[var(--text-tertiary)] text-xs leading-relaxed line-clamp-2">
              <GlossaryTooltip>{article.summary}</GlossaryTooltip>
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

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)]">Market News</h1>
          <p className="text-[var(--text-tertiary)] text-sm mt-0.5">Latest financial news and market updates</p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-1.5 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors duration-150 text-sm cursor-pointer"
        >
          <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
          Refresh
        </button>
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
          <div className="flex items-center gap-2">
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
              onSymbolClick={(s) => { setInputVal(s); setFilterSymbol(s); }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

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
      className="inline-flex items-center gap-1 text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full bg-[#1E293B] text-[#94A3B8] hover:bg-[#334155] hover:text-[#F8FAFC] transition-colors duration-150 cursor-pointer"
    >
      {symbol}
    </button>
  );
}

function NewsCard({ article, onSymbolClick }: { article: any; onSymbolClick: (s: string) => void }) {
  const ago = timeAgo(article.published_at);
  return (
    <div className="bg-[#0F172A] border border-[#1E293B] rounded-xl p-4 hover:border-[#334155] transition-colors duration-150 group">
      <div className="flex gap-4">
        <div className="flex-1 min-w-0">
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[#F8FAFC] font-medium text-sm leading-snug hover:text-[#94A3B8] transition-colors duration-150 line-clamp-2 group-hover:underline"
          >
            {article.headline}
          </a>
          {article.summary && (
            <p className="mt-1.5 text-[#475569] text-xs leading-relaxed line-clamp-2">
              <GlossaryTooltip>{article.summary}</GlossaryTooltip>
            </p>
          )}
          <div className="mt-2.5 flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2 text-[11px] text-[#475569]">
              <span className="font-medium text-[#475569]">{article.source}</span>
              <span className="text-[#334155]">·</span>
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
          <ExternalLink size={14} className="text-[#475569] group-hover:text-[#94A3B8] transition-colors duration-150" />
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
          <h1 className="text-xl font-bold text-[#F8FAFC]">Market News</h1>
          <p className="text-[#475569] text-sm mt-0.5">Latest financial news and market updates</p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-1.5 text-[#475569] hover:text-[#F8FAFC] transition-colors duration-150 text-sm cursor-pointer"
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
            className="w-full bg-[#0F172A] border border-[#334155] text-[#F8FAFC] text-base md:text-sm px-3 py-2 rounded-lg placeholder-[#475569] focus:outline-none focus:border-[#3B82F6] uppercase transition-colors duration-150"
          />
          {filterSymbol && (
            <button
              type="button"
              onClick={clearFilter}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[#475569] hover:text-[#F8FAFC] cursor-pointer transition-colors duration-150"
            >
              <X size={13} />
            </button>
          )}
        </div>
        <button
          type="submit"
          className="bg-[#3B82F6] text-white font-semibold text-sm px-4 py-2 rounded-lg hover:bg-[#2563EB] transition-colors duration-150 cursor-pointer"
        >
          Filter
        </button>
        {filterSymbol && (
          <div className="flex items-center gap-2">
            <span className="text-[#475569] text-sm">Showing news for</span>
            <span className="font-mono font-bold text-[#F8FAFC]">{filterSymbol}</span>
            {COMPANY_INFO[filterSymbol] && (
              <span className="text-[#475569] text-sm">{COMPANY_INFO[filterSymbol].name}</span>
            )}
            <SectorPill symbol={filterSymbol} />
            <button
              onClick={() => navigate(`/chart?symbol=${filterSymbol}`)}
              className="text-xs text-[#475569] hover:text-[#F8FAFC] underline cursor-pointer transition-colors duration-150"
            >
              View chart →
            </button>
          </div>
        )}
      </form>

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="bg-[#0F172A] border border-[#1E293B] rounded-xl p-4 animate-pulse">
              <div className="h-4 bg-[#1E293B] rounded w-3/4 mb-2" />
              <div className="h-3 bg-[#1E293B]/60 rounded w-full mb-1" />
              <div className="h-3 bg-[#1E293B]/60 rounded w-2/3" />
            </div>
          ))}
        </div>
      ) : articles.length === 0 ? (
        <div className="text-center py-16 text-[#475569]">
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

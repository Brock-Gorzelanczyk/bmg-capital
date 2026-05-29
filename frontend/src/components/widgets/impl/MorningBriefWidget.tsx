import { useState, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { getMarketOverview, getSectorPerformance, getNews } from "@/api/market";
import { generateMorningBrief } from "@/lib/demoBrief";
import { Skeleton } from "@/components/ui/Skeleton";

const INDEX_NAMES: Record<string, string> = {
  SPY: "S&P 500", QQQ: "NASDAQ 100", DIA: "Dow Jones", IWM: "Russell 2000",
  VXX: "Volatility", GLD: "Gold", TLT: "10Y Treasury",
};

export default function MorningBriefWidget() {
  const [displayText, setDisplayText] = useState("");
  const [briefText, setBriefText] = useState("");
  const [animKey, setAnimKey] = useState(0);

  const { data: rawIndices, isLoading: indicesLoading } = useQuery({ queryKey: ["market-overview"], queryFn: getMarketOverview, staleTime: 60_000 });
  const { data: rawSectors, isLoading: sectorsLoading } = useQuery({ queryKey: ["sectors"], queryFn: getSectorPerformance, staleTime: 60_000 });
  const { data: rawNews } = useQuery({ queryKey: ["news"], queryFn: () => getNews(), staleTime: 300_000 });

  const indices: any[] = Array.isArray(rawIndices) ? rawIndices : [];
  const sectors: any[] = Array.isArray(rawSectors) ? rawSectors : [];
  const news: any[] = Array.isArray(rawNews) ? rawNews : [];
  const isLoading = indicesLoading || sectorsLoading;

  const buildBrief = useCallback(() => {
    if (!indices.length) return "";
    return generateMorningBrief(
      {
        indices: indices.map((i: any) => ({ symbol: i.symbol, name: INDEX_NAMES[i.symbol] ?? i.symbol, change_pct: i.change_pct, price: i.price })),
        sectors: sectors.map((s: any) => ({ sector: s.sector, change_pct: s.change_pct })),
        topNews: news.map((a: any) => a.headline).filter(Boolean),
      },
      new Date()
    );
  }, [indices, sectors, news]);

  useEffect(() => {
    if (isLoading || !indices.length) return;
    const text = buildBrief();
    setBriefText(text);
    setDisplayText("");
    let i = 0, lastTime = 0, rafId: number;
    const tick = (ts: number) => {
      if (ts - lastTime >= 18) { i++; setDisplayText(text.slice(0, i)); lastTime = ts; }
      if (i < text.length) rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [animKey, isLoading, buildBrief, indices.length]);

  const now = new Date();
  const dateLabel = now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  const timeLabel = now.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

  return (
    <div className="h-full flex flex-col" style={{ borderLeft: "3px solid var(--accent-positive)", margin: "-1rem", padding: "1rem" }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-base shrink-0">🌅</span>
          <h2 className="text-sm font-semibold text-[var(--text-primary)] shrink-0">Morning Brief</h2>
          <span className="text-xs text-[var(--text-tertiary)] font-mono truncate hidden sm:block">{dateLabel} · {timeLabel}</span>
        </div>
        <button onClick={() => setAnimKey((k) => k + 1)} title="Regenerate" className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] p-1 rounded cursor-pointer transition-colors">
          <RefreshCw size={14} />
        </button>
      </div>

      {isLoading || !indices.length ? (
        <Skeleton rows={3} height={14} />
      ) : (
        <p className="text-[var(--text-secondary)] text-sm leading-relaxed flex-1">
          {displayText}
          {displayText.length < briefText.length && (
            <span className="inline-block w-0.5 h-4 bg-[var(--accent-positive)] ml-0.5 animate-pulse align-middle" />
          )}
        </p>
      )}

      <div className="mt-3 pt-2 border-t border-[var(--border-subtle)]">
        <span className="text-[10px] text-[var(--text-tertiary)] font-medium tracking-wide">Powered by BMG Intelligence</span>
      </div>
    </div>
  );
}

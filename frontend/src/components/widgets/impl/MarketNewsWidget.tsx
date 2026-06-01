import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { getNews } from "@/api/market";
import { Card, CardLabel } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { timeAgo } from "@/lib/utils";

export default function MarketNewsWidget() {
  const { data: rawNews, isLoading } = useQuery({ queryKey: ["news"], queryFn: () => getNews(), staleTime: 300_000 });
  const news: any[] = Array.isArray(rawNews) ? rawNews : [];

  return (
    <Card glow className="h-full overflow-auto">
      <CardLabel>Market News</CardLabel>
      {isLoading ? (
        <div className="space-y-4">
          {[1,2,3,4,5].map((i) => (
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
            <a
              key={article.id}
              href={article.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-start gap-3 py-3 border-b border-[var(--border-subtle)] last:border-0 hover:bg-[var(--bg-elevated-2)]/30 -mx-4 px-4 transition-colors rounded cursor-pointer"
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm text-[var(--text-secondary)] font-medium line-clamp-2 group-hover:text-[var(--text-primary)] transition-colors">{article.headline}</p>
                <div className="flex items-center gap-2 mt-1.5">
                  <span className="text-[11px] text-[var(--text-tertiary)] font-medium">{article.source}</span>
                  <span className="text-[var(--border-emphasis)]">·</span>
                  <span className="text-[11px] text-[var(--text-tertiary)]">{timeAgo(article.published_at)}</span>
                </div>
              </div>
              <ExternalLink size={13} className="text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)] mt-0.5 shrink-0" />
            </a>
          ))}
        </div>
      )}
    </Card>
  );
}

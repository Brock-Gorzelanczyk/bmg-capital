import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getSectorPerformance } from "@/api/market";
import { formatPercent, cn } from "@/lib/utils";
import { Card, CardLabel } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";

export default function SectorPerformanceWidget() {
  const navigate = useNavigate();
  const { data: rawSectors, isLoading } = useQuery({ queryKey: ["sectors"], queryFn: getSectorPerformance, refetchInterval: 60_000 });
  const sectors: any[] = Array.isArray(rawSectors) ? rawSectors : [];
  const maxMove = Math.max(...sectors.map((s: any) => Math.abs(s.change_pct)), 0.1);

  return (
    <Card glow className="h-full overflow-auto">
      <CardLabel className="flex items-center gap-1.5">Sector Performance</CardLabel>
      {isLoading ? (
        <div className="space-y-3">
          {[1,2,3,4,5,6].map((i) => (
            <div key={i} className="flex items-center gap-3 py-1">
              <Skeleton height={12} className="w-28 shrink-0" />
              <Skeleton height={6} className="flex-1" />
              <Skeleton height={12} className="w-12 shrink-0" />
            </div>
          ))}
        </div>
      ) : (
        <div>
          {[...sectors].sort((a: any, b: any) => b.change_pct - a.change_pct).map((s: any) => {
            const isPos = s.change_pct >= 0;
            const barPct = Math.abs(s.change_pct) / maxMove * 100;
            const label = s.sector.replace("Select Sector SPDR Fund", "").replace("SPDR", "").trim();
            return (
              <div
                key={s.sector}
                onClick={() => s.symbol && navigate(`/chart?symbol=${s.symbol}`)}
                className={cn(
                  "flex items-center gap-3 py-2.5 border-b border-[var(--border-subtle)] last:border-0 transition-colors",
                  s.symbol && "cursor-pointer hover:bg-[var(--bg-elevated-2)]/40 -mx-2 px-2 rounded"
                )}
              >
                <span className="text-xs text-[var(--text-secondary)] w-32 shrink-0 truncate">{label}</span>
                <div className="flex-1 h-1 bg-[var(--bg-elevated-2)] rounded-full overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${Math.min(barPct, 100)}%`, background: isPos ? "var(--accent-positive)" : "var(--accent-negative)", opacity: 0.7 }} />
                </div>
                <span className={cn("text-xs font-mono font-medium w-14 text-right shrink-0", isPos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
                  {isPos ? "+" : ""}{formatPercent(s.change_pct)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

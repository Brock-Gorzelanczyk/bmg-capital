import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ArrowRight, FlaskConical } from "lucide-react";
import { getTrades } from "@/api/strategy";
import { Card, CardLabel } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import SectorPill from "@/components/ui/SectorPill";

export default function StrategySignalsWidget() {
  const navigate = useNavigate();
  const { data: tradesData, isLoading } = useQuery({ queryKey: ["strategy-trades"], queryFn: getTrades, staleTime: 55_000 });
  const trades: any[] = Array.isArray(tradesData?.trades) ? tradesData.trades : [];

  if (isLoading) return (
    <Card className="h-full">
      <Skeleton height={14} className="w-32 mb-4" />
      <div className="space-y-2">{[1,2,3].map((i) => <Skeleton key={i} height={36} />)}</div>
    </Card>
  );

  const open = trades.filter((t) => t.status === "open").slice(0, 4);
  const watching = trades.filter((t) => t.status === "candidate").slice(0, 4);

  return (
    <Card glow className="h-full overflow-auto">
      <div className="flex items-center justify-between mb-4">
        <CardLabel className="mb-0 flex items-center gap-1.5"><FlaskConical size={12} /> Strategy Signals</CardLabel>
        <button onClick={() => navigate("/strategy")} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-xs flex items-center gap-1 transition-colors cursor-pointer">
          View all <ArrowRight size={11} />
        </button>
      </div>
      {open.length + watching.length === 0 ? (
        <div className="py-6 text-center text-[var(--text-tertiary)] text-sm">No active signals</div>
      ) : (
        <div className="space-y-1">
          {open.length > 0 && <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mb-1.5">Open</div>}
          {open.map((t: any) => (
            <div key={t.id} className="flex items-center justify-between cursor-pointer hover:bg-[var(--bg-elevated-2)]/50 -mx-2 px-2 py-1.5 rounded transition-colors" onClick={() => navigate(`/chart?symbol=${t.symbol}`)}>
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-[var(--text-primary)] text-sm">{t.symbol}</span>
                <SectorPill symbol={t.symbol} />
              </div>
              <span className="text-xs font-semibold text-[var(--accent-positive)] bg-[var(--accent-positive-bg)] border border-[var(--accent-positive)]/20 px-1.5 py-px rounded">Open</span>
            </div>
          ))}
          {watching.length > 0 && <div className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider mt-2 mb-1.5">Watching</div>}
          {watching.map((t: any) => (
            <div key={t.id} className="flex items-center justify-between cursor-pointer hover:bg-[var(--bg-elevated-2)]/50 -mx-2 px-2 py-1.5 rounded transition-colors" onClick={() => navigate(`/chart?symbol=${t.symbol}`)}>
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-[var(--text-primary)] text-sm">{t.symbol}</span>
                <SectorPill symbol={t.symbol} />
              </div>
              <span className="text-xs text-[#F59E0B] bg-[#F59E0B]/10 border border-[#F59E0B]/20 px-1.5 py-px rounded">Watch</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

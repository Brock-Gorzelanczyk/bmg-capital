import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { getAccount } from "@/api/paper";
import { formatCurrency, cn } from "@/lib/utils";
import { SkeletonCard } from "@/components/ui/Skeleton";
import { Card, CardLabel } from "@/components/ui/Card";

export default function PaperAccountWidget() {
  const navigate = useNavigate();
  const { data: account, isLoading, isError } = useQuery({
    queryKey: ["paper-account"],
    queryFn: getAccount,
    staleTime: 30_000,
    retry: false,
  });

  if (isLoading) return <SkeletonCard className="h-full" />;
  if (isError || !account) return (
    <div className="h-full flex items-center justify-center text-[var(--text-tertiary)] text-sm">No data</div>
  );

  const isPos = account.day_pnl >= 0;
  return (
    <Card glow onClick={() => navigate("/paper")} className="cursor-pointer hover:border-[var(--border-emphasis)] h-full">
      <div className="flex items-start justify-between gap-2 mb-4">
        <div>
          <CardLabel className="mb-1">Paper Portfolio</CardLabel>
          <div className="text-2xl font-semibold text-[var(--text-primary)] font-mono leading-none">
            {formatCurrency(account.equity)}
          </div>
        </div>
        <span className="text-[var(--text-tertiary)] text-xs flex items-center gap-1 shrink-0 mt-1">
          View <ArrowRight size={11} />
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="bg-[var(--bg-base)] rounded-lg px-3 py-2">
          <div className="text-[10px] text-[var(--text-tertiary)] mb-0.5">Day P&amp;L</div>
          <span className={cn("text-sm font-semibold font-mono", isPos ? "text-[var(--accent-positive)]" : "text-[var(--accent-negative)]")}>
            {isPos ? "▲" : "▼"} {formatCurrency(Math.abs(account.day_pnl))}
          </span>
        </div>
        <div className="bg-[var(--bg-base)] rounded-lg px-3 py-2">
          <div className="text-[10px] text-[var(--text-tertiary)] mb-0.5">Positions</div>
          <div className="text-sm font-semibold text-[var(--text-primary)]">
            {(account.positions?.length ?? 0) > 0 ? account.positions.length : "—"}
          </div>
        </div>
      </div>
    </Card>
  );
}

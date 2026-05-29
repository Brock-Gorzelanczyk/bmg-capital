import { useQuery } from "@tanstack/react-query";
import { Calendar } from "lucide-react";
import { getLatestRecap } from "@/api/recap";
import { Card, CardLabel } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import DailyRecapCard from "@/components/recap/DailyRecapCard";

export default function DailyRecapWidget() {
  const { data: recap, isLoading } = useQuery({ queryKey: ["recap-latest"], queryFn: getLatestRecap, staleTime: 300_000 });

  if (isLoading) return (
    <Card className="h-full">
      <Skeleton height={12} className="w-28 mb-3" />
      <Skeleton height={36} className="mb-2" />
      <Skeleton height={14} className="w-4/5" />
    </Card>
  );

  return (
    <Card glow className="h-full overflow-auto">
      <div className="flex items-center justify-between mb-3">
        <CardLabel className="mb-0 flex items-center gap-1.5"><Calendar size={12} /> Daily Recap</CardLabel>
      </div>
      {recap ? (
        <DailyRecapCard recap={recap} defaultExpanded={false} />
      ) : (
        <div className="flex flex-col items-center justify-center py-5 text-center gap-2">
          <Calendar size={24} className="text-[var(--border-emphasis)]" />
          <p className="text-sm text-[var(--text-tertiary)]">Daily recap generates at 4:15 PM ET</p>
          <p className="text-xs text-[var(--text-tertiary)] opacity-60">Check back after market close</p>
        </div>
      )}
    </Card>
  );
}

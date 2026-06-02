import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import client from "@/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

interface WashSaleCheckResponse {
  blocked: boolean;
  sold_date?: string;
  safe_after?: string;
}

interface WashSaleWarningBadgeProps {
  symbol: string;
  className?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function WashSaleWarningBadge({ symbol, className }: WashSaleWarningBadgeProps) {
  const { data } = useQuery<WashSaleCheckResponse>({
    queryKey: ["wash-sale", symbol],
    queryFn: () =>
      client
        .get<WashSaleCheckResponse>(`/api/robo/wash-sale/check/${symbol}`)
        .then((r) => r.data),
    staleTime: 60 * 1000,
    enabled: !!symbol,
  });

  if (!data?.blocked) return null;

  return (
    <div
      className={cn(
        "flex items-start gap-2 px-3 py-2 rounded-lg",
        "bg-amber-500/10 border border-amber-500/25",
        className
      )}
    >
      <AlertTriangle size={14} className="text-amber-400 mt-0.5 shrink-0" />
      <p className="text-xs text-amber-300 leading-snug">
        <span className="font-semibold">Wash-sale risk:</span>{" "}
        <span className="font-medium text-amber-400">{symbol}</span> was sold at a loss
        {data.sold_date ? ` on ${formatDate(data.sold_date)}` : ""}.{" "}
        {data.safe_after && (
          <>
            Safe to re-buy after{" "}
            <span className="font-medium text-amber-400">{formatDate(data.safe_after)}</span>.
          </>
        )}
      </p>
    </div>
  );
}

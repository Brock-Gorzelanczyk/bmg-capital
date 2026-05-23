import { useQuery } from "@tanstack/react-query";
import { fetchBars } from "@/api/bars";

function buildPath(prices: number[], w: number, h: number): string {
  if (prices.length < 2) return "";
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;
  return prices
    .map((p, i) => {
      const x = ((i / (prices.length - 1)) * w).toFixed(1);
      const y = (h - ((p - min) / range) * (h - 2) - 1).toFixed(1);
      return `${i === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");
}

interface Props {
  symbol: string;
  width?: number;
  height?: number;
}

const SEVEN_DAYS_AGO = new Date(Date.now() - 10 * 86400_000).toISOString().slice(0, 10);

export default function Sparkline({ symbol, width = 64, height = 28 }: Props) {
  const { data } = useQuery({
    queryKey: ["sparkline", symbol],
    queryFn: () => fetchBars(symbol, "1Day", undefined, SEVEN_DAYS_AGO),
    staleTime: 24 * 3600_000,
    gcTime: 48 * 3600_000,
  });

  const prices = data?.bars.map((b) => b.c) ?? [];
  if (prices.length < 2) return <div style={{ width, height }} className="shrink-0" />;

  const isUp = prices[prices.length - 1] >= prices[0];
  const color = isUp ? "#26a69a" : "#ef5350";

  return (
    <svg width={width} height={height} className="shrink-0 overflow-visible">
      <path d={buildPath(prices, width, height)} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

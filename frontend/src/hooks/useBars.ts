import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { fetchBars } from "@/api/bars";

export function useBars(symbol: string, timeframe: string, indicators?: string, start?: string) {
  return useQuery({
    queryKey: ["bars", symbol, timeframe, indicators, start],
    queryFn: () => fetchBars(symbol, timeframe, indicators, start),
    enabled: Boolean(symbol),
    staleTime: timeframe === "1Day" ? 60_000 : 30_000,
    retry: 1,
    // Keep previous data visible while new timeframe/period fetches, preventing blank flashes
    placeholderData: keepPreviousData,
  });
}

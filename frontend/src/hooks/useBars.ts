import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useRef } from "react";
import { fetchBars } from "@/api/bars";

export function useBars(symbol: string, timeframe: string, indicators?: string, start?: string) {
  // Track the last symbol we fetched so we can suppress keepPreviousData across symbol changes.
  // Keeping previous bars when only timeframe/period/indicators change is fine (prevents flash),
  // but keeping BTC bars while NVDA loads causes a wrong price-axis range.
  const prevSymbolRef = useRef(symbol);
  const symbolChanged = prevSymbolRef.current !== symbol;
  if (symbolChanged) prevSymbolRef.current = symbol;

  return useQuery({
    queryKey: ["bars", symbol, timeframe, indicators, start],
    queryFn: () => fetchBars(symbol, timeframe, indicators, start),
    enabled: Boolean(symbol),
    // Full-history fetches are expensive — keep in cache for 5 min before staling,
    // and hold in memory for 30 min so switching periods (same timeframe) is instant.
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
    retry: 1,
    // Only keep previous data when the symbol hasn't changed (e.g. period/timeframe switch).
    // When the symbol itself changes we clear immediately so the old price axis doesn't bleed through.
    placeholderData: symbolChanged ? undefined : keepPreviousData,
  });
}

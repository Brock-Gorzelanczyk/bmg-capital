import client from "./client";
import type { Bar } from "@/types/market";

export const getLatestPrices = (symbols: string[]): Promise<Record<string, number | null>> =>
  client.get<{ prices: Record<string, number | null> }>(`/bars/latest`, { params: { symbols: symbols.join(",") } })
    .then(r => r.data.prices)
    .catch(() => ({}));

export interface BarsResponse {
  symbol: string;
  bars: Bar[];
  indicators: Record<string, (number | null)[]>;
}

export async function fetchBars(
  symbol: string,
  timeframe = "1Day",
  indicators?: string,
  start?: string,
  limit?: number,
): Promise<BarsResponse> {
  const params: Record<string, string> = { timeframe, adjustment: "split" };
  if (indicators) params.indicators = indicators;
  if (start) params.start = start;
  if (limit) params.limit = String(limit);
  const { data } = await client.get<BarsResponse>(`/bars/${symbol}`, { params });
  return data;
}

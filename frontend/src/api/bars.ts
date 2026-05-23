import client from "./client";
import type { Bar } from "@/types/market";

export interface BarsResponse {
  symbol: string;
  bars: Bar[];
  indicators: Record<string, (number | null)[]>;
}

export async function fetchBars(
  symbol: string,
  timeframe = "1Day",
  indicators?: string,
  start?: string
): Promise<BarsResponse> {
  const params: Record<string, string> = { timeframe };
  if (indicators) params.indicators = indicators;
  if (start) params.start = start;
  const { data } = await client.get<BarsResponse>(`/bars/${symbol}`, { params });
  return data;
}

import client from "./client";
import type { IndexSnapshot, SectorPerf, NewsArticle, EarningsEvent } from "@/types/market";

export async function getMarketOverview(): Promise<IndexSnapshot[]> {
  const { data } = await client.get<any>("/market/overview");
  const arr = data?.indices ?? data?.data ?? data;
  return Array.isArray(arr) ? arr : [];
}

export async function getSectorPerformance(): Promise<SectorPerf[]> {
  const { data } = await client.get<any>("/market/sectors");
  const arr = data?.sectors ?? data?.data ?? data;
  return Array.isArray(arr) ? arr : [];
}

export async function getNews(symbols?: string[]): Promise<NewsArticle[]> {
  const params: Record<string, string> = {};
  if (symbols?.length) params.symbols = symbols.join(",");
  const { data } = await client.get<any>("/news", { params });
  const arr = data?.articles ?? data?.data ?? data;
  return Array.isArray(arr) ? arr : [];
}

export async function getEarnings(daysAhead = 14): Promise<EarningsEvent[]> {
  const { data } = await client.get<any>("/earnings", { params: { days_ahead: daysAhead } });
  const arr = data?.earnings ?? data?.data ?? data;
  return Array.isArray(arr) ? arr : [];
}

export async function getImpliedMove(symbol: string): Promise<{ symbol: string; implied_move_pct: number | null }> {
  const { data } = await client.get<{ symbol: string; implied_move_pct: number | null }>(`/earnings/implied-move/${symbol}`);
  return data;
}

export interface EarningsHistoryEntry {
  period: string;
  eps_actual: number | null;
  eps_estimate: number | null;
  surprise_pct: number | null;
}

export async function getEarningsHistory(symbol: string): Promise<EarningsHistoryEntry[]> {
  const { data } = await client.get<any>(`/earnings/history/${symbol}`);
  const arr = data?.history ?? data?.data ?? data;
  return Array.isArray(arr) ? arr : [];
}

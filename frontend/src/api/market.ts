import client from "./client";
import type { IndexSnapshot, SectorPerf, NewsArticle, EarningsEvent } from "@/types/market";

export async function getMarketOverview(): Promise<IndexSnapshot[]> {
  const { data } = await client.get<{ indices: IndexSnapshot[] }>("/market/overview");
  return data.indices;
}

export async function getSectorPerformance(): Promise<SectorPerf[]> {
  const { data } = await client.get<{ sectors: SectorPerf[] }>("/market/sectors");
  return data.sectors;
}

export async function getNews(symbols?: string[]): Promise<NewsArticle[]> {
  const params: Record<string, string> = {};
  if (symbols?.length) params.symbols = symbols.join(",");
  const { data } = await client.get<{ articles: NewsArticle[] }>("/news", { params });
  return data.articles;
}

export async function getEarnings(daysAhead = 14): Promise<EarningsEvent[]> {
  const { data } = await client.get<{ earnings: EarningsEvent[] }>("/earnings", { params: { days_ahead: daysAhead } });
  return data.earnings;
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
  const { data } = await client.get<{ symbol: string; history: EarningsHistoryEntry[] }>(`/earnings/history/${symbol}`);
  return data.history;
}

import client from "./client";
import type { Watchlist, WatchlistItem } from "@/types/watchlist";
import type { Snapshot } from "@/types/market";

export async function getWatchlists(): Promise<Watchlist[]> {
  const { data } = await client.get<{ watchlists: Watchlist[] }>("/watchlists");
  return data.watchlists;
}

export async function createWatchlist(name: string): Promise<Watchlist> {
  const { data } = await client.post<Watchlist>("/watchlists", { name });
  return data;
}

export async function deleteWatchlist(id: number): Promise<void> {
  await client.delete(`/watchlists/${id}`);
}

export async function addSymbol(watchlistId: number, symbol: string): Promise<WatchlistItem> {
  const { data } = await client.post<WatchlistItem>(`/watchlists/${watchlistId}/symbols`, { symbol });
  return data;
}

export async function removeSymbol(watchlistId: number, symbol: string): Promise<void> {
  await client.delete(`/watchlists/${watchlistId}/symbols/${symbol}`);
}

export async function getSnapshot(watchlistId: number): Promise<Snapshot[]> {
  const { data } = await client.get<{ snapshots: Snapshot[] }>(`/watchlists/${watchlistId}/snapshot`);
  return data.snapshots;
}

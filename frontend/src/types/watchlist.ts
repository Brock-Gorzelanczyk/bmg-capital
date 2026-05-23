export interface WatchlistItem {
  id: number;
  symbol: string;
  added_at: string;
}

export interface Watchlist {
  id: number;
  name: string;
  created_at: string;
  items: WatchlistItem[];
}

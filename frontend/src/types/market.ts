export interface Bar {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface Quote {
  symbol: string;
  bid: number;
  ask: number;
  price: number;
  timestamp: string;
}

export interface LiveBar {
  symbol: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  timestamp: string;
}

export interface Snapshot {
  symbol: string;
  price: number;
  change: number;
  change_pct: number;
  volume: number;
  prev_close: number;
}

export interface IndexSnapshot {
  symbol: string;
  price: number;
  change: number;
  change_pct: number;
  volume: number;
}

export interface SectorPerf {
  sector: string;
  symbol: string;
  price: number;
  change_pct: number;
}

export interface NewsArticle {
  id: string;
  headline: string;
  summary: string;
  author: string;
  source: string;
  url: string;
  symbols: string[];
  published_at: string;
}

export interface EarningsEvent {
  symbol: string;
  date: string;
  eps_estimate: number | null;
  eps_actual: number | null;
  revenue_estimate: number | null;
  revenue_actual: number | null;
  time: string;
}

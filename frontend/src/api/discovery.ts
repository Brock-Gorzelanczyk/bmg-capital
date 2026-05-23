import client from "./client";

export interface ThemeConstituent {
  symbol: string;
  change_pct: number;
  price: number;
}

export interface Theme {
  id: string;
  name: string;
  description: string;
  emoji: string;
  color: string;
  tickers: string[];
  avg_change_pct: number;
  constituents: ThemeConstituent[];
}

export interface IPO {
  company: string;
  symbol: string;
  date: string;
  price_range: string;
  exchange: string;
  status: string;
}

export interface InsiderTrade {
  symbol: string;
  name: string;
  title: string;
  transaction: "buy" | "sell";
  shares: number;
  value: number;
  date: string;
}

export const getThemes = (): Promise<{ themes: Theme[] }> =>
  client.get("/api/discovery/themes").then((r) => r.data);

export const getIPOs = (daysAhead = 90): Promise<{ ipos: IPO[] }> =>
  client.get("/api/discovery/ipos", { params: { days_ahead: daysAhead } }).then((r) => r.data);

export const getInsiders = (limit = 50): Promise<{ insiders: InsiderTrade[] }> =>
  client.get("/api/discovery/insiders", { params: { limit } }).then((r) => r.data);

export const getSectorPerformance = (): Promise<{ sectors: { sector: string; symbol: string; price: number; change_pct: number }[] }> =>
  client.get("/api/market/sectors").then((r) => r.data);

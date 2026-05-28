import api from "./client";

export interface CoinData {
  symbol: string;
  name: string;
  slug: string;
  last: number | null;
  prev_close: number | null;
  change_pct: number | null;
  volume: number;
  market_cap: number;
}

export interface CryptoMarket {
  coins: CoinData[];
  cached: boolean;
}

export async function getCryptoMarket(): Promise<CryptoMarket> {
  const res = await api.get("/crypto/market");
  return res.data;
}

export async function getCryptoQuote(symbol: string): Promise<CoinData> {
  const res = await api.get(`/crypto/quote/${symbol}`);
  return res.data;
}

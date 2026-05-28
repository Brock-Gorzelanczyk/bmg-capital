import api from "./client";

export interface CoinGeckoData {
  id: string;
  symbol: string;           // uppercase, e.g. "BTC"
  name: string;
  image: string | null;
  current_price: number | null;
  market_cap: number;
  market_cap_rank: number | null;
  total_volume: number;
  pct_1h: number | null;
  pct_24h: number | null;
  pct_7d: number | null;
  sparkline: number[];      // ~168 hourly prices for 7d
  sparkline_url?: string;   // image URL (trending only)
}

export interface CryptoOverview {
  total_market_cap_usd: number;
  market_cap_change_24h_pct: number;
  btc_dominance: number;
  active_coins: number;
  fear_greed: {
    value: number;
    label: string;
    timestamp: string | null;
  };
}

export async function getCryptoMarket(): Promise<{ coins: CoinGeckoData[] }> {
  const res = await api.get("/crypto/market");
  return res.data;
}

export async function getCryptoOverview(): Promise<CryptoOverview> {
  const res = await api.get("/crypto/overview");
  return res.data;
}

export async function getCryptoTrending(): Promise<{ coins: CoinGeckoData[] }> {
  const res = await api.get("/crypto/trending");
  return res.data;
}

export async function refreshCryptoMarket(): Promise<{ ok: boolean }> {
  const res = await api.post("/crypto/refresh");
  return res.data;
}

export async function getCryptoQuote(symbol: string): Promise<{ symbol: string; last: number | null; change_pct: number | null }> {
  const res = await api.get(`/crypto/quote/${symbol}`);
  return res.data;
}

// ── Crypto Strategy endpoints ─────────────────────────────────────────────────

export interface CryptoTrade {
  id: number;
  preset_key: string;
  preset_label: string;
  symbol: string;
  status: "open" | "closed" | "candidate";
  asset_class: string;
  exchange: string | null;
  candidate_since: string | null;
  entry_trigger: string | null;
  entry_date: string | null;
  entry_price: number | null;
  shares: number | null;
  stop_price: number | null;
  target_price: number | null;
  atr: number | null;
  current_price: number | null;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  pnl: number | null;
  pnl_pct: number | null;
  days_held: number;
  last_known_price: number | null;
}

export interface CryptoStrategySummary {
  overall: {
    total_closed: number;
    wins: number;
    losses: number;
    win_rate: number;
    total_pnl: number;
    open_pnl: number;
    portfolio_value: number;
    open_positions: number;
    candidates: number;
    expectancy: number;
  };
  by_preset: Array<{
    preset_key: string;
    preset_label: string;
    trades: number;
    wins: number;
    losses: number;
    win_rate: number;
    total_pnl: number;
  }>;
}

export const getCryptoStrategyTrades = () =>
  api.get("/crypto-strategy/trades").then((r) => r.data as { trades: CryptoTrade[] });

export const getCryptoStrategyCandidates = () =>
  api.get("/crypto-strategy/candidates").then((r) => r.data as { candidates: CryptoTrade[] });

export const getCryptoStrategySummary = () =>
  api.get("/crypto-strategy/summary").then((r) => r.data as CryptoStrategySummary);

export const getCryptoStrategyLog = (limit = 50) =>
  api.get(`/crypto-strategy/log?limit=${limit}`).then((r) => r.data);

export const getCryptoStrategyEquity = () =>
  api.get("/crypto-strategy/equity").then((r) => r.data);

export const runCryptoStrategyNow = () =>
  api.post("/crypto-strategy/run-now").then((r) => r.data);

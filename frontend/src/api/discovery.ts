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
  client.get("/discovery/themes").then((r) => r.data);

export const getIPOs = (daysAhead = 90): Promise<{ ipos: IPO[] }> =>
  client.get("/discovery/ipos", { params: { days_ahead: daysAhead } }).then((r) => r.data);

export const getInsiders = (limit = 50): Promise<{ insiders: InsiderTrade[] }> =>
  client.get("/discovery/insiders", { params: { limit } }).then((r) => r.data);

export const getSectorPerformance = (): Promise<{ sectors: { sector: string; symbol: string; price: number; change_pct: number }[] }> =>
  client.get("/market/sectors").then((r) => r.data);

// ── Crypto Discovery ─────────────────────────────────────────────────────────

export interface CryptoLaunch {
  address: string;
  name: string;
  symbol: string;
  chain: string;
  dex: string;
  price_usd: number;
  price_change_24h: number;
  volume_24h: number;
  liquidity_usd: number;
  pair_address: string;
  age_hours: number;
  url: string;
  risk_score?: number;
}

export interface NarrativeCoin {
  id: string;
  symbol: string;
  name: string;
  price: number | null;
  pct_24h: number;
  market_cap: number | null;
  image: string | null;
}

export interface Narrative {
  id: string;
  name: string;
  emoji: string;
  avg_pct_24h: number;
  coins: string[];
  coins_data: NarrativeCoin[];
}

export interface IdoEvent {
  project: string;
  token: string;
  type: string;
  platform: string;
  date: string;
  status: "upcoming" | "priced" | "active";
  est_raise_usd?: number;
  price_usd?: number;
  vesting?: string;
  website: string;
  description: string;
  tags: string[];
}

export const getCryptoLaunches = (min_liquidity?: number, limit?: number): Promise<{ launches: CryptoLaunch[] }> =>
  client.get("/discovery/crypto/launches", { params: { min_liquidity, limit } }).then((r) => r.data);

export const getCryptoTrending = (chain?: string, limit?: number): Promise<{ pairs: CryptoLaunch[] }> =>
  client.get("/discovery/crypto/trending", { params: { chain, limit } }).then((r) => r.data);

export const getMemecoins = (limit?: number): Promise<{ tokens: CryptoLaunch[] }> =>
  client.get("/discovery/crypto/memecoins", { params: { limit } }).then((r) => r.data);

export const getNarratives = (): Promise<{ narratives: Narrative[] }> =>
  client.get("/discovery/crypto/narratives").then((r) => r.data);

export const getIdoCalendar = (): Promise<{ events: IdoEvent[] }> =>
  client.get("/discovery/crypto/ido-calendar").then((r) => r.data);

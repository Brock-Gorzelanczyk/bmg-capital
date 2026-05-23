import client from "./client";

export type TierName = "free" | "pro" | "premium";

export interface TierFeatures {
  paper_trading: boolean;
  basic_screener: boolean;
  learn: boolean;
  watchlist_limit: number;
  alerts_limit: number;
  strategy_backtest: boolean;
  options_lab: boolean;
  social: boolean;
  ai_explain: boolean;
  advanced_charts: boolean;
}

export interface MyTier {
  tier: TierName;
  features: TierFeatures;
  expires_at: string | null;
}

export interface Plan {
  id: TierName;
  name: string;
  pricing: { monthly: number; annual: number };
  features: TierFeatures;
}

export const getMyTier = (): Promise<MyTier> =>
  client.get("/api/tiers/me").then((r) => r.data);

export const getPlans = (): Promise<{ plans: Plan[] }> =>
  client.get("/api/tiers/plans").then((r) => r.data);

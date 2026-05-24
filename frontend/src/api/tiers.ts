import client from "./client";

export type TierName = "free" | "plus" | "premium";
export type TierStatus = "active" | "trialing" | "past_due" | "cancelled";

export interface Entitlements {
  pro_mode: boolean;
  chart_history_years: number;
  chart_indicators_max: number;
  chart_tabs_max: number;
  watchlist_count: number;
  watchlist_symbols: number;
  alert_count_max: number;
  real_time_options: boolean;
  extended_hours: boolean;
  recurring_buys: boolean;
  tax_loss_harvest: boolean;
  margin_enabled: boolean;
  strategy_lab_tier: "none" | "basic" | "advanced";
  strategy_backtest_years: number;
  options_lab_tier: "none" | "basic" | "full";
  learning_center_tier: "beginner" | "intermediate" | "all";
  ai_tutor_unlimited: boolean;
  ai_copilot_reasoning: boolean;
  level_2_quotes: boolean;
  opra_realtime: boolean;
  options_flow: boolean;
  reading_level_slider: boolean;
  certified_exams: boolean;
  apy_rate: number;
  ira_match_rate: number;
  ira_match_cap: number;
  instant_deposit_cap: number;
  api_access: boolean;
  support_tier: "community" | "email" | "live_chat";
  community_post: boolean;
  crypto_limit: number;
  _tier: TierName;
  _status: TierStatus;
}

export interface MyTierResponse {
  tier: TierName;
  status: TierStatus;
  entitlements: Entitlements;
  billing_interval: "monthly" | "annual" | null;
  trial_ends_at: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  aum_override: string | null;
  has_stripe: boolean;
}

export interface Plan {
  id: TierName;
  name: string;
  pricing: { monthly: number; annual: number; annual_monthly_equiv: number };
  entitlements: Entitlements;
}

export const getMyTier = (): Promise<MyTierResponse> =>
  client.get("/api/tiers/me").then((r) => r.data);

export const getPlans = (): Promise<{ plans: Plan[] }> =>
  client.get("/api/tiers/plans").then((r) => r.data);

export const startTrial = (): Promise<{ ok: boolean; trial_ends_at: string }> =>
  client.post("/api/tiers/start-trial").then((r) => r.data);

export const createCheckout = (plan: TierName, interval: "monthly" | "annual"): Promise<{ url: string }> =>
  client.post("/api/tiers/checkout", { plan, interval }).then((r) => r.data);

export const createPortal = (): Promise<{ url: string }> =>
  client.post("/api/tiers/portal").then((r) => r.data);

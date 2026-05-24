import { create } from "zustand";
import type { Entitlements, MyTierResponse, TierName } from "@/api/tiers";

const FREE_ENTITLEMENTS: Entitlements = {
  pro_mode: false,
  chart_history_years: 1,
  chart_indicators_max: 5,
  chart_tabs_max: 1,
  watchlist_count: 1,
  watchlist_symbols: 50,
  alert_count_max: 10,
  real_time_options: false,
  extended_hours: false,
  recurring_buys: false,
  tax_loss_harvest: false,
  margin_enabled: false,
  strategy_lab_tier: "none",
  strategy_backtest_years: 0,
  options_lab_tier: "none",
  learning_center_tier: "beginner",
  ai_tutor_unlimited: false,
  ai_copilot_reasoning: false,
  level_2_quotes: false,
  opra_realtime: false,
  options_flow: false,
  reading_level_slider: false,
  certified_exams: false,
  apy_rate: 1.5,
  ira_match_rate: 0,
  ira_match_cap: 0,
  instant_deposit_cap: 1000,
  api_access: false,
  support_tier: "community",
  community_post: false,
  crypto_limit: 50,
  _tier: "free",
  _status: "active",
};

interface TierState {
  tier: TierName;
  entitlements: Entitlements;
  trialEndsAt: string | null;
  currentPeriodEnd: string | null;
  billingInterval: "monthly" | "annual" | null;
  cancelAtPeriodEnd: boolean;
  hasStripe: boolean;
  loaded: boolean;
  setTierData: (data: MyTierResponse) => void;
  can: (feature: keyof Entitlements) => boolean;
  canNum: (feature: keyof Entitlements, required: number) => boolean;
}

export const useTierStore = create<TierState>((set, get) => ({
  tier: "free",
  entitlements: FREE_ENTITLEMENTS,
  trialEndsAt: null,
  currentPeriodEnd: null,
  billingInterval: null,
  cancelAtPeriodEnd: false,
  hasStripe: false,
  loaded: false,

  setTierData: (data) =>
    set({
      tier: data.tier,
      entitlements: data.entitlements ?? FREE_ENTITLEMENTS,
      trialEndsAt: data.trial_ends_at,
      currentPeriodEnd: data.current_period_end,
      billingInterval: data.billing_interval,
      cancelAtPeriodEnd: data.cancel_at_period_end,
      hasStripe: data.has_stripe,
      loaded: true,
    }),

  can: (feature) => {
    const val = get().entitlements[feature];
    if (typeof val === "boolean") return val;
    if (typeof val === "number") return val !== 0;
    return Boolean(val);
  },

  canNum: (feature, required) => {
    const val = get().entitlements[feature];
    if (typeof val === "number") return val === -1 || val >= required;
    return false;
  },
}));

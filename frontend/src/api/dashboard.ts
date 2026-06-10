import client from "./client";
import type { AnalystHighlight } from "./analyst";

export interface DashV2Sleeve {
  value_cents: number;
  open_positions: number;
  watching: number;
  pnl_cents: number;
  bots_active: number;
  bots_total: number;
}

export interface DashV2LeaderboardEntry {
  rank: number;
  profile: string;
  name: string;
  return_30d_pct: number;
  today_pnl_cents: number;
  watchlist_count: number;
  portfolio_value_cents: number;
}

export interface DashboardV2 {
  portfolio: {
    total_value_cents: number;
    today_pnl_cents: number;
    today_pnl_pct: number;
    return_30d_pct: number;
    leaderboard: DashV2LeaderboardEntry[];
  };
  regime: {
    vix_regime: string;
    trend_regime: string;
    btc_dominance: number;
    btc_funding_rate: number;
    ts: string | null;
    label: string;
    description: string;
  };
  sleeves: {
    stocks: DashV2Sleeve;
    crypto: DashV2Sleeve;
    options: DashV2Sleeve;
  };
  health: {
    bots_active: number;
    bots_total: number;
    last_signal_minutes_ago: number | null;
    status: "ok" | "warn";
  };
  recent_signals: Array<{
    id: number;
    ts: string;
    bot_name: string;
    display_name: string;
    symbol: string;
    side: "buy" | "sell" | "long" | "short" | "hold";
    confidence: number;
    reason: string;
    strategy: string;
  }>;
  analyst_highlights: AnalystHighlight[];
  open_positions: Array<{
    id: number;
    symbol: string;
    side: string;
    qty: number;
    avg_cost_cents: number;
    current_price_cents: number | null;
    bot_name: string;
  }>;
}

export const getDashboardV2 = (): Promise<DashboardV2> =>
  client.get<DashboardV2>("/dashboard/v2").then((r) => r.data);

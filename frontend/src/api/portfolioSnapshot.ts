import client from "@/api/client";

export interface BotSnap {
  id: string;
  display_name: string;
  category: "stocks" | "crypto" | "options" | "quant";
  tier: string | null;
  status: "active" | "paused" | "disabled" | "admin_locked" | "unknown";
  enabled: boolean;
  is_admin_locked: boolean;
  open_positions: number;
  today_pnl_cents: number;
  alltime_pnl_cents: number;
  return_30d_pct: number;
  return_alltime_pct: number;
  starting_capital_cents: number;
  current_value_cents: number;
  allocation_pct_of_sleeve: number;
  description: string;
}

export interface SleeveSnap {
  starting_capital_cents: number;
  current_value_cents: number;
  open_positions: number;
  today_pnl_cents: number;
  alltime_pnl_cents: number;
  alltime_return_pct: number;
  return_30d_pct: number;
  active_bots: number;
  total_bots: number;
  bot_ids: string[];
  reserved_capital_cents: number;
}

export interface PortfolioSnapshot {
  as_of: string;
  user_id: number;
  total_value_cents: number;
  total_starting_capital_cents: number;
  total_open_positions: number;
  total_pnl_today_cents: number;
  total_pnl_alltime_cents: number;
  return_30d_pct: number;
  return_alltime_pct: number;
  capital_allocation: {
    stocks_pct: number;
    crypto_pct: number;
    options_pct: number;
    quant_pct: number;
    cash_pct: number;
  };
  by_sleeve: {
    stocks: SleeveSnap;
    crypto: SleeveSnap;
    options: SleeveSnap;
    quant: SleeveSnap;
  };
  bots: BotSnap[];
}

const EMPTY_SLEEVE: SleeveSnap = {
  starting_capital_cents: 0, current_value_cents: 0, open_positions: 0,
  today_pnl_cents: 0, alltime_pnl_cents: 0, alltime_return_pct: 0,
  return_30d_pct: 0, active_bots: 0, total_bots: 0, bot_ids: [],
  reserved_capital_cents: 0,
};

export const EMPTY_SNAPSHOT: PortfolioSnapshot = {
  as_of: new Date().toISOString(),
  user_id: 0,
  total_value_cents: 0,
  total_starting_capital_cents: 0,
  total_open_positions: 0,
  total_pnl_today_cents: 0,
  total_pnl_alltime_cents: 0,
  return_30d_pct: 0,
  return_alltime_pct: 0,
  capital_allocation: { stocks_pct: 0, crypto_pct: 0, options_pct: 0, quant_pct: 0, cash_pct: 100 },
  by_sleeve: { stocks: EMPTY_SLEEVE, crypto: EMPTY_SLEEVE, options: EMPTY_SLEEVE, quant: EMPTY_SLEEVE },
  bots: [],
};

export const getPortfolioSnapshot = (): Promise<PortfolioSnapshot> =>
  client
    .get<PortfolioSnapshot>("/portfolio/snapshot")
    .then((r) => r.data)
    .catch(() => EMPTY_SNAPSHOT);

import client from "./client";

export interface RiskConsole {
  as_of: string;
  fund: {
    pv_cents: number;
    starting_cents: number;
    all_time_pnl_cents: number;
    pnl_windows?: {
      all_time?: { cents: number; pct: number };
      mtd?: { cents: number; pct: number };
      wtd?: { cents: number; pct: number };
      today?: { cents: number; pct: number };
    };
  };
  deployment: {
    deployed_usd: number;
    unrealized_usd: number;
    deployment_pct: number;
    cash_reserve_pct: number;
    open_positions_count: number;
    top5_concentration_pct: number;
    sleeve_notional_usd: Record<string, number>;
  };
  drawdown: {
    max_drawdown_pct: number;
    max_drawdown_cents: number;
    peak_date?: string;
    trough_date?: string;
    days_of_data: number;
    equity_curve?: Array<{ date: string; value_cents: number }>;
  };
  var: {
    var_95_1d_cents: number;
    days_of_data: number;
    note?: string;
  };
  correlation: {
    bot_count: number;
    pairs_computed: number;
    top_correlated: Array<{ bot_a: string; bot_b: string; corr: number; n_days: number }>;
  };
  net_exposure_by_symbol: Array<{
    symbol: string;
    notional_usd: number;
    unrealized_usd: number;
    bots: string[];
    positions_count: number;
    is_option: boolean;
  }>;
}

export interface FlattenAllResult {
  closed: number;
  attempted: number;
  reason: string;
  results: Array<{ position_id: number; symbol: string; status: string; exit_price_usd?: number; error?: string }>;
  note?: string;
}

export const getRiskConsole = (): Promise<RiskConsole> =>
  client.get<RiskConsole>("/risk/console").then((r) => r.data);

export const flattenAll = (reason?: string): Promise<FlattenAllResult> =>
  client
    .post<FlattenAllResult>("/risk/flatten-all", { confirm: "FLATTEN_ALL", reason: reason || "manual_flatten" })
    .then((r) => r.data);

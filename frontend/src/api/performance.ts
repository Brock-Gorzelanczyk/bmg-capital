import client from "./client";

export type Period = "7d" | "30d" | "90d" | "all";
export type LeaderboardMetric = "sharpe" | "total_return_pct" | "win_rate" | "profit_factor" | "today_pnl_usd";
export type StratSort = "pnl" | "return" | "win_rate" | "trades" | "sharpe";

export interface BotMetrics {
  allocation_id: number;
  bot_name: string;
  starting_capital_usd: number;
  total_return_pct: number | null;
  total_return_usd: number | null;
  today_pnl_usd: number | null;
  period_return_pct: number | null;
  sharpe: number | null;
  sortino: number | null;
  calmar: number | null;
  max_drawdown_pct: number | null;
  max_drawdown_usd: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  avg_win_usd: number | null;
  avg_loss_usd: number | null;
  win_loss_ratio: number | null;
  avg_hold_hours: number | null;
  best_trade_usd: number | null;
  worst_trade_usd: number | null;
  total_trades: number;
  open_positions: number;
  data_days: number;
}

export interface EquityPoint {
  date: string;
  equity_usd: number;
  drawdown_pct: number;
}

export interface MonthlyReturn {
  year: number;
  month: number;
  return_pct: number;
}

export interface StrategyRow {
  strategy: string;
  pnl_usd: number;
  raw_return_pct: number | null;
  capital_deployed_usd: number;
  weight_pct: number | null;
  num_trades: number;
}

export interface SymbolRow {
  symbol: string;
  pnl_usd: number;
  num_trades: number;
}

export interface TimeOfDayRow {
  hour: number;
  avg_pnl_usd: number;
  num_trades: number;
}

export interface RegimeRow {
  regime: string;
  pnl_usd: number;
  num_trades: number;
}

export interface LeaderboardBot {
  allocation_id: number;
  bot_name: string;
  sharpe: number | null;
  total_return_pct: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  total_trades: number;
  today_pnl_usd: number | null;
}

export interface StrategyLeaderboardRow {
  strategy_id: string;
  strategy_name: string;
  category: string;
  total_pnl_usd: number;
  weighted_return_pct: number | null;
  total_trades: number;
  win_rate: number | null;
  sharpe: number | null;
  bots_using: number;
  source: string;
}

// ── API calls ─────────────────────────────────────────────────────────────────

const BASE = "/performance";

export const getPortfolioPerformance = (period: Period = "30d"): Promise<BotMetrics> =>
  client.get(`${BASE}/portfolio`, { params: { period } }).then((r) => r.data);

export const getBotLeaderboard = (
  metric: LeaderboardMetric = "sharpe",
  period: Period = "30d",
): Promise<{ leaderboard: LeaderboardBot[] }> =>
  client.get(`${BASE}/leaderboard`, { params: { metric, period } }).then((r) => r.data);

export const getBotPerformance = (botName: string, period: Period = "30d"): Promise<BotMetrics> =>
  client.get(`${BASE}/bots/${botName}`, { params: { period } }).then((r) => r.data);

export const getBotEquityCurve = (
  botName: string,
  days = 30,
): Promise<{ curve: EquityPoint[] }> =>
  client.get(`${BASE}/bots/${botName}/equity-curve`, { params: { days } }).then((r) => r.data);

export const getBotMonthlyReturns = (
  botName: string,
): Promise<{ monthly: MonthlyReturn[] }> =>
  client.get(`${BASE}/bots/${botName}/monthly-returns`).then((r) => r.data);

export const getBotStrategyAttribution = (
  botName: string,
  period: Period = "all",
): Promise<{ attribution: StrategyRow[]; total_capital_usd: number }> =>
  client
    .get(`${BASE}/bots/${botName}/strategy-attribution`, { params: { period } })
    .then((r) => r.data);

export const getBotSymbolAttribution = (
  botName: string,
  top = 5,
): Promise<{ symbols: SymbolRow[] }> =>
  client
    .get(`${BASE}/bots/${botName}/symbol-attribution`, { params: { top } })
    .then((r) => r.data);

export const getBotTimeOfDay = (botName: string): Promise<{ time_of_day: TimeOfDayRow[] }> =>
  client.get(`${BASE}/bots/${botName}/time-of-day`).then((r) => r.data);

export const getBotRegimeBreakdown = (botName: string): Promise<{ regimes: RegimeRow[] }> =>
  client.get(`${BASE}/bots/${botName}/regime-breakdown`).then((r) => r.data);

export const getStrategyLeaderboard = (
  period: Period = "30d",
  sort: StratSort = "pnl",
  category?: string,
): Promise<{ strategies: StrategyLeaderboardRow[]; period: string; sort: string }> =>
  client
    .get(`${BASE}/strategy-leaderboard`, { params: { period, sort, category } })
    .then((r) => r.data);

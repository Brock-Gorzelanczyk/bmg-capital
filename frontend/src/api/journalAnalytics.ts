import client from "./client";

export interface BestWorstTrade {
  symbol: string;
  pnl: number;
  pnl_pct: number;
  date: string;
}

export interface HeadlineStats {
  total_trades: number;
  win_rate: number;
  profit_factor: number;
  avg_r_multiple: number;
  total_pnl: number;
  max_drawdown: number;
  avg_hold_days: number;
  best_trade: BestWorstTrade;
  worst_trade: BestWorstTrade;
}

export interface EquityPoint {
  date: string;
  cumulative_pnl: number;
}

export interface SetupRow {
  setup: string;
  trade_count: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_pnl: number;
  total_pnl: number;
  avg_r_multiple: number;
}

export interface SymbolRow {
  symbol: string;
  trade_count: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
}

export interface MonthRow {
  month: string;
  trade_count: number;
  total_pnl: number;
  win_rate: number;
}

export interface RBucket {
  bucket: string;
  count: number;
}

export interface Streaks {
  current_win_streak: number;
  current_loss_streak: number;
  longest_win_streak: number;
  longest_loss_streak: number;
}

export interface MoodRow {
  mood: number;
  count: number;
  avg_pnl: number;
  win_rate: number;
}

export interface AnalyticsFilters {
  days: number;
  account_type: string;
  cutoff_date: string;
}

export interface AnalyticsResult {
  headline: HeadlineStats;
  equity_curve: EquityPoint[];
  by_setup: SetupRow[];
  by_symbol: SymbolRow[];
  by_month: MonthRow[];
  r_distribution: RBucket[];
  streaks: Streaks;
  by_mood: MoodRow[];
  filters: AnalyticsFilters;
}

export async function getJournalAnalytics(
  days = 365,
  accountType = "all"
): Promise<AnalyticsResult> {
  const { data } = await client.get("/journal/analytics", {
    params: { days, account_type: accountType },
  });
  return data;
}

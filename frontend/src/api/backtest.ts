import client from "./client";

export interface BacktestMetrics {
  total_return_pct: number;
  cagr: number;
  win_rate: number;
  avg_win_pct: number;
  avg_loss_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  profit_factor: number;
  total_trades: number;
}

export interface BacktestEquityPoint {
  date: string;
  value: number;
}

export interface BacktestTrade {
  symbol: string;
  entry_date: string;
  entry_price: number;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: string;
  pnl_pct: number;
  pnl: number;
}

export interface BacktestStrategySummary extends BacktestMetrics {
  strategy_key: string;
  strategy_label: string;
}

export interface BacktestStatusResponse {
  running: boolean;
  available: boolean;
  run_date: string | null;
  period_years: number | null;
}

export interface BacktestResultsResponse {
  run_date: string;
  period_years: number;
  strategies: BacktestStrategySummary[];
}

export interface BacktestDetailResponse {
  strategy_key: string;
  strategy_label: string;
  metrics: BacktestMetrics;
  equity_curve: BacktestEquityPoint[];
  trades: BacktestTrade[];
  period_years: number;
  run_date: string;
}

export const getBacktestStatus = () =>
  client.get<BacktestStatusResponse>("/api/backtest/status").then((r) => r.data);

export const runBacktest = (period_years = 3) =>
  client.post<{ ok: boolean; message: string }>(`/api/backtest/run?period_years=${period_years}`).then((r) => r.data);

export const getBacktestResults = () =>
  client.get<BacktestResultsResponse>("/api/backtest/results").then((r) => r.data);

export const getBacktestDetail = (strategyKey: string) =>
  client.get<BacktestDetailResponse>(`/api/backtest/results/${strategyKey}`).then((r) => r.data);

export const STRATEGY_LABELS: Record<string, string> = {
  canslim_leaders:        "CAN SLIM Leaders",
  stage2_breakout:        "Stage 2 Breakout",
  momentum_surge:         "Momentum Surge",
  high_rs_momentum:       "High RS Leaders",
  power_trend:            "Power Trend",
  turtle_breakout:        "Turtle Breakout",
  momentum_12m:           "12-Month Momentum",
  darvas_box:             "Darvas Box",
  mean_reversion_quality: "Quality Dip Buy",
  deep_value_bounce:      "Quality Oversold",
  rsi_oversold:           "RSI Oversold",
  zscore_reversion:       "Z-Score Reversion",
  volatility_contraction: "Volatility Squeeze",
  ema_stack_uptrend:      "EMA Stack",
  consecutive_gains:      "Momentum Continuation",
  golden_cross:           "Golden Cross",
  macd_bullish:           "MACD Crossover",
  volume_surge:           "Volume Surge",
  breakout_52w:           "52-Week High",
};

export const STRATEGY_KEYS = Object.keys(STRATEGY_LABELS);

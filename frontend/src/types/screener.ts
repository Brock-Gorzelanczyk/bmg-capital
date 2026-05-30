export interface FilterConfig {
  field: string;
  operator: string;
  value: string | number | boolean;
}

export interface FilterChip {
  field: string;
  operator: string;
  value: string | number;
  label: string;
}

export interface ScreenResult {
  symbol: string;
  price: number;
  change_pct: number;
  change_5d: number;
  volume: number;
  rel_volume: number;
}

export type PresetName =
  | "rsi_oversold" | "golden_cross" | "macd_bullish" | "volume_surge" | "breakout_52w"
  | "stage2_breakout" | "canslim_leaders" | "momentum_surge" | "high_rs_momentum" | "power_trend"
  | "mean_reversion_quality" | "deep_value_bounce"
  | "volatility_contraction" | "ema_stack_uptrend" | "consecutive_gains";

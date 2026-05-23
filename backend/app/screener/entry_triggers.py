from __future__ import annotations

"""
Per-strategy entry trigger logic.

Each trigger function receives:
  df  — pandas DataFrame with columns: open, high, low, close, volume (daily bars, most recent last)
  trade — StrategyTrade ORM object in "candidate" status

Returns True when the trigger condition is met and the trade should be entered.
"""

from typing import Callable, Dict

import pandas as pd
import ta


# ---------------------------------------------------------------------------
# Trigger implementations
# ---------------------------------------------------------------------------

def _breakout_pivot(df: pd.DataFrame, trade) -> bool:
    """Close above 5-day high with volume > 1.3× average."""
    if len(df) < 8:
        return False
    recent_high = df["close"].iloc[-6:-1].max()
    today_vol = df["volume"].iloc[-1]
    avg_vol = df["volume"].iloc[-22:-1].mean() if len(df) >= 23 else df["volume"].mean()
    return bool(
        df["close"].iloc[-1] > recent_high
        and today_vol > 1.3 * avg_vol
    )


def _rsi_recovery_35(df: pd.DataFrame, trade) -> bool:
    """RSI crosses from below 35 to above 35 — momentum turning up."""
    if len(df) < 16:
        return False
    rsi = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    return bool(rsi.iloc[-2] < 35 and rsi.iloc[-1] >= 35)


def _rsi_recovery_32(df: pd.DataFrame, trade) -> bool:
    """RSI crosses from below 32 to above 32 — deeper oversold recovery."""
    if len(df) < 16:
        return False
    rsi = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    return bool(rsi.iloc[-2] < 32 and rsi.iloc[-1] >= 32)


def _ema_pullback(df: pd.DataFrame, trade) -> bool:
    """Price pulled back to within 1.5% of EMA21 and closed green above it."""
    if len(df) < 25:
        return False
    ema21 = df["close"].ewm(span=21, adjust=False).mean().iloc[-1]
    low = df["low"].iloc[-1]
    close = df["close"].iloc[-1]
    open_ = df["open"].iloc[-1]
    touched = low <= ema21 * 1.015
    green = close > open_
    above = close > ema21
    return bool(touched and green and above)


def _squeeze_breakout(df: pd.DataFrame, trade) -> bool:
    """Close above the 10-day range high — coiled energy released."""
    if len(df) < 12:
        return False
    range_high = df["high"].iloc[-11:-1].max()
    return bool(df["close"].iloc[-1] > range_high)


def _next_open(df: pd.DataFrame, trade) -> bool:
    """Enter on the next daily check — no additional condition required."""
    return True


def _volume_direction(df: pd.DataFrame, trade) -> bool:
    """Volume surge day must have been an up day (close > open)."""
    return bool(df["close"].iloc[-1] > df["open"].iloc[-1])


def _turtle_breakout(df: pd.DataFrame, trade) -> bool:
    """55-day channel breakout."""
    if len(df) < 57:
        return False
    channel_high = df["high"].iloc[-56:-1].max()
    return bool(df["close"].iloc[-1] > channel_high)


def _zscore_recovery(df: pd.DataFrame, trade) -> bool:
    """Z-score crosses from below -2 to above -1.5."""
    if len(df) < 22:
        return False
    ma = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std()
    z = (df["close"] - ma) / std
    if pd.isna(z.iloc[-1]) or pd.isna(z.iloc[-2]):
        return False
    return bool(z.iloc[-2] < -2.0 and z.iloc[-1] > -1.5)


def _darvas_breakout(df: pd.DataFrame, trade) -> bool:
    """Price breaks above the box top (5-day high) on volume."""
    return _breakout_pivot(df, trade)


# ---------------------------------------------------------------------------
# Registry — maps preset_key → trigger function
# ---------------------------------------------------------------------------

TRIGGER_MAP: Dict[str, Callable] = {
    # Breakout setups
    "canslim_leaders":       _breakout_pivot,
    "stage2_breakout":       _breakout_pivot,
    "momentum_surge":        _breakout_pivot,
    "breakout_52w":          _breakout_pivot,
    "darvas_box":            _darvas_breakout,
    "turtle_breakout":       _turtle_breakout,

    # Mean reversion — wait for RSI to turn
    "mean_reversion_quality": _rsi_recovery_35,
    "deep_value_bounce":      _rsi_recovery_32,
    "rsi_oversold":           _rsi_recovery_32,
    "zscore_reversion":       _zscore_recovery,

    # Trend following — enter on EMA pullback
    "power_trend":          _ema_pullback,
    "ema_stack_uptrend":    _ema_pullback,

    # Pattern squeeze breakout
    "volatility_contraction": _squeeze_breakout,

    # Enter next check (confirmation already built into screen)
    "high_rs_momentum":   _next_open,
    "consecutive_gains":  _next_open,
    "macd_bullish":       _next_open,
    "golden_cross":       _next_open,
    "momentum_12m":       _next_open,

    # Direction-dependent
    "volume_surge": _volume_direction,
}

# How many calendar days a candidate can wait before expiring
CANDIDATE_MAX_DAYS = 14  # ~10 trading days


# ---------------------------------------------------------------------------
# Conviction tiers and R multiples
# ---------------------------------------------------------------------------

CONVICTION: Dict[str, str] = {
    "stage2_breakout":        "high",
    "canslim_leaders":        "high",
    "volatility_contraction": "high",
    "darvas_box":             "high",
    "momentum_surge":         "medium",
    "breakout_52w":           "medium",
    "power_trend":            "medium",
    "ema_stack_uptrend":      "medium",
    "high_rs_momentum":       "medium",
    "golden_cross":           "medium",
    "turtle_breakout":        "medium",
    "momentum_12m":           "medium",
    "mean_reversion_quality": "low",
    "deep_value_bounce":      "low",
    "consecutive_gains":      "low",
    "macd_bullish":           "low",
    "rsi_oversold":           "low",
    "volume_surge":           "low",
    "zscore_reversion":       "low",
}

RISK_DOLLARS: Dict[str, float] = {
    "high":   2000.0,
    "medium": 1500.0,
    "low":    1000.0,
}

# Risk:reward multiples — stop is 2×ATR, target is R_MULTIPLE × 2×ATR
R_MULTIPLE: Dict[str, float] = {
    "stage2_breakout":        3.0,
    "canslim_leaders":        3.0,
    "volatility_contraction": 3.5,
    "darvas_box":             3.0,
    "turtle_breakout":        4.0,
    "momentum_12m":           3.5,
    "ema_stack_uptrend":      4.0,
    "power_trend":            3.5,
    "momentum_surge":         2.5,
    "breakout_52w":           3.0,
    "high_rs_momentum":       2.5,
    "golden_cross":           3.0,
    "consecutive_gains":      2.0,
    "mean_reversion_quality": 1.5,
    "deep_value_bounce":      1.5,
    "rsi_oversold":           1.5,
    "volume_surge":           2.0,
    "zscore_reversion":       1.5,
    "macd_bullish":           2.0,
}

# Momentum presets paused in risk-off regimes
MOMENTUM_PRESETS = {
    "canslim_leaders", "stage2_breakout", "momentum_surge", "high_rs_momentum",
    "power_trend", "breakout_52w", "turtle_breakout", "momentum_12m",
    "darvas_box", "consecutive_gains", "ema_stack_uptrend",
}

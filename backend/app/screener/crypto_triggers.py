from __future__ import annotations

"""
Entry triggers for crypto strategy presets.

Same pattern as entry_triggers.py but for crypto.
Each trigger function receives (symbol, bars_df) and returns True when the
entry condition is confirmed (e.g., RSI turning up, breakout confirmed).
"""

import logging
from typing import Callable

import pandas as pd
import ta

logger = logging.getLogger(__name__)

# Risk / sizing constants (mirrors equity values, but crypto uses smaller sizing)
CRYPTO_RISK_DOLLARS = 150.0      # $ at risk per trade
CRYPTO_R_MULTIPLE   = 3.0        # target = entry + 3R
CRYPTO_CONVICTION: dict[str, float] = {
    "btc_ma_crossover":      1.2,
    "rsi_oversold_crypto":   0.9,
    "breakout_30d_high":     1.1,
    "volume_surge_crypto":   1.0,
    "dca_accumulation":      0.8,
    "momentum_continuation": 1.0,
    "oversold_bounce":       0.9,
    "golden_zone_retrace":   1.0,
}
CRYPTO_CANDIDATE_MAX_DAYS = 10  # expire watching sooner (crypto moves faster)


def _rsi(df: pd.DataFrame, window: int = 14) -> pd.Series:
    return ta.momentum.RSIIndicator(df["close"], window=window).rsi()


def _ma(df: pd.DataFrame, window: int) -> float:
    return float(df["close"].rolling(window).mean().iloc[-1])


# ── Trigger functions ──────────────────────────────────────────────────────────

def _ma_cross_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """50-day MA crossed above 200-day MA in the last 3 bars."""
    if len(df) < 205:
        return False
    ma50 = df["close"].rolling(50).mean()
    ma200 = df["close"].rolling(200).mean()
    for i in range(-3, 0):
        if ma50.iloc[i - 1] < ma200.iloc[i - 1] and ma50.iloc[i] >= ma200.iloc[i]:
            return True
    return False


def _rsi_recovery_crypto(symbol: str, df: pd.DataFrame) -> bool:
    """RSI crossed above 35 from below (recovering from oversold)."""
    if len(df) < 16:
        return False
    rsi = _rsi(df)
    return float(rsi.iloc[-2]) < 35 and float(rsi.iloc[-1]) >= 35


def _breakout_30d(symbol: str, df: pd.DataFrame) -> bool:
    """Price closes above the 30-day high (confirmed breakout)."""
    if len(df) < 31:
        return False
    high_30 = float(df["close"].iloc[-31:-1].max())
    return float(df["close"].iloc[-1]) > high_30


def _volume_surge_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """Volume 2x+ the 20-day average and price up on the day."""
    if len(df) < 21:
        return False
    vol_avg = float(df["volume"].iloc[-21:-1].mean())
    last_vol = float(df["volume"].iloc[-1])
    last_close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2])
    return last_vol >= 2.0 * vol_avg and last_close > prev_close


def _dca_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """RSI below 40 and price down 3-15% from 30-day high (DCA accumulation zone)."""
    if len(df) < 31:
        return False
    rsi_val = float(_rsi(df).iloc[-1])
    high_30 = float(df["close"].iloc[-31:].max())
    current = float(df["close"].iloc[-1])
    drawdown = (high_30 - current) / high_30 * 100
    return rsi_val < 40 and 3.0 <= drawdown <= 15.0


def _momentum_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """RSI between 55-75 and price above both 50d and 200d MA."""
    if len(df) < 205:
        return False
    rsi_val = float(_rsi(df).iloc[-1])
    current = float(df["close"].iloc[-1])
    return 55 <= rsi_val <= 75 and current > _ma(df, 50) and current > _ma(df, 200)


def _oversold_bounce_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """RSI crossed above 30 (leaving extreme oversold)."""
    if len(df) < 16:
        return False
    rsi = _rsi(df)
    return float(rsi.iloc[-2]) < 30 and float(rsi.iloc[-1]) >= 30


def _golden_zone_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """Price in RSI 40-60 range and above both MAs (balanced momentum)."""
    if len(df) < 205:
        return False
    rsi_val = float(_rsi(df).iloc[-1])
    current = float(df["close"].iloc[-1])
    return 40 <= rsi_val <= 60 and current > _ma(df, 50) and current > _ma(df, 200)


# ── Trigger map ────────────────────────────────────────────────────────────────

TriggerFn = Callable[[str, pd.DataFrame], bool]

CRYPTO_TRIGGER_MAP: dict[str, TriggerFn] = {
    "btc_ma_crossover":      _ma_cross_confirm,
    "rsi_oversold_crypto":   _rsi_recovery_crypto,
    "breakout_30d_high":     _breakout_30d,
    "volume_surge_crypto":   _volume_surge_confirm,
    "dca_accumulation":      _dca_confirm,
    "momentum_continuation": _momentum_confirm,
    "oversold_bounce":       _oversold_bounce_confirm,
    "golden_zone_retrace":   _golden_zone_confirm,
}

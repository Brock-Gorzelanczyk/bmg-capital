from __future__ import annotations

"""
Entry triggers for all 18 crypto strategy presets.

Per-coin triggers: fn(symbol, df) -> bool
Cross-sectional triggers use simple per-coin confirmation checks because
the screening phase already identified the best candidates cross-sectionally.
"""

import logging
from datetime import date
from typing import Callable

import pandas as pd
import ta

logger = logging.getLogger(__name__)

# Risk / sizing constants
CRYPTO_RISK_DOLLARS = 150.0
CRYPTO_R_MULTIPLE   = 3.0       # default target multiplier
CRYPTO_CANDIDATE_MAX_DAYS = 10

# Per-preset conviction multiplier (applied to CRYPTO_RISK_DOLLARS)
CRYPTO_CONVICTION: dict[str, float] = {
    # Phase 0 strategies
    "btc_ma_crossover":         1.3,
    "rsi_oversold_crypto":      0.9,
    "breakout_30d_high":        1.1,
    "volume_surge_crypto":      1.0,
    "dca_accumulation":         0.8,
    "momentum_continuation":    1.0,
    "oversold_bounce":          0.9,
    "golden_zone_retrace":      1.0,
    # Phase 1 per-coin
    "pi_cycle_top":             1.4,   # strong macro signal on BTC
    "donchian_breakout":        1.1,
    "tsmom":                    1.2,
    "ma_200w":                  1.3,   # historically very reliable BTC entry
    "zscore_reversal":          0.9,
    "halving_phase":            1.2,
    # Phase 1 cross-sectional
    "cross_sectional_momentum": 1.1,
    "altseason_index":          1.0,
    "eth_btc_ratio":            1.1,
    "narrative_basket":         0.9,
}

# Per-preset R-multiple override (target = entry + atr * 1.5 * R)
CRYPTO_R_MULTIPLES: dict[str, float] = {
    "btc_ma_crossover":         4.0,
    "pi_cycle_top":             5.0,   # macro cycle trade — hold longer
    "tsmom":                    4.0,
    "cross_sectional_momentum": 3.5,
    "ma_200w":                  4.0,
    "halving_phase":            4.0,
    "zscore_reversal":          2.0,   # mean reversion — tighter target
    "rsi_oversold_crypto":      2.0,
    "oversold_bounce":          2.0,
    "dca_accumulation":         2.5,
}


def _rsi(df: pd.DataFrame, window: int = 14) -> pd.Series:
    return ta.momentum.RSIIndicator(df["close"], window=window).rsi()


def _ma(df: pd.DataFrame, window: int) -> float:
    return float(df["close"].rolling(window).mean().iloc[-1])


# ── Phase 0 triggers (original 8) ─────────────────────────────────────────────

def _ma_cross_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """50-day MA crossed above 200-day MA within the last 3 bars."""
    if len(df) < 205:
        return False
    ma50  = df["close"].rolling(50).mean()
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
    """Volume 2x+ 20-day average and price up on the day."""
    if len(df) < 21:
        return False
    vol_avg   = float(df["volume"].iloc[-21:-1].mean())
    last_vol  = float(df["volume"].iloc[-1])
    last_cls  = float(df["close"].iloc[-1])
    prev_cls  = float(df["close"].iloc[-2])
    return last_vol >= 2.0 * vol_avg and last_cls > prev_cls


def _dca_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """RSI < 40 and price 3-15% below 30-day high (DCA accumulation zone)."""
    if len(df) < 31:
        return False
    rsi_val  = float(_rsi(df).iloc[-1])
    high_30  = float(df["close"].iloc[-31:].max())
    current  = float(df["close"].iloc[-1])
    drawdown = (high_30 - current) / high_30 * 100
    return rsi_val < 40 and 3.0 <= drawdown <= 15.0


def _momentum_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """RSI 55-75, price above both 50d and 200d MA."""
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
    """Price in RSI 40-60 range and above both MAs."""
    if len(df) < 205:
        return False
    rsi_val = float(_rsi(df).iloc[-1])
    current = float(df["close"].iloc[-1])
    return 40 <= rsi_val <= 60 and current > _ma(df, 50) and current > _ma(df, 200)


# ── Phase 1 per-coin triggers (6) ─────────────────────────────────────────────

def _pi_cycle_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """111MA recovering (rising for 3 bars) AND still well below 2×350MA."""
    if len(df) < 360:
        return False
    ma111 = df["close"].rolling(111).mean()
    ma350 = df["close"].rolling(350).mean()
    if pd.isna(ma111.iloc[-1]) or pd.isna(ma350.iloc[-1]):
        return False
    ratio = float(ma111.iloc[-1]) / (2.0 * float(ma350.iloc[-1]))
    if ratio >= 0.95:  # too close to cycle top, don't enter
        return False
    # Confirm 111MA is rising (recovering)
    return float(ma111.iloc[-1]) > float(ma111.iloc[-3])


def _donchian_20_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """Price closes above the 20-day high (Donchian breakout)."""
    if len(df) < 21:
        return False
    high_20 = float(df["close"].iloc[-21:-1].max())
    return float(df["close"].iloc[-1]) > high_20


def _tsmom_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """11-month return (skip 1 month) positive AND last month also positive."""
    if len(df) < 400:
        return False
    try:
        # 11-month return: price 30 days ago vs price 395 days ago
        ret_11m = float(df["close"].iloc[-30]) / float(df["close"].iloc[-395]) - 1
        # Last month return: confirms trend is still intact
        ret_1m  = float(df["close"].iloc[-1])  / float(df["close"].iloc[-31])  - 1
        return ret_11m > 0 and ret_1m > 0
    except (IndexError, ZeroDivisionError):
        return False


def _ma_200w_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """Price just crossed above 200-day MA after trading near or below it."""
    if len(df) < 205:
        return False
    ma200 = df["close"].rolling(200).mean()
    current   = float(df["close"].iloc[-1])
    prev      = float(df["close"].iloc[-3])
    ma_now    = float(ma200.iloc[-1])
    ma_before = float(ma200.iloc[-3])
    if pd.isna(ma_now) or pd.isna(ma_before):
        return False
    # Price crosses from below (or near) to above 200-day MA
    was_near_or_below = prev <= ma_before * 1.05
    now_above = current > ma_now
    return was_near_or_below and now_above


def _zscore_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """Z-score was below -2 and is now recovering (moving back toward mean)."""
    if len(df) < 22:
        return False
    window_now  = df["close"].iloc[-20:]
    window_prev = df["close"].iloc[-21:-1]
    std = float(window_now.std())
    if std <= 0:
        return False
    mean_now = float(window_now.mean())
    z_now  = (float(df["close"].iloc[-1])  - mean_now) / std
    z_prev = (float(df["close"].iloc[-2])  - mean_now) / std
    # Was oversold AND starting to recover
    return z_prev < -2.0 and z_now > z_prev


def _halving_phase_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """In the right halving phase AND price above 50-day MA."""
    if len(df) < 51:
        return False
    last_halving = date(2024, 4, 20)
    next_halving = date(2028, 4, 1)
    today = date.today()
    days_since = (today - last_halving).days
    days_to    = (next_halving - today).days
    in_phase = (days_to <= 180) or (0 <= days_since <= 540)
    if not in_phase:
        return False
    current = float(df["close"].iloc[-1])
    return current > _ma(df, 50)


# ── Phase 1 cross-sectional triggers (4) ──────────────────────────────────────
# These are simple per-coin confirmation checks; the cross-sectional screening
# already identified which coins are in the top cohort.

def _cross_sectional_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """Confirm momentum entry: price above 20MA, not overbought."""
    if len(df) < 21:
        return True
    rsi_val = float(_rsi(df).iloc[-1])
    current = float(df["close"].iloc[-1])
    ma20    = float(df["close"].rolling(20).mean().iloc[-1])
    return current > ma20 and rsi_val < 75


def _altseason_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """Alt in altseason: not overbought and momentum positive."""
    if len(df) < 16:
        return True
    rsi_val = float(_rsi(df).iloc[-1])
    return rsi_val < 70


def _eth_btc_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """ETH price above 20-day MA (individual confirmation)."""
    if len(df) < 21:
        return True
    current = float(df["close"].iloc[-1])
    ma20    = float(df["close"].rolling(20).mean().iloc[-1])
    return current > ma20


def _narrative_confirm(symbol: str, df: pd.DataFrame) -> bool:
    """Top narrative coin: price above 20MA and RSI not extreme."""
    if len(df) < 21:
        return True
    rsi_val = float(_rsi(df).iloc[-1])
    current = float(df["close"].iloc[-1])
    ma20    = float(df["close"].rolling(20).mean().iloc[-1])
    return current > ma20 and 30 <= rsi_val <= 80


# ── Trigger map ────────────────────────────────────────────────────────────────

TriggerFn = Callable[[str, pd.DataFrame], bool]

CRYPTO_TRIGGER_MAP: dict[str, TriggerFn] = {
    # Phase 0
    "btc_ma_crossover":         _ma_cross_confirm,
    "rsi_oversold_crypto":      _rsi_recovery_crypto,
    "breakout_30d_high":        _breakout_30d,
    "volume_surge_crypto":      _volume_surge_confirm,
    "dca_accumulation":         _dca_confirm,
    "momentum_continuation":    _momentum_confirm,
    "oversold_bounce":          _oversold_bounce_confirm,
    "golden_zone_retrace":      _golden_zone_confirm,
    # Phase 1 per-coin
    "pi_cycle_top":             _pi_cycle_confirm,
    "donchian_breakout":        _donchian_20_confirm,
    "tsmom":                    _tsmom_confirm,
    "ma_200w":                  _ma_200w_confirm,
    "zscore_reversal":          _zscore_confirm,
    "halving_phase":            _halving_phase_confirm,
    # Phase 1 cross-sectional
    "cross_sectional_momentum": _cross_sectional_confirm,
    "altseason_index":          _altseason_confirm,
    "eth_btc_ratio":            _eth_btc_confirm,
    "narrative_basket":         _narrative_confirm,
}

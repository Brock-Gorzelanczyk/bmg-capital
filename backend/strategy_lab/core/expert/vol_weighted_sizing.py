"""
Risk parity sizing: scale position size by realized volatility.

Target risk per position = max_position_risk_pct (default 1.0%).
Position size = target_risk / (realized_vol * ATR_factor).

Realized vol: 20-day annualized (sqrt(252) * std of daily returns).
Cap at max_position_size_pct (default 10%).
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

_ANNUALIZATION_FACTOR = math.sqrt(252)


def _realized_vol(bars: list[dict], period: int = 20) -> float | None:
    """Annualized realized volatility from daily returns."""
    closes = []
    for b in bars:
        c = b.get("c") or b.get("close")
        if c is not None:
            try:
                closes.append(float(c))
            except (TypeError, ValueError):
                pass

    if len(closes) < period + 1:
        return None

    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(len(closes) - period, len(closes))
        if closes[i - 1] != 0
    ]

    if len(returns) < 5:
        return None

    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    daily_std = math.sqrt(variance)
    annualized = daily_std * _ANNUALIZATION_FACTOR
    return annualized


def compute_vol_weighted_size(
    symbol: str,
    bars: list[dict],
    target_risk_pct: float = 1.0,  # from profile risk_overlay
    max_size_pct: float = 10.0,    # from profile
) -> float:
    """Returns position size as % of portfolio."""
    vol = _realized_vol(bars)

    if vol is None or vol <= 0:
        # Fallback: return half of max size
        fallback = max_size_pct / 2.0
        logger.debug(
            "[vol_sizing:%s] insufficient bars for vol, fallback size=%.2f%%",
            symbol, fallback,
        )
        return fallback

    # Position size = target_risk / realized_vol
    # Example: target_risk=1.0%, vol=20% → size=5%
    size = target_risk_pct / vol * 100  # vol is a decimal (0.20 = 20%), size in pct

    # Cap at max
    size = min(size, max_size_pct)

    # Floor at 0.5% to avoid trivially small positions
    size = max(size, 0.5)

    logger.debug(
        "[vol_sizing:%s] vol=%.2f%% target_risk=%.2f%% size=%.2f%% (max=%.2f%%)",
        symbol, vol * 100, target_risk_pct, size, max_size_pct,
    )
    return round(size, 4)

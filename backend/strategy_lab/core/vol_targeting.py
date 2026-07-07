"""Volatility-targeting overlay (Moreira & Muir 2017, SSRN 2659431).

Retrofit that scales any bot's position size by target_vol / realized_vol.
Documented to lift Sharpe by 20-40% on market, value, momentum, BAB,
ROE, and carry portfolios — pure post-hoc retrofit, no strategy change.

Usage in a strategy runner:

    from strategy_lab.core.vol_targeting import vol_target_scale
    scale = vol_target_scale(symbol_bars, target_vol=0.15)
    size_hint *= scale
    size_hint = min(size_hint, MAX_SIZE_HINT)

Reference: Moreira, Muir 2017 "Volatility-Managed Portfolios" JoF.
Key insight: volatility is persistent, expected returns are not.
Scaling by 1/vol overweights low-vol periods (positive expected return
per unit of vol) and underweights high-vol periods (poor risk-adjusted
returns historically).
"""
from __future__ import annotations

import logging
import math
from statistics import stdev
from typing import Optional

logger = logging.getLogger(__name__)


def _realized_vol(closes: list[float], window: int = 22) -> Optional[float]:
    """Annualized realized volatility over the last `window` bars.

    Uses daily log-returns; annualizes with √252.
    Returns None if insufficient data or zero-variance.
    """
    if len(closes) < window + 1:
        return None
    tail = closes[-(window + 1):]
    rets = []
    for i in range(1, len(tail)):
        prev, cur = tail[i - 1], tail[i]
        if prev <= 0 or cur <= 0:
            continue
        rets.append(math.log(cur / prev))
    if len(rets) < 3:
        return None
    try:
        s = stdev(rets)
        return s * math.sqrt(252)
    except Exception:
        return None


def vol_target_scale(
    closes: list[float],
    target_vol: float = 0.15,
    window: int = 22,
    cap: float = 2.0,
    floor: float = 0.25,
) -> float:
    """Return a multiplier for position size hint.

    scale = clip(target_vol / realized_vol, floor, cap)

    Defaults:
      target_vol = 15% annualized
      window     = 22-day realized vol
      cap        = 2.0  (never scale UP more than 2×)
      floor      = 0.25 (never scale DOWN below 25%)

    If realized vol can't be computed, returns 1.0 (no adjustment).
    """
    rv = _realized_vol(closes, window=window)
    if rv is None or rv <= 0:
        return 1.0
    raw_scale = target_vol / rv
    return max(floor, min(cap, raw_scale))

"""Overnight gap fade — Branch & Ma (2008) + Berkman et al. (2012).

Stocks that gap up sharply at the open tend to fade intraday; stocks
that gap down tend to recover.  This candidate fires a counter-trend
signal when the overnight gap exceeds a threshold.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "overnight_gap_fade"

# Minimum gap size to trigger a fade signal
_GAP_THRESHOLD = 0.015   # 1.5 % overnight gap
_LARGE_GAP = 0.040        # 4 % — higher conviction fade

# Avoid fading gaps that are too extreme (likely news-driven moves)
_MAX_GAP = 0.12           # 12 %


def _compute_gap(bar_list: list[dict]) -> float | None:
    """Gap = (today_open - yesterday_close) / yesterday_close."""
    if len(bar_list) < 2:
        return None
    prev_close = float(bar_list[-2].get("c", 0))
    today_open = float(bar_list[-1].get("o", 0))
    if prev_close <= 0 or today_open <= 0:
        return None
    return (today_open - prev_close) / prev_close


def generate_signals(
    bars: dict,
    profile_config: dict,
    regime: dict,
) -> List[Signal]:
    vix = regime.get("vix_regime", "mid")
    trend = regime.get("trend_regime", "chop")

    # Gap fades work best in mean-reverting / choppy markets
    # Reduce confidence in strong trending regimes
    trend_mult = 0.75 if trend == "bull" else 1.0
    # Avoid in panic — gaps can extend, not fade
    if vix == "panic":
        return []

    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        # Skip crypto — overnight gaps less meaningful on 24/7 markets
        if "/" in symbol:
            continue
        gap = _compute_gap(bar_list)
        if gap is None:
            continue
        abs_gap = abs(gap)
        if abs_gap < _GAP_THRESHOLD or abs_gap > _MAX_GAP:
            continue

        # Fade the gap: gap up → sell, gap down → buy
        side = "sell" if gap > 0 else "buy"
        base_conf = 0.62 if abs_gap >= _LARGE_GAP else 0.52
        conf = round(base_conf * trend_mult, 4)
        out.append(Signal(
            symbol=symbol,
            side=side,
            confidence=conf,
            size_hint=0.45,
            reason=f"Gap fade: gap={gap:.3f} ({abs_gap:.1%})",
            strategy=STRATEGY_NAME,
        ))
    return out


def generate_signal(
    symbol: str,
    closes: list[float],
    bars: list[dict] | None = None,
    **kwargs,
) -> Optional[Signal]:
    """Backwards-compat shim — requires bars kwarg for open prices."""
    bar_list = bars or []
    if len(bar_list) < 2:
        return None
    gap = _compute_gap(bar_list)
    if gap is None:
        return None
    abs_gap = abs(gap)
    if abs_gap < _GAP_THRESHOLD or abs_gap > _MAX_GAP:
        return None
    side = "sell" if gap > 0 else "buy"
    conf = 0.62 if abs_gap >= _LARGE_GAP else 0.52
    return Signal(
        symbol=symbol,
        side=side,
        confidence=conf,
        size_hint=0.45,
        reason=f"Gap fade: gap={gap:.3f}",
        strategy=STRATEGY_NAME,
    )

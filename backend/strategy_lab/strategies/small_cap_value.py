"""Small Cap Value strategy — low-price stocks with stabilizing momentum."""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "small_cap_value"
PRICE_CAP = 20.0      # proxy for small cap
MIN_MOM = -0.10       # not collapsing


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Return buy on small-cap value proxy conditions.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last. Requires len >= 60.
    """
    if len(closes) < 60:
        return []

    current = closes[-1]
    sixty_ago = closes[-60]

    if sixty_ago == 0:
        return []

    mom = (current - sixty_ago) / sixty_ago

    if current < PRICE_CAP and mom > MIN_MOM:
        confidence = max(0.3, min(0.7, 0.5 + mom))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Small-cap value: price ${current:.2f} < ${PRICE_CAP:.0f} cap; "
                f"60d momentum {mom*100:.1f}%"
            ),
            strategy=STRATEGY_NAME,
        )]

    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """New-style interface called by runner.py."""
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes))
    return out


def generate_signal(symbol: str, closes: list[float]) -> Optional[Signal]:
    """Backwards-compat shim."""
    signals = _v1_signals(symbol, closes)
    return signals[0] if signals else None

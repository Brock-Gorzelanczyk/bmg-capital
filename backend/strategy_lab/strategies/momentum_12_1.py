"""12-1 Month Momentum strategy — 12-month return excluding last month."""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "momentum_12_1"
MIN_MOMENTUM = 0.10  # 10% minimum 12-1 momentum


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Return buy on positive 12-1 month momentum.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last. Requires len >= 252.
    """
    if len(closes) < 252:
        return []

    price_12mo_ago = closes[-252]
    price_1mo_ago = closes[-21]

    if price_12mo_ago == 0:
        return []

    ret_12_1 = (price_1mo_ago - price_12mo_ago) / price_12mo_ago

    if ret_12_1 > MIN_MOMENTUM:
        confidence = max(0.4, min(0.9, ret_12_1 * 2))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"12-1 momentum: {ret_12_1*100:.1f}% return "
                f"(12mo-ago {price_12mo_ago:.2f} → 1mo-ago {price_1mo_ago:.2f})"
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

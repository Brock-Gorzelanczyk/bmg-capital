"""Dollar-Cost Averaging (DCA) strategy.

Always returns a "buy" signal for the target asset.
Size based on capital / position_cap (equal weight).
Used by crypto_lt and stock_lt for the DCA portion.
"""
from __future__ import annotations

import logging
from typing import List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "dca"


def generate_signals(
    symbol: str,
    capital: float,
    position_cap: int = 8,
) -> List[Signal]:
    """Return a single DCA buy signal sized by equal-weight capital allocation.

    Args:
        symbol: Ticker/pair to buy.
        capital: Total available capital in USD.
        position_cap: Maximum number of positions (divides capital equally).
    """
    size_hint = min(1.0, 1.0 / max(1, position_cap))
    return [Signal(
        symbol=symbol,
        side="buy",
        confidence=1.0,
        size_hint=size_hint,
        reason=f"DCA scheduled buy: 1/{position_cap} of ${capital:.0f} capital",
        strategy=STRATEGY_NAME,
    )]


# Backwards-compat shim
def generate_signal(symbol: str, size_hint: float = 1.0) -> Signal:
    """Single-call convenience wrapper (kept for backwards compatibility)."""
    return Signal(
        symbol=symbol,
        side="buy",
        confidence=1.0,
        size_hint=min(1.0, max(0.0, size_hint)),
        reason=f"DCA scheduled buy for {symbol}",
        strategy=STRATEGY_NAME,
    )

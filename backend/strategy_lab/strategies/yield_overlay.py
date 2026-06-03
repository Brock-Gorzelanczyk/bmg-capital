"""Yield Overlay strategy — park idle stablecoins in yield instruments."""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "yield_overlay"

# Stablecoin / USD-denominated asset identifiers
_STABLE_KEYWORDS = ("USD", "USDC", "USDT", "BUSD", "DAI", "TUSD", "FRAX", "GUSD")


def _is_stable(symbol: str) -> bool:
    """Return True if symbol represents a stable/USD asset."""
    upper = symbol.upper()
    return any(kw in upper for kw in _STABLE_KEYWORDS)


def _v1_signals(symbol: str) -> List[Signal]:
    """Return a low-confidence buy hint for stablecoin/yield parking.

    Args:
        symbol: Ticker/pair symbol.
    """
    if _is_stable(symbol):
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=0.3,
            size_hint=0.3,
            reason="Yield overlay: park idle stables in yield instrument (allocation hint)",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """New-style interface called by runner.py."""
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        out.extend(_v1_signals(symbol))
    return out


def generate_signal(symbol: str) -> Optional[Signal]:
    """Backwards-compat shim."""
    signals = _v1_signals(symbol)
    return signals[0] if signals else None

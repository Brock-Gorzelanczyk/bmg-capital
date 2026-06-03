"""BTC Dominance Rotation strategy — rotate between BTC and alts on dominance trend."""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "btc_dominance_rotation"

_BTC_SYMBOLS = {"BTC/USD", "BTCUSD", "BTC-USD", "XBTUSD", "BTC/USDT"}


def _is_btc(symbol: str) -> bool:
    return symbol.upper() in {s.upper() for s in _BTC_SYMBOLS}


def _v1_signals(
    symbol: str,
    closes: list[float],
    btc_dominance_rising: bool,
) -> List[Signal]:
    """Return rotation signal based on BTC dominance direction.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last.
        btc_dominance_rising: True if BTC dominance is rising.
    """
    if not closes:
        return []

    if btc_dominance_rising:
        if _is_btc(symbol):
            return [Signal(
                symbol=symbol,
                side="buy",
                confidence=0.6,
                size_hint=0.6,
                reason="BTC dominance rising — rotate into BTC",
                strategy=STRATEGY_NAME,
            )]
        else:
            return [Signal(
                symbol=symbol,
                side="sell",
                confidence=0.55,
                size_hint=0.55,
                reason="BTC dominance rising — reduce alt exposure",
                strategy=STRATEGY_NAME,
            )]
    else:
        if _is_btc(symbol):
            return [Signal(
                symbol=symbol,
                side="sell",
                confidence=0.55,
                size_hint=0.55,
                reason="BTC dominance falling — trim BTC, rotate to alts",
                strategy=STRATEGY_NAME,
            )]
        else:
            return [Signal(
                symbol=symbol,
                side="buy",
                confidence=0.55,
                size_hint=0.55,
                reason="BTC dominance falling — favor alt basket",
                strategy=STRATEGY_NAME,
            )]


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """New-style interface called by runner.py."""
    btc_dominance_rising: bool = bool(regime.get("btc_dominance_rising", False))
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, btc_dominance_rising))
    return out


def generate_signal(
    symbol: str,
    closes: list[float],
    btc_dominance_rising: bool = False,
) -> Optional[Signal]:
    """Backwards-compat shim."""
    signals = _v1_signals(symbol, closes, btc_dominance_rising)
    return signals[0] if signals else None

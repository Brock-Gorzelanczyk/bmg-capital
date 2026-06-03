"""Heikin-Ashi trend: smoothed candles, signal on N consecutive bullish HA bars."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "heikin_ashi_trend"


def _compute_ha(opens: list, highs: list, lows: list, closes: list):
    """Return lists of (ha_open, ha_close) pairs."""
    n = len(closes)
    ha_close = [(opens[i] + highs[i] + lows[i] + closes[i]) / 4 for i in range(n)]
    ha_open = [0.0] * n
    ha_open[0] = (opens[0] + closes[0]) / 2
    for i in range(1, n):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2
    return ha_open, ha_close


def _v1_signals(
    symbol: str, closes: list[float], opens: list[float],
    highs: list[float], lows: list[float]
) -> List[Signal]:
    """Core logic: 3+ consecutive bullish HA candles = buy."""
    if len(closes) < 5:
        return []
    ha_open, ha_close = _compute_ha(opens, highs, lows, closes)
    count_bull = sum(1 for i in range(-4, 0) if ha_close[i] > ha_open[i])
    if count_bull >= 3:
        conf = min(0.90, 0.60 + count_bull * 0.05)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"Heikin-Ashi trend: {count_bull}/4 bullish HA candles",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        opens = [float(b.get("o", 0)) for b in bar_list]
        highs = [float(b.get("h", 0)) for b in bar_list]
        lows = [float(b.get("l", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, opens, highs, lows))
    return out


def generate_signal(
    symbol: str, closes: list[float], opens: list[float] = None,
    highs: list[float] = None, lows: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not opens or not highs or not lows:
        return None
    sigs = _v1_signals(symbol, closes, opens, highs, lows)
    return sigs[0] if sigs else None

"""Shareholder Yield strategy — steady appreciation + monthly consistency proxy."""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "shareholder_yield"
MIN_ANNUAL_RETURN = 0.05
MIN_CONSISTENCY = 0.60


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Return buy on consistent annual appreciation (total return proxy).

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last. Requires len >= 252.
    """
    if len(closes) < 252:
        return []

    annual_return = (closes[-1] - closes[-252]) / closes[-252] if closes[-252] != 0 else 0.0

    # Monthly win rate: count months where close >= prior-month close
    monthly_wins = 0
    months = 0
    for i in range(-252, 0, 21):
        idx = len(closes) + i
        prev_idx = idx - 21
        if prev_idx >= 0 and closes[prev_idx] != 0:
            if closes[idx] >= closes[prev_idx]:
                monthly_wins += 1
            months += 1

    consistency = monthly_wins / months if months > 0 else 0.0

    if annual_return > MIN_ANNUAL_RETURN and consistency >= MIN_CONSISTENCY:
        confidence = max(0.35, min(0.8, consistency))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Shareholder yield: annual return {annual_return*100:.1f}%, "
                f"monthly consistency {consistency*100:.0f}%"
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

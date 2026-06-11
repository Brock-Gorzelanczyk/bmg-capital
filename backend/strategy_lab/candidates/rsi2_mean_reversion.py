"""RSI-2 mean reversion — Connors & Alvarez (2009).

A short-term mean-reversion strategy using a 2-period RSI.
Buy when RSI(2) drops below 10 (severely oversold) after the stock
is above its 200-day MA (long-term uptrend filter).  Sell when RSI(2)
closes above 70 (no fixed stop — exit on mean reversion).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "rsi2_mean_reversion"

_RSI_PERIOD = 2
_MA_PERIOD = 200
_OVERSOLD = 10.0
_OVERBOUGHT = 70.0


def _rsi(closes: list[float], period: int) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = closes[-(period + 1 - i) + period] - closes[-(period + 1 - i) + period - 1]
        (gains if delta >= 0 else losses).append(abs(delta))
    # Wilder smoothing — initial simple average
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _evaluate(closes: list[float]) -> tuple[str | None, float, str]:
    """Returns (side, confidence, reason) or (None, 0, '')."""
    if len(closes) < _MA_PERIOD + _RSI_PERIOD:
        return None, 0.0, ""

    ma200 = _sma(closes, _MA_PERIOD)
    rsi2 = _rsi(closes, _RSI_PERIOD)

    if ma200 is None or rsi2 is None:
        return None, 0.0, ""

    price = closes[-1]

    # Long setup: price above 200-MA AND RSI(2) < oversold threshold
    if price > ma200 and rsi2 < _OVERSOLD:
        depth = _OVERSOLD - rsi2
        conf = min(0.82, 0.60 + depth * 0.012)
        return "buy", conf, f"RSI2={rsi2:.1f} above MA200 — oversold reversion entry"

    # Exit / short setup: RSI(2) > overbought threshold
    if rsi2 > _OVERBOUGHT:
        excess = rsi2 - _OVERBOUGHT
        conf = min(0.75, 0.55 + excess * 0.005)
        return "sell", conf, f"RSI2={rsi2:.1f} — overbought reversion exit"

    return None, 0.0, ""


def generate_signals(
    bars: dict,
    profile_config: dict,
    regime: dict,
) -> List[Signal]:
    # RSI-2 is a mean-reversion play — avoid in strong trending regimes
    if regime.get("trend_regime") == "bull" and regime.get("vix_regime") == "low":
        return []

    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        # RSI-2 designed for equities; skip crypto
        if "/" in symbol:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        side, conf, reason = _evaluate(closes)
        if side is None:
            continue
        out.append(Signal(
            symbol=symbol,
            side=side,
            confidence=conf,
            size_hint=0.55,
            reason=reason,
            strategy=STRATEGY_NAME,
        ))
    return out


def generate_signal(
    symbol: str,
    closes: list[float],
    **kwargs,
) -> Optional[Signal]:
    """Backwards-compat shim."""
    side, conf, reason = _evaluate(closes)
    if side is None:
        return None
    return Signal(
        symbol=symbol,
        side=side,
        confidence=conf,
        size_hint=0.55,
        reason=reason,
        strategy=STRATEGY_NAME,
    )

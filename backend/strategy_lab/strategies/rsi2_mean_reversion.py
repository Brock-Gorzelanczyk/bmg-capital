"""RSI(2) mean reversion: buy when RSI(2) < 10, sell when RSI(2) > 65."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "rsi2_mean_reversion"


def _compute_rsi2(closes: list[float]) -> float:
    """Compute 2-period RSI using Wilder smoothing."""
    if len(closes) < 3:
        return 50.0
    gains, losses = [], []
    for i in range(-2, 0):
        delta = closes[i] - closes[i - 1]
        gains.append(max(0.0, delta))
        losses.append(max(0.0, -delta))
    avg_gain = sum(gains) / 2
    avg_loss = sum(losses) / 2
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: Connors RSI(2) extreme levels."""
    if len(closes) < 3:
        return []
    rsi2 = _compute_rsi2(closes)
    if rsi2 < 10:
        conf = max(0.50, min(0.90, (10 - rsi2) / 10))
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf, reason=f"RSI(2)={rsi2:.1f} < 10, oversold reversion buy",
            strategy=STRATEGY_NAME,
        )]
    if rsi2 > 65:
        conf = max(0.40, min(0.85, (rsi2 - 65) / 35))
        return [Signal(
            symbol=symbol, side="sell", confidence=conf,
            size_hint=conf, reason=f"RSI(2)={rsi2:.1f} > 65, overbought reversion sell",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes))
    return out


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Optional[Signal]:
    """Backwards-compat shim."""
    sigs = _v1_signals(symbol, closes)
    return sigs[0] if sigs else None

"""MeanReversionRsi — classic RSI oversold/overbought alpha.

Emits 'up' insights when RSI drops below rsi_low (oversold) and 'down'
insights when RSI rises above rsi_high (overbought).  Works on any
asset class; just pass the right bar history.
"""
from __future__ import annotations
import logging
from .base import AlphaModel
from ..types import Symbol, Bar, Insight
from ..context import AlgorithmContext

logger = logging.getLogger(__name__)


def _rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder's RSI."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = closes[-period + i] - closes[-period + i - 1]
        (gains if delta >= 0 else losses).append(abs(delta))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))


class MeanReversionRsi(AlphaModel):
    """RSI-based mean reversion signals."""

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_low: float = 30.0,
        rsi_high: float = 70.0,
    ) -> None:
        self._period = rsi_period
        self._rsi_low = rsi_low
        self._rsi_high = rsi_high

    @property
    def name(self) -> str:
        return f"mean_reversion_rsi(lo={self._rsi_low},hi={self._rsi_high})"

    async def generate_insights(
        self,
        ctx: AlgorithmContext,
        universe: list[Symbol],
        bars: dict[Symbol, list[Bar]],
    ) -> list[Insight]:
        insights = []
        for sym in universe:
            sym_bars = bars.get(sym, [])
            if len(sym_bars) < self._period + 1:
                continue
            closes = [b.close for b in sym_bars]
            rsi = _rsi(closes, self._period)
            if rsi is None:
                continue

            if rsi < self._rsi_low:
                confidence = round(min(0.95, (self._rsi_low - rsi) / self._rsi_low + 0.5), 3)
                insights.append(Insight(
                    symbol=sym,
                    direction="up",
                    confidence=confidence,
                    period="5d",
                    source=self.name,
                    reason=f"RSI({self._period})={rsi:.1f} < {self._rsi_low} — oversold, mean-revert up",
                ))
            elif rsi > self._rsi_high:
                confidence = round(min(0.95, (rsi - self._rsi_high) / (100 - self._rsi_high) + 0.5), 3)
                insights.append(Insight(
                    symbol=sym,
                    direction="down",
                    confidence=confidence,
                    period="5d",
                    source=self.name,
                    reason=f"RSI({self._period})={rsi:.1f} > {self._rsi_high} — overbought, mean-revert down",
                ))
        return insights

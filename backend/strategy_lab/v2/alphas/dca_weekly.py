"""DcaWeekly — Dollar Cost Averaging alpha.

Emits an 'up' insight for every symbol in the universe with full confidence.
There's no market-timing here — DCA always buys, every cycle, regardless of
price.  This is intentional: DCA's edge comes from consistency, not from
predicting entries.

The portfolio construction model downstream handles how much to buy based
on current positions vs target weights.
"""
from __future__ import annotations
from .base import AlphaModel
from ..types import Symbol, Bar, Insight
from ..context import AlgorithmContext


class DcaWeekly(AlphaModel):
    """Emit a BUY insight for every symbol in the universe every cycle.

    period: the investment horizon label attached to each insight.
    confidence: always 1.0 — we never second-guess DCA timing.
    """

    def __init__(self, period: str = "30d") -> None:
        self._period = period

    @property
    def name(self) -> str:
        return "dca_weekly"

    async def generate_insights(
        self,
        ctx: AlgorithmContext,
        universe: list[Symbol],
        bars: dict[Symbol, list[Bar]],
    ) -> list[Insight]:
        insights = []
        for sym in universe:
            price = ctx.cache.get_price(sym)
            price_str = f"@ ${price:,.2f}" if price else "(price unknown)"
            insights.append(Insight(
                symbol=sym,
                direction="up",
                confidence=1.0,
                period=self._period,
                source=self.name,
                reason=f"Weekly DCA — systematic buy regardless of price {price_str}",
            ))
        return insights

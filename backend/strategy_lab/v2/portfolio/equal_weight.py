"""EqualWeightPortfolio — divide capital equally across all up-insights.

Simplest sizing model.  If there are 5 'up' insights and $50,000 in capital,
each position gets $10,000.  Useful for strategies where you have no view
on which symbol will outperform within the selection.
"""
from __future__ import annotations
from .base import PortfolioConstructionModel
from ..types import Symbol, Insight, PortfolioTarget
from ..context import AlgorithmContext


class EqualWeightPortfolio(PortfolioConstructionModel):
    """Equal allocation across all symbols with an 'up' insight."""

    def __init__(
        self,
        max_positions: int = 10,
        capital_pct: float = 1.0,    # fraction of portfolio_value to deploy
        min_order_usd: float = 10.0,
    ) -> None:
        self._max_positions = max_positions
        self._capital_pct = min(1.0, max(0.0, capital_pct))
        self._min_order_usd = min_order_usd

    @property
    def name(self) -> str:
        return f"equal_weight(max={self._max_positions})"

    async def create_targets(
        self,
        ctx: AlgorithmContext,
        insights: list[Insight],
        current_positions: dict[Symbol, float],
        portfolio_value: float,
    ) -> list[PortfolioTarget]:
        # Sort by confidence desc, take top N
        up = sorted(
            [i for i in insights if i.direction == "up"],
            key=lambda i: i.confidence,
            reverse=True,
        )[: self._max_positions]

        if not up:
            return []

        deployable = portfolio_value * self._capital_pct
        per_position_usd = deployable / len(up)

        targets = []
        for insight in up:
            if per_position_usd < self._min_order_usd:
                continue
            price = ctx.cache.get_price(insight.symbol)
            if not price or price <= 0:
                ctx.log("warning", f"No price for {insight.symbol} — skipping")
                continue
            qty = per_position_usd / price
            targets.append(PortfolioTarget(
                symbol=insight.symbol,
                target_qty=round(qty, 8),
                reason=f"Equal weight: ${per_position_usd:.0f} of {len(up)}-way split @ ${price:,.2f}",
                target_value_usd=per_position_usd,
                source_insight=insight,
            ))

        return targets

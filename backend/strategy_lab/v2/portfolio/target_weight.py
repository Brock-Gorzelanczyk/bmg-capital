"""TargetWeightPortfolio — size positions to hit explicit target weights.

Used by crypto_lt which has fixed target allocations:
  BTC/USD: 40%, ETH/USD: 30%, SOL/USD: 15%, AVAX/USD: 10%, LINK/USD: 5%

Only generates BUY targets for symbols that are below their target weight
(it never sells when rebalancing downward — that would be handled by a
separate rebalancing alpha or execution model if the position is over-weight).

For a simple DCA overlay, this is correct: we only add, never subtract.
"""
from __future__ import annotations
import logging
from .base import PortfolioConstructionModel
from ..types import Symbol, Insight, PortfolioTarget
from ..context import AlgorithmContext

logger = logging.getLogger(__name__)


class TargetWeightPortfolio(PortfolioConstructionModel):
    """Allocate capital to match target weight percentages.

    target_weights: {symbol: fraction} where fractions sum to ~1.0
    weekly_dca_pct: fraction of free cash to deploy this cycle (0.0–1.0)
    """

    def __init__(
        self,
        target_weights: dict[Symbol, float],
        weekly_dca_pct: float = 1.0,
        min_order_usd: float = 10.0,
    ) -> None:
        total = sum(target_weights.values())
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"target_weights must sum to 1.0, got {total:.3f}")
        self._weights = target_weights
        self._weekly_dca_pct = min(1.0, max(0.0, weekly_dca_pct))
        self._min_order_usd = min_order_usd

    @property
    def name(self) -> str:
        return "target_weight"

    async def create_targets(
        self,
        ctx: AlgorithmContext,
        insights: list[Insight],
        current_positions: dict[Symbol, float],
        portfolio_value: float,
    ) -> list[PortfolioTarget]:
        # Only act on symbols the alpha liked
        up_symbols = {i.symbol for i in insights if i.direction == "up"}
        targets: list[PortfolioTarget] = []

        for sym, weight in self._weights.items():
            if sym not in up_symbols:
                continue

            price = ctx.cache.get_price(sym)
            if not price or price <= 0:
                ctx.log("warning", f"No price for {sym} — skipping target")
                continue

            # Current position value
            current_qty = current_positions.get(sym, 0.0)
            current_value = current_qty * price

            # Target value = portfolio_value × weight
            target_value = portfolio_value * weight

            # How much to buy to reach the target
            deficit_usd = (target_value - current_value) * self._weekly_dca_pct
            if deficit_usd < self._min_order_usd:
                ctx.log("debug", f"{sym}: deficit ${deficit_usd:.2f} below min ${self._min_order_usd} — skip")
                continue

            buy_qty = deficit_usd / price
            targets.append(PortfolioTarget(
                symbol=sym,
                target_qty=round(buy_qty, 8),
                reason=f"DCA to {weight*100:.0f}% target weight; deficit=${deficit_usd:.2f} @ ${price:,.2f}",
                target_value_usd=deficit_usd,
                source_insight=next((i for i in insights if i.symbol == sym), None),
            ))

        return targets

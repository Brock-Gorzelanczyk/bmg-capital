"""MarketImmediateExecution — market orders, fill as fast as possible.

In shadow mode (default): converts targets → Order objects but submits
nothing.  The runner logs what WOULD happen.

In paper mode: calls ctx.broker.submit_order() which writes to the paper
trading tables (not yet wired for live; will use POST /api/paper/orders
once the v2 runner graduates from shadow mode).
"""
from __future__ import annotations
from .base import ExecutionModel
from ..types import Symbol, PortfolioTarget, Order
from ..context import AlgorithmContext


class MarketImmediateExecution(ExecutionModel):
    """Convert targets to market orders and submit via the broker adapter."""

    def __init__(self, time_in_force: str = "gtc") -> None:
        self._tif = time_in_force

    @property
    def name(self) -> str:
        return "market_immediate"

    async def execute(
        self,
        ctx: AlgorithmContext,
        targets: list[PortfolioTarget],
        current_positions: dict[Symbol, float],
    ) -> list[Order]:
        orders = []
        for target in targets:
            if abs(target.target_qty) < 1e-8:
                continue

            delta = target.target_qty - current_positions.get(target.symbol, 0.0)
            if abs(delta) < 1e-8:
                ctx.log("debug", f"{target.symbol}: already at target qty — skip")
                continue

            side = "buy" if delta > 0 else "sell"
            qty = abs(delta)
            price = ctx.cache.get_price(target.symbol)

            order = Order(
                symbol=target.symbol,
                side=side,
                qty=round(qty, 8),
                order_type="market",
                time_in_force=self._tif,
                tag=f"v2:{ctx.bot_id}:market",
                estimated_fill_usd=qty * price if price else None,
            )

            resp = await ctx.broker.submit_order(order)
            ctx.log(
                "info",
                f"Order submitted: {side} {qty:.6f} {target.symbol} "
                f"(est. ${order.estimated_fill_usd:,.2f})" if order.estimated_fill_usd
                else f"Order submitted: {side} {qty:.6f} {target.symbol}",
            )
            orders.append(order)

        return orders

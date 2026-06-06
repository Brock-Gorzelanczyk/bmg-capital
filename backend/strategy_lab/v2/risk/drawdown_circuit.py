"""DrawdownCircuit — halt new entries when portfolio drawdown exceeds the limit.

Compares current portfolio value to the high-water mark.  When the
loss from peak exceeds `pct`, all new BUY targets are rejected.  SELL
targets (exits) are allowed through so the model can reduce positions.

For DCA strategies, this protects against buying into a freefall.
"""
from __future__ import annotations
from .base import RiskManagementModel
from ..types import Symbol, PortfolioTarget
from ..context import AlgorithmContext


class DrawdownCircuit(RiskManagementModel):
    """Veto new entries when peak drawdown exceeds `pct` (0.10 = 10%)."""

    def __init__(self, pct: float = 0.10) -> None:
        if not 0.0 < pct <= 1.0:
            raise ValueError("pct must be in (0, 1]")
        self._pct = pct

    @property
    def name(self) -> str:
        return f"drawdown_circuit({int(self._pct*100)}%)"

    async def manage_risk(
        self,
        ctx: AlgorithmContext,
        targets: list[PortfolioTarget],
        current_positions: dict[Symbol, float],
        portfolio_value: float,
    ) -> list[PortfolioTarget]:
        hwm = await ctx.broker.get_high_water_mark(ctx.bot_id)
        if hwm <= 0:
            return targets

        drawdown = (hwm - portfolio_value) / hwm

        if drawdown >= self._pct:
            ctx.log(
                "warning",
                f"DrawdownCircuit tripped: {drawdown*100:.1f}% drawdown "
                f"≥ {self._pct*100:.0f}% limit (HWM=${hwm:,.0f}, now=${portfolio_value:,.0f})",
            )
            ctx.emit("drawdown_circuit_tripped", {
                "drawdown_pct": round(drawdown * 100, 2),
                "hwm_usd": hwm,
                "current_usd": portfolio_value,
                "threshold_pct": self._pct * 100,
            })
            # Allow exits (qty heading toward 0), block new entries
            return [t for t in targets if t.target_qty <= 0]

        ctx.log("debug", f"DrawdownCircuit OK: {drawdown*100:.1f}% < {self._pct*100:.0f}%")
        return targets

"""DailyLossLimit — reject new entries if today's P&L exceeds the daily loss cap.

Reads the paper_accounts.day_pnl field (updated by the existing paper
trading executor).  When today's loss is worse than `pct` of yesterday's
portfolio value, all new BUY targets are rejected.
"""
from __future__ import annotations
from .base import RiskManagementModel
from ..types import Symbol, PortfolioTarget
from ..context import AlgorithmContext


class DailyLossLimit(RiskManagementModel):
    """Halt new entries if today's P&L < -pct of portfolio value."""

    def __init__(self, pct: float = 0.02) -> None:
        if not 0.0 < pct <= 1.0:
            raise ValueError("pct must be in (0, 1]")
        self._pct = pct

    @property
    def name(self) -> str:
        return f"daily_loss_limit({int(self._pct*100)}%)"

    async def manage_risk(
        self,
        ctx: AlgorithmContext,
        targets: list[PortfolioTarget],
        current_positions: dict[Symbol, float],
        portfolio_value: float,
    ) -> list[PortfolioTarget]:
        try:
            from app.db.models.paper import PaperAccount
            db = getattr(ctx.broker, "_db", None)
            user_id = getattr(ctx.broker, "_user_id", None)
            if db is None or user_id is None:
                return targets

            acct = db.query(PaperAccount).filter_by(user_id=user_id).first()
            if not acct:
                return targets

            day_pnl = float(acct.day_pnl or 0.0) if hasattr(acct, "day_pnl") else 0.0
            loss_pct = abs(day_pnl) / portfolio_value if portfolio_value > 0 and day_pnl < 0 else 0.0

            if loss_pct >= self._pct:
                ctx.log(
                    "warning",
                    f"DailyLossLimit tripped: {loss_pct*100:.1f}% loss "
                    f"≥ {self._pct*100:.0f}% cap (P&L=${day_pnl:,.0f})",
                )
                ctx.emit("daily_loss_limit_tripped", {
                    "day_pnl_usd": day_pnl,
                    "loss_pct": round(loss_pct * 100, 2),
                    "threshold_pct": self._pct * 100,
                })
                return [t for t in targets if t.target_qty <= 0]
        except Exception as exc:
            ctx.log("debug", f"DailyLossLimit check failed (non-fatal): {exc}")

        return targets

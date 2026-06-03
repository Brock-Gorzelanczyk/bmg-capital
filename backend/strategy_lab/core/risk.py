"""RiskManager — position sizing, stop application, and drawdown enforcement."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RiskManager:
    """Centralised risk rules for a single BotAllocation."""

    def __init__(
        self,
        capital_usd: float,
        position_size_pct: float,      # e.g. 12.5 means 1/8 of capital
        stop_loss_pct: Optional[float],  # e.g. -8.0; None = no hard stop
        take_profit_pct: Optional[float],
        max_drawdown_pct: float,        # e.g. -20.0
        trailing_stop_activate_at_pct: Optional[float] = None,
    ) -> None:
        self.capital_usd = capital_usd
        self.position_size_pct = position_size_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.trailing_stop_activate_at_pct = trailing_stop_activate_at_pct

    # ── Public API ──────────────────────────────────────────────────────────

    def position_size(self, price_usd: float, size_hint: float = 1.0) -> float:
        """Return share/unit quantity given current price and a [0,1] size hint."""
        if price_usd <= 0:
            return 0.0
        dollars = self.capital_usd * (self.position_size_pct / 100.0) * size_hint
        return dollars / price_usd

    def apply_stops(self, entry_price: float, current_price: float) -> Optional[str]:
        """Return exit reason string if a stop/target has been hit, else None."""
        if entry_price <= 0:
            return None
        pct_change = ((current_price - entry_price) / entry_price) * 100.0

        if self.stop_loss_pct is not None and pct_change <= self.stop_loss_pct:
            logger.debug("Stop-loss triggered: %.2f%% <= %.2f%%", pct_change, self.stop_loss_pct)
            return "stop_loss"

        if self.take_profit_pct is not None and pct_change >= self.take_profit_pct:
            logger.debug("Take-profit triggered: %.2f%% >= %.2f%%", pct_change, self.take_profit_pct)
            return "take_profit"

        return None

    def check_drawdown_cap(self, current_equity_usd: float) -> bool:
        """Return True if the portfolio has breached the max drawdown cap."""
        drawdown_pct = ((current_equity_usd - self.capital_usd) / self.capital_usd) * 100.0
        if drawdown_pct <= self.max_drawdown_pct:
            logger.warning(
                "Max drawdown cap breached: %.2f%% <= %.2f%%",
                drawdown_pct, self.max_drawdown_pct,
            )
            return True
        return False

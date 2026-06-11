"""SafeBrokerWrapper — wraps any BrokerAdapter with gate + blackout checks.

All checks are fail-open: if the safety code itself throws, the order
proceeds normally.  This wrapper intercepts submit_order and
submit_bracket_order; all other methods pass through transparently.
"""
from __future__ import annotations

import logging

from app.services.trading_gate import TradingGate, TradingHaltedException
from app.services.blackout_check import BlackoutCheck, BlackoutException

logger = logging.getLogger(__name__)


class SafeBrokerWrapper:
    """Wraps an inner BrokerAdapter with trading gate + blackout checks."""

    def __init__(self, inner):
        self._inner = inner

    def _check(self, symbol: str) -> None:
        """Raise TradingHaltedException or BlackoutException if blocked."""
        try:
            if not TradingGate.is_open():
                _audit("order_blocked", "trading_gate_closed", symbol)
                raise TradingHaltedException(
                    f"Trading gate closed — order for {symbol} rejected"
                )
        except TradingHaltedException:
            raise
        except Exception as exc:
            logger.warning("[safe_broker] gate check failed, proceeding: %s", exc)

        try:
            if BlackoutCheck.is_blacked_out(symbol):
                _audit("order_blocked", "blackout_window", symbol)
                raise BlackoutException(
                    f"{symbol} in earnings/macro blackout window — order rejected"
                )
        except BlackoutException:
            raise
        except Exception as exc:
            logger.warning("[safe_broker] blackout check failed, proceeding: %s", exc)

    def submit_order(self, symbol: str, qty: float, side: str) -> dict:
        self._check(symbol)
        return self._inner.submit_order(symbol, qty, side)

    def submit_bracket_order(self, symbol: str, qty: float, side: str,
                              stop_price: float, target_price: float,
                              limit_price=None) -> dict:
        self._check(symbol)
        return self._inner.submit_bracket_order(
            symbol, qty, side, stop_price, target_price, limit_price
        )

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def _audit(event: str, reason: str, symbol: str | None) -> None:
    try:
        from app.db.session import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            db.execute(text(
                "INSERT INTO trading_gate_audit (event, reason, symbol) VALUES (:e, :r, :s)"
            ), {"e": event, "r": reason, "s": symbol})
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("[safe_broker] audit insert failed: %s", exc)

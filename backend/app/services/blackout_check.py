"""Blackout window check — blocks orders near earnings and macro events.

Fail-open: any exception → return False (allow the order).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class BlackoutException(Exception):
    """Raised when an order is blocked by a blackout window."""


class BlackoutCheck:
    @staticmethod
    def is_blacked_out(symbol: str) -> bool:
        """True if symbol (or portfolio-wide NULL) is in an active blackout window.

        Fail-open: any exception returns False so a DB outage never blocks trading.
        """
        try:
            db = SessionLocal()
            try:
                from sqlalchemy import text
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                row = db.execute(text(
                    "SELECT id FROM trading_blackouts "
                    "WHERE blackout_start <= :now AND blackout_end >= :now "
                    "AND (symbol = :sym OR symbol IS NULL) "
                    "LIMIT 1"
                ), {"now": now, "sym": symbol}).fetchone()
                return row is not None
            finally:
                db.close()
        except Exception as exc:
            logger.warning("[blackout_check] check failed, defaulting to OPEN: %s", exc)
            return False

"""Records portfolio equity every 5 min during market hours.

Sums starting_capital_cents + realized P&L across all allocations.
Used by the drawdown circuit breaker to compute peak-to-trough drawdown.
"""
from __future__ import annotations

import logging

from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def record() -> None:
    db = SessionLocal()
    try:
        from sqlalchemy import text
        rows = db.execute(text(
            "SELECT a.starting_capital_cents, COALESCE(SUM(p.realized_cents), 0) "
            "FROM bot_allocations a "
            "LEFT JOIN bot_daily_pnl p ON p.allocation_id = a.id "
            "WHERE a.enabled = 1 "
            "GROUP BY a.id, a.starting_capital_cents"
        )).fetchall()

        if not rows:
            return

        total_starting = sum(r[0] or 0 for r in rows)
        total_realized = sum(r[1] or 0 for r in rows)
        equity_usd = (total_starting + total_realized) / 100.0

        db.execute(text(
            "INSERT INTO portfolio_equity_snapshots (equity_usd) VALUES (:eq)"
        ), {"eq": equity_usd})
        db.commit()
        logger.debug("[equity_snapshot] recorded equity_usd=%.2f", equity_usd)
    except Exception as exc:
        logger.warning("[equity_snapshot] failed: %s", exc)
    finally:
        db.close()

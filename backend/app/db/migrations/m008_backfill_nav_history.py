"""Migration m008: Backfill nav_history from bot_daily_pnl.

compute_nav was using bot_trades.pnl_cents (doesn't exist) so nav_history
stayed empty. This migration runs backfill_nav_history once on deploy, then
the fixed compute_and_store_nav will maintain it going forward.
Idempotent — UPSERT, safe to re-run.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def run(conn) -> None:
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        from app.jobs.compute_nav import backfill_nav_history
        written = backfill_nav_history(db)
        logger.warning("[m008] backfill_nav_history wrote %d rows", written)
    except Exception as exc:
        logger.warning("[m008] backfill_nav_history failed (non-fatal): %s", exc)
    finally:
        db.close()

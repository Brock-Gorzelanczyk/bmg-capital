"""Migration m018: bot_heartbeat table for scheduler heartbeat tracking.

Tracks the last time each bot produced a signal vs. last time it scanned,
plus the expected cadence so a watchdog cron can detect stalled bots and
fire an ops alert.

  expected_cadence_minutes:
    stocks during RTH  → 90  (every 90 min on the 5-min stock_day loop)
    crypto always-on   → 240 (4-hour cycles)

Idempotent: CREATE TABLE IF NOT EXISTS.
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


def run(conn) -> None:
    try:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS bot_heartbeat (
                    bot_name TEXT PRIMARY KEY,
                    last_signal_at DATETIME,
                    last_scan_at DATETIME,
                    expected_cadence_minutes INTEGER NOT NULL DEFAULT 90,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.commit()
        logger.info("[m018] bot_heartbeat table ensured")
    except Exception as exc:
        logger.warning("[m018] create failed (non-fatal): %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass

"""m047 — create bot_daily_journals table for the Phase 1 closed-loop learning system.

Stores one row per (allocation_id, journal_date) — the nightly 04:00 UTC
daily_journal job writes here; Phase 1b Mac-side sync will later read via
the /api/admin/strategy-journal endpoint and write vault .md files.

Idempotent: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.
No backfill — table starts empty; job populates from the first nightly run.
No date predicate in the migration body (avoids the m010 mass-quarantine trap).

Standing decisions honored:
  - NO writes to bot_trades, bot_positions, bot_allocations, bot_daily_pnl.
  - NO cascade delete on bot_allocations FK (rows are never deleted).
  - NO starting_capital_cents used for all-time % (only day-scoped working capital).
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def run(conn) -> dict:
    """Create bot_daily_journals table and indexes. Idempotent.

    Returns:
        {"executed": True, "table_created": bool, "indexes_created": int}
    """
    # Check if table already exists
    result = conn.execute(
        text(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='bot_daily_journals'"
        )
    )
    table_exists_before = bool(result.scalar())

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS bot_daily_journals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                allocation_id INTEGER NOT NULL REFERENCES bot_allocations(id),
                bot_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                journal_date DATE NOT NULL,
                sleeve TEXT,
                asset_class TEXT,
                starting_capital_cents INTEGER NOT NULL DEFAULT 0,
                ending_pv_cents INTEGER NOT NULL DEFAULT 0,
                day_pnl_cents INTEGER NOT NULL DEFAULT 0,
                day_return_pct REAL NOT NULL DEFAULT 0.0,
                trades_count INTEGER NOT NULL DEFAULT 0,
                winning_trades INTEGER NOT NULL DEFAULT 0,
                losing_trades INTEGER NOT NULL DEFAULT 0,
                win_rate REAL,
                avg_winner_cents INTEGER,
                avg_loser_cents INTEGER,
                profit_factor REAL,
                avg_hold_minutes REAL,
                max_concurrent_positions INTEGER NOT NULL DEFAULT 0,
                end_of_day_positions INTEGER NOT NULL DEFAULT 0,
                end_of_day_deployed_cents INTEGER NOT NULL DEFAULT 0,
                deployment_pct_avg REAL,
                regime_vix_band TEXT,
                regime_trend TEXT,
                regime_btc_dom_band TEXT,
                strategies_breakdown_json TEXT,
                errors_24h INTEGER NOT NULL DEFAULT 0,
                sentry_issues_json TEXT,
                body_md TEXT,
                frontmatter_yaml TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(allocation_id, journal_date)
            )
            """
        )
    )

    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_bot_daily_journals_bot_date "
            "ON bot_daily_journals(bot_id, journal_date DESC)"
        )
    )

    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_bot_daily_journals_user_date "
            "ON bot_daily_journals(user_id, journal_date DESC)"
        )
    )

    # Commit is required for CREATE TABLE to persist in SQLite autocommit mode
    conn.execute(text("SELECT 1"))  # no-op flush

    result2 = conn.execute(
        text(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='bot_daily_journals'"
        )
    )
    table_exists_after = bool(result2.scalar())

    table_created = not table_exists_before and table_exists_after

    logger.warning(
        "[m047] bot_daily_journals table_created=%s table_exists=%s",
        table_created,
        table_exists_after,
    )

    return {
        "executed": True,
        "table_created": table_created,
        "table_exists": table_exists_after,
    }

"""m048 -- create aqa_state + aqa_proposals tables for AQA Phase A.

aqa_state  — single-row config + per-day counters for the Autonomous Quant Agent.
aqa_proposals — one row per LLM proposal cycle; posted to Discord + reviewed by Brock.

Idempotent: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.
No DROP TABLE anywhere. No FK to bot_allocations (proposals reference bot_ids by string).
No date predicate trap (avoids the m010 mass-quarantine pattern from known-issues #8).

Standing decisions honored:
  - NO writes to bot_trades, bot_positions, bot_allocations, bot_daily_pnl.
  - NO writes to inception_capital_cents.
  - NO quarantine migration pattern.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def run(conn) -> dict:
    """Create aqa_state and aqa_proposals tables. Idempotent.

    Returns:
        {"executed": True, "table_created": bool, "table_exists": bool}
    """
    # --- Check pre-existence ------------------------------------------------
    result = conn.execute(
        text(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='aqa_state'"
        )
    )
    state_table_exists_before = bool(result.scalar())

    # --- Create aqa_state ---------------------------------------------------
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS aqa_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                frozen INTEGER NOT NULL DEFAULT 0,
                frozen_reason TEXT,
                frozen_at TIMESTAMP,
                frozen_by TEXT,
                deploys_today INTEGER NOT NULL DEFAULT 0,
                llm_calls_today INTEGER NOT NULL DEFAULT 0,
                counter_date DATE NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )

    # --- Seed single row (only if table was just created / still empty) -----
    count_result = conn.execute(text("SELECT COUNT(*) FROM aqa_state"))
    row_count = count_result.scalar()
    if row_count == 0:
        conn.execute(
            text(
                "INSERT INTO aqa_state (frozen, deploys_today, llm_calls_today, counter_date) "
                "VALUES (0, 0, 0, date('now'))"
            )
        )
        logger.warning("[m048] Seeded initial aqa_state row (counter_date = today UTC)")

    # --- Create aqa_proposals -----------------------------------------------
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS aqa_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_id TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                issue_tags TEXT NOT NULL,
                llm_response_md TEXT NOT NULL,
                context_summary TEXT NOT NULL,
                discord_message_id TEXT,
                posted_at TIMESTAMP,
                outcome TEXT
            )
            """
        )
    )

    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_aqa_proposals_created_at "
            "ON aqa_proposals(created_at DESC)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_aqa_proposals_cycle_id "
            "ON aqa_proposals(cycle_id)"
        )
    )

    # --- Verify ----------------------------------------------------------------
    conn.execute(text("SELECT 1"))  # no-op flush

    result2 = conn.execute(
        text(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='aqa_state'"
        )
    )
    state_table_exists_after = bool(result2.scalar())

    table_created = not state_table_exists_before and state_table_exists_after

    logger.warning(
        "[m048] aqa_state + aqa_proposals table_created=%s table_exists=%s",
        table_created,
        state_table_exists_after,
    )

    return {
        "executed": True,
        "table_created": table_created,
        "table_exists": state_table_exists_after,
    }

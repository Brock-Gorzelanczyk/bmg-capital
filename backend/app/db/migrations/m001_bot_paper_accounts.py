"""
Migration m001: Create bot_paper_accounts table.

Tracks the starting and current balance for each bot's dedicated paper
sub-account. One row per bot_id. Called from app/main.py lifespan on startup.

This file is the canonical source of the CREATE TABLE statement.
Only crypto_quant_aggressive's row is inserted here — other bots are NOT
backfilled (they run against the shared bot_allocations capital).
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m001_bot_paper_accounts_2026"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS bot_paper_accounts (
    bot_id                 VARCHAR(50) PRIMARY KEY,
    starting_balance_cents BIGINT NOT NULL,
    current_balance_cents  BIGINT NOT NULL,
    realized_pnl_cents     BIGINT DEFAULT 0,
    unrealized_pnl_cents   BIGINT DEFAULT 0,
    created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

INSERT_CQA_SQL = """
INSERT OR IGNORE INTO bot_paper_accounts
    (bot_id, starting_balance_cents, current_balance_cents,
     realized_pnl_cents, unrealized_pnl_cents)
VALUES
    ('crypto_quant_aggressive', 10000000, 10000000, 0, 0)
"""


def run(conn) -> None:
    """Create bot_paper_accounts and insert crypto_quant_aggressive row (idempotent).

    Uses schema_migrations as a claim token so the CREATE is only logged once,
    but CREATE TABLE IF NOT EXISTS is safe to call repeatedly.
    """
    try:
        conn.execute(text(CREATE_SQL))
        conn.commit()
        logger.info("[m001] bot_paper_accounts table ensured")
    except Exception as exc:
        logger.warning("[m001] CREATE TABLE failed (non-fatal): %s", exc)

    try:
        result = conn.execute(text(INSERT_CQA_SQL))
        conn.commit()
        if result.rowcount:
            logger.info(
                "[m001] crypto_quant_aggressive sub-account seeded: $100,000 paper"
            )
    except Exception as exc:
        logger.warning("[m001] INSERT crypto_quant_aggressive row failed (non-fatal): %s", exc)

"""Migration m005: Add options-specific columns to bot_positions and bot_trades.

Adds nullable columns so existing stock/crypto rows are unaffected.
Idempotent — uses ALTER TABLE … ADD COLUMN which is a no-op if the column exists
(SQLite silently ignores duplicate ADD COLUMN; PostgreSQL raises but we catch it).
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_OPTIONS_COLUMNS = {
    "bot_positions": [
        ("option_type",            "TEXT"),
        ("strike_price",           "REAL"),
        ("expiration_date",        "TEXT"),
        ("underlying_symbol",      "TEXT"),
        ("contract_count",         "INTEGER"),
        ("contract_premium_cents", "REAL"),
    ],
    "bot_trades": [
        ("option_type",            "TEXT"),
        ("strike_price",           "REAL"),
        ("expiration_date",        "TEXT"),
        ("underlying_symbol",      "TEXT"),
        ("contract_count",         "INTEGER"),
        ("contract_premium_cents", "REAL"),
    ],
}


def run(conn) -> None:
    added = 0
    for table, columns in _OPTIONS_COLUMNS.items():
        for col_name, col_type in columns:
            try:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                )
                conn.commit()
                added += 1
                logger.info("[m005] Added %s.%s (%s)", table, col_name, col_type)
            except Exception as exc:
                # Column already exists — expected on re-run
                _msg = str(exc).lower()
                if "duplicate" in _msg or "already exists" in _msg:
                    logger.debug("[m005] %s.%s already exists — skip", table, col_name)
                else:
                    logger.warning("[m005] ALTER TABLE %s ADD COLUMN %s failed: %s", table, col_name, exc)
                try:
                    conn.rollback()
                except Exception:
                    pass

    if added:
        logger.warning("[m005] Added %d options columns to bot_positions/bot_trades", added)
    else:
        logger.info("[m005] Options columns already present — no action needed")

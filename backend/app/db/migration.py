from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_TABLE_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "user_tiers": [
        ("billing_interval",       "VARCHAR"),
        ("trial_ends_at",          "DATETIME"),
        ("current_period_end",     "DATETIME"),
        ("stripe_customer_id",     "VARCHAR"),
        ("stripe_subscription_id", "VARCHAR"),
        ("stripe_sub_id",          "VARCHAR"),
        ("aum_override",           "VARCHAR"),
        ("aum_override_until",     "DATETIME"),
        ("cancel_at_period_end",   "BOOLEAN"),
        ("updated_at",             "DATETIME"),
    ],
    "paper_transactions": [
        ("notes", "VARCHAR"),
    ],
    "strategy_trades": [
        ("candidate_since",  "DATETIME"),
        ("entry_trigger",    "VARCHAR"),
        ("entry_notes",      "VARCHAR"),
        ("atr",              "FLOAT"),
        ("risk_dollars",     "FLOAT"),
        ("user_id",          "INTEGER"),
        ("last_known_price", "FLOAT"),
        ("prev_close",       "FLOAT"),
    ],
    "watchlists": [
        ("user_id", "INTEGER"),
    ],
    "portfolios": [
        ("user_id", "INTEGER"),
    ],
    "alert_configs": [
        ("user_id", "INTEGER"),
    ],
    "saved_screens": [
        ("user_id", "INTEGER"),
    ],
    "strategy_daily_log": [
        ("user_id", "INTEGER"),
    ],
    "strategy_equity_snapshots": [
        ("user_id", "INTEGER"),
    ],
}


def run_migrations(engine: Engine) -> None:
    """Add any missing columns to existing tables (safe no-op if already present)."""
    with engine.connect() as conn:
        for table_name, columns in _TABLE_MIGRATIONS.items():
            try:
                existing = {
                    row[1]
                    for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
                }
            except Exception:
                continue
            for col_name, col_type in columns:
                if col_name not in existing:
                    try:
                        conn.execute(
                            text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
                        )
                        conn.commit()
                        logger.info(f"Migration: added {table_name}.{col_name}")
                    except Exception as e:
                        logger.warning(f"Migration skipped {table_name}.{col_name}: {e}")

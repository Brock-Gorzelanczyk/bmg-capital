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
        ("candidate_since",    "DATETIME"),
        ("entry_trigger",      "VARCHAR"),
        ("entry_notes",        "VARCHAR"),
        ("atr",                "FLOAT"),
        ("risk_dollars",       "FLOAT"),
        ("user_id",            "INTEGER"),
        ("last_known_price",   "FLOAT"),
        ("prev_close",         "FLOAT"),
        ("paper_order_placed", "BOOLEAN"),
        ("paper_sell_placed",  "BOOLEAN"),
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


def _ensure_migration_log(conn) -> None:
    """Create the schema_migrations tracking table if it doesn't exist."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_name VARCHAR NOT NULL UNIQUE,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.commit()


def _migration_already_ran(conn, name: str) -> bool:
    """Return True if this migration has already been applied."""
    try:
        result = conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_name = :n"), {"n": name}
        ).fetchone()
        return result is not None
    except Exception:
        return False


def _record_migration(conn, name: str) -> None:
    """Record a migration as applied."""
    conn.execute(
        text("INSERT OR IGNORE INTO schema_migrations (migration_name) VALUES (:n)"), {"n": name}
    )
    conn.commit()


def run_migrations(engine: Engine) -> None:
    """Add any missing columns to existing tables (safe no-op if already present)."""
    with engine.connect() as conn:
        _ensure_migration_log(conn)

        for table_name, columns in _TABLE_MIGRATIONS.items():
            try:
                existing = {
                    row[1]
                    for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
                }
            except Exception:
                continue
            for col_name, col_type in columns:
                migration_name = f"{table_name}.{col_name}"
                if col_name not in existing and not _migration_already_ran(conn, migration_name):
                    try:
                        conn.execute(
                            text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
                        )
                        conn.commit()
                        _record_migration(conn, migration_name)
                        logger.info(f"Migration: added {table_name}.{col_name}")
                    except Exception as e:
                        logger.warning(f"Migration skipped {table_name}.{col_name}: {e}", exc_info=True)
                elif col_name in existing and not _migration_already_ran(conn, migration_name):
                    # Column already exists but wasn't tracked — record it now
                    _record_migration(conn, migration_name)

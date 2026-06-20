"""m013 — Fix smart_money_congress.id: BigInteger → INTEGER for SQLite auto-increment.

SQLite only auto-increments a PRIMARY KEY declared as INTEGER (the exact word).
BigInteger maps to BIGINT which does NOT alias the rowid → every INSERT without
an explicit id value raises "NOT NULL constraint failed: smart_money_congress.id".

The table has no real data (all inserts rolled back due to this same bug), so
we can safely drop and recreate it. Idempotent: if the table already has the
correct column type (INTEGER), we skip the recreation.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def run(conn) -> dict:
    # Check existing column type via PRAGMA
    try:
        rows = conn.execute(text("PRAGMA table_info(smart_money_congress)")).fetchall()
    except Exception:
        return {"skipped": True, "reason": "table does not exist"}

    col_map = {r[1]: r[2].upper() for r in rows}  # name → type
    id_type = col_map.get("id", "")

    if id_type == "INTEGER":
        logger.info("[m013] smart_money_congress.id is already INTEGER — no-op")
        return {"skipped": True, "reason": "already correct"}

    # Check row count — warn if data exists (shouldn't happen, but be safe)
    count = conn.execute(text("SELECT COUNT(*) FROM smart_money_congress")).scalar() or 0
    if count > 0:
        logger.warning("[m013] smart_money_congress has %d rows — skipping recreation to avoid data loss", count)
        return {"skipped": True, "reason": f"table has {count} rows — refusing to drop"}

    logger.info("[m013] id type is %r, recreating smart_money_congress with INTEGER PK", id_type)

    conn.execute(text("DROP TABLE smart_money_congress"))
    conn.execute(text("""
        CREATE TABLE smart_money_congress (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            member_name     VARCHAR(200) NOT NULL,
            party           VARCHAR(1),
            chamber         VARCHAR(1),
            state           VARCHAR(2),
            ticker          VARCHAR(20),
            asset_description TEXT,
            transaction_type  VARCHAR(20),
            amount_range    VARCHAR(50),
            amount_lower_cents BIGINT,
            amount_upper_cents BIGINT,
            transaction_date DATE NOT NULL,
            disclosure_date  DATE,
            source          VARCHAR(50),
            source_id       VARCHAR(200),
            fetched_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (source, source_id)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_smc_ticker "
        "ON smart_money_congress (ticker, transaction_date)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_smc_date "
        "ON smart_money_congress (transaction_date)"
    ))
    conn.commit()
    logger.info("[m013] smart_money_congress recreated with INTEGER PRIMARY KEY AUTOINCREMENT")
    return {"recreated": True}

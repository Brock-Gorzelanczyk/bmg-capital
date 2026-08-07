"""m096 — Add realized-P&L columns to bot_trades.

Per approved spec at vault/context/09-realized-pnl-rebuild-spec.md.

Adds two nullable columns to bot_trades so the C6 extension can populate
realized P&L per close-side trade, sourced from Alpaca order-pair FIFO:

  pnl_cents   INTEGER  — realized dollars in cents (signed)
  pnl_source  VARCHAR  — 'exact' | 'reconstructed' | NULL (for open-side rows)

Nullable so historical rows and open-side rows stay NULL — the NOT NULL
constraint on closing rows is deferred until Railway backups are
configured (issue #16). Once backups land, a follow-up migration ships:

    CHECK (side NOT IN ('sell','close','cover') OR pnl_cents IS NOT NULL)

Idempotent via IF NOT EXISTS + _gate.record().
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m096_add_realized_pnl_to_bot_trades_2026_08_06"


def _add_col_safely(conn, col_sql: str, col_name: str) -> None:
    try:
        conn.execute(text(f"ALTER TABLE bot_trades ADD COLUMN IF NOT EXISTS {col_sql}"))
    except Exception as exc:
        logger.warning("[m096] IF NOT EXISTS not supported (%s), using probe", exc)
        try:
            conn.execute(text(f"SELECT {col_name} FROM bot_trades LIMIT 1")).fetchone()
        except Exception:
            conn.execute(text(f"ALTER TABLE bot_trades ADD COLUMN {col_sql}"))


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    _add_col_safely(conn, "pnl_cents INTEGER", "pnl_cents")
    _add_col_safely(conn, "pnl_source VARCHAR(20)", "pnl_source")

    if hasattr(conn, "commit"):
        conn.commit()

    logger.warning("[m096] added bot_trades.pnl_cents + pnl_source")
    record(conn, _MIGRATION_NAME)
    return {"executed": True}

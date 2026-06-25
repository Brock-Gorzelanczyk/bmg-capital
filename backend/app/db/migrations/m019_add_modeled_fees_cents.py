"""m019 — Add `modeled_fees_cents` column to bot_trades.

COMMIT 12 introduced friction modeling for NEW trades (slippage + commission
per asset class). Existing 12,000+ historical paper trades have fees_cents=0
because the modeler didn't exist when they fired. Brock's spec called for a
SEPARATE column so the backfill doesn't touch existing P&L:

  modeled_fees_cents  →  what friction WOULD have been if the V1 model had
                          existed at the time of the trade. Used for accurate
                          historical Sharpe / Sortino computations + an
                          informational "Net P&L after modeled friction"
                          line on bot detail.

  fees_cents          →  unchanged. Continues to be the source of truth for
                          realized_pnl_cents math in canonical.

Nullable so existing rows remain valid. Populated by POST /admin/friction/backfill.

Idempotent — skips if the column already exists.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() or []
    return any(r[1] == column for r in rows)


def _table_exists(conn, table: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() or []
    return bool(rows)


def run(conn) -> dict:
    added: list[str] = []

    if not _table_exists(conn, "bot_trades"):
        logger.info("[m019] bot_trades table missing — no-op")
        return {"added": added, "skipped_reason": "bot_trades table missing"}

    if _column_exists(conn, "bot_trades", "modeled_fees_cents"):
        logger.info("[m019] bot_trades.modeled_fees_cents already exists — no-op")
        return {"added": added}

    conn.execute(text(
        "ALTER TABLE bot_trades ADD COLUMN modeled_fees_cents INTEGER"
    ))
    conn.commit()
    added.append("bot_trades.modeled_fees_cents")
    logger.info("[m019] added bot_trades.modeled_fees_cents (nullable INTEGER)")
    return {"added": added}

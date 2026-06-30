"""m049 — add regime_vix / regime_trend / regime_btc_dom_band columns to bot_trades.

Creates a composite index on (allocation_id, regime_vix, regime_trend).
Fully idempotent: PRAGMA table_info check + CREATE INDEX IF NOT EXISTS.
No _gate.already_ran needed — schema changes self-protect.

Standing decisions honored:
  - ADDITIVE only: no DROP, no NOT NULL, no default value (NULL = pre-m049).
  - No writes to inception_capital_cents, bot_daily_pnl, or bot_allocations.
  - Width VARCHAR(16): longest values "UNKNOWN" (7) and "55-60" (5).
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_NEW_COLUMNS = ["regime_vix", "regime_trend", "regime_btc_dom_band"]


def run(conn) -> dict:
    """Add regime tagging columns to bot_trades and create composite index.

    Idempotent via PRAGMA table_info check + CREATE INDEX IF NOT EXISTS.
    Safe to run every boot.

    Returns:
        {
            "executed": True,
            "columns_added": [...],
            "columns_present_after": [...],
            "index_present": bool,
        }
    """
    # ── 1. Check which columns already exist ──────────────────────────────────
    existing = {
        r[1]
        for r in conn.execute(text("PRAGMA table_info(bot_trades)")).fetchall()
    }

    # ── 2. Add missing columns (no NOT NULL, no DEFAULT — NULL = pre-m049) ────
    columns_added = []
    for col in _NEW_COLUMNS:
        if col not in existing:
            conn.execute(
                text(f"ALTER TABLE bot_trades ADD COLUMN {col} VARCHAR(16)")
            )
            columns_added.append(col)
            logger.warning("[m049] Added column %s to bot_trades", col)

    # ── 3. Create composite index (idempotent) ────────────────────────────────
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_bot_trades_regime "
            "ON bot_trades(allocation_id, regime_vix, regime_trend)"
        )
    )

    # ── 4. Verify final state ─────────────────────────────────────────────────
    existing_after = {
        r[1]
        for r in conn.execute(text("PRAGMA table_info(bot_trades)")).fetchall()
    }
    columns_present_after = [c for c in _NEW_COLUMNS if c in existing_after]

    index_row = conn.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name='idx_bot_trades_regime'"
        )
    ).fetchone()
    index_present = index_row is not None

    logger.warning(
        "[m049] regime_tagging done — columns_added=%s columns_present=%s index_present=%s",
        columns_added,
        columns_present_after,
        index_present,
    )

    return {
        "executed": True,
        "columns_added": columns_added,
        "columns_present_after": columns_present_after,
        "index_present": index_present,
    }

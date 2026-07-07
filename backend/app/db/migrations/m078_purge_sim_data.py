"""m078 — Purge all sim-fallback trades + positions. Real Alpaca data only.

Per Brock 2026-07-07: "I want to verify the data in the app is real if
it is real we can keep it".

Deletes every bot_trades row without an alpaca_order_id (the silent
DB fallback the runner wrote whenever Alpaca rejected). Deletes every
bot_positions row that has NO alpaca-linked trade (the phantom
positions those trades created).

What survives:
  - bot_trades rows with alpaca_order_id NOT NULL (real Alpaca fills)
  - bot_positions rows that have at least one alpaca-linked trade

Fund invariant unchanged: bot_allocations.starting_capital_cents and
portfolio_rank_bots.starting_capital_cents are the source of truth
for fund size. Trade/position history is P&L data, not capital.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m078_purge_sim_data_2026_07_07"


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    # ── 1. Count before ──────────────────────────────────────────────────
    trades_total_row = conn.execute(text("SELECT COUNT(*) FROM bot_trades")).fetchone()
    trades_real_row = conn.execute(text(
        "SELECT COUNT(*) FROM bot_trades WHERE alpaca_order_id IS NOT NULL"
    )).fetchone()
    positions_total_row = conn.execute(text("SELECT COUNT(*) FROM bot_positions")).fetchone()
    trades_total = int(trades_total_row[0] or 0)
    trades_real = int(trades_real_row[0] or 0)
    positions_total = int(positions_total_row[0] or 0)

    logger.warning(
        "[m078] before: trades_total=%d trades_real=%d positions_total=%d",
        trades_total, trades_real, positions_total,
    )

    # ── 2. Delete sim positions FIRST (must go before trades because of
    #        the position_id FK on bot_trades) ────────────────────────────
    # A position is REAL if any of its trades has alpaca_order_id NOT NULL.
    pos_del = conn.execute(text("""
        DELETE FROM bot_positions
        WHERE id IN (
            SELECT p.id FROM bot_positions p
            WHERE NOT EXISTS (
                SELECT 1 FROM bot_trades t
                WHERE t.position_id = p.id
                  AND t.alpaca_order_id IS NOT NULL
            )
        )
    """))
    positions_deleted = pos_del.rowcount
    logger.warning("[m078] deleted sim positions: %d", positions_deleted)

    # ── 3. Delete sim trades (alpaca_order_id IS NULL) ──────────────────
    tr_del = conn.execute(text(
        "DELETE FROM bot_trades WHERE alpaca_order_id IS NULL"
    ))
    trades_deleted = tr_del.rowcount
    logger.warning("[m078] deleted sim trades: %d", trades_deleted)

    # ── 4. Also clear bot_signals older than 24h with no linked trade ──
    # These accumulate at massive rates and pollute the signals_24h count.
    # Keep last 24h so the dashboard signal-generation activity is intact.
    cutoff = (datetime.now(timezone.utc)).timestamp()
    from datetime import timedelta
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    sig_del = conn.execute(text("""
        DELETE FROM bot_signals
        WHERE ts < :cut
          AND id NOT IN (SELECT signal_id FROM bot_trades WHERE signal_id IS NOT NULL)
    """), {"cut": cutoff_iso})
    signals_deleted = sig_del.rowcount
    logger.warning("[m078] deleted historical unlinked signals: %d", signals_deleted)

    # ── 5. Recount ──────────────────────────────────────────────────────
    trades_after = conn.execute(text("SELECT COUNT(*) FROM bot_trades")).fetchone()[0]
    positions_after = conn.execute(text("SELECT COUNT(*) FROM bot_positions")).fetchone()[0]

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "trades_before": trades_total,
        "trades_deleted": trades_deleted,
        "trades_after": int(trades_after),
        "positions_before": positions_total,
        "positions_deleted": positions_deleted,
        "positions_after": int(positions_after),
        "signals_deleted": signals_deleted,
    }

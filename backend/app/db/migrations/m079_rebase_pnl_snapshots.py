"""m079 — Purge pre-m077 daily snapshots so all-time/MTD/WTD anchor at rebase.

After m077 rescaled the fund $1M → $97,340 to mirror Alpaca paper equity,
the historical bot_daily_pnl.portfolio_value_eod_cents rows still hold the
pre-rescale $1M-scale values. That makes the /strategy header show:

    ALL-TIME: -$903,107 (-90.311%)
    MONTHLY:  -$903,107 (-90.311%)
    WEEKLY:   -$903,107 (-90.311%)

which is the phantom rescale delta, NOT real trading losses.

Fix: delete all bot_daily_pnl rows dated before 2026-07-07 (the m077 rescale
date). Post-purge, _sum_eod_snapshot_on returns NULL for old anchors and the
canonical aggregator falls back to _FUND_INCEPTION_CENTS = $97,340 — which is
now the correct baseline.

Real trading history from 2026-07-07 forward is preserved.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m079_rebase_pnl_snapshots_2026_07_07"
_REBASE_DATE = "2026-07-07"


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    before_row = conn.execute(text(
        "SELECT COUNT(*) FROM bot_daily_pnl WHERE date < :cut"
    ), {"cut": _REBASE_DATE}).fetchone()
    before = int(before_row[0] or 0) if before_row else 0

    after_row = conn.execute(text(
        "SELECT COUNT(*) FROM bot_daily_pnl WHERE date >= :cut"
    ), {"cut": _REBASE_DATE}).fetchone()
    after = int(after_row[0] or 0) if after_row else 0

    del_result = conn.execute(text(
        "DELETE FROM bot_daily_pnl WHERE date < :cut"
    ), {"cut": _REBASE_DATE})
    deleted = del_result.rowcount

    logger.warning(
        "[m079] pre-rebase snapshots: had=%d deleted=%d kept=%d (>= %s)",
        before, deleted, after, _REBASE_DATE,
    )

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "rebase_date": _REBASE_DATE,
        "rows_deleted": deleted,
        "rows_kept": after,
    }

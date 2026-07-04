"""m060 — Close phantom option_type=NULL positions on options bots.

Root cause of options bots showing 0 trades in the last 3 days:
  scan_and_execute counts ALL non-closed positions toward position_cap.
  Both options bots have 30+ legacy positions with option_type=NULL
  (residue from before m033_close_options_bot_equity_violations). These
  aren't real options — they're stuck equity-style rows.

  options_income has 41 open positions on alloc_id=14 (cap=15) — every
  new signal hits [position-cap] full: 15/15 and gets skipped.

  options_directional has 49 open positions on alloc_id=15 (cap=15).

Fix: bulk close all option_type IS NULL positions on both bots. Keep
the real options positions (option_type IN 'put'/'call'/'iron condor'
etc.) untouched.

No env-var gate — this is a pure phantom cleanup, not a capital move.
Idempotent via the _gate.already_ran pattern.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m060_close_options_phantoms_2026_07"
_BOTS = ("options_income", "options_directional")


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    result = {}

    for bot_name in _BOTS:
        # Get allocation ids for this bot
        alloc_ids = [int(r[0]) for r in conn.execute(text(
            "SELECT a.id FROM bot_allocations a "
            "JOIN bot_profiles p ON p.id = a.profile_id "
            "WHERE p.name = :n"
        ), {"n": bot_name}).fetchall()]

        if not alloc_ids:
            result[bot_name] = {"error": "no allocations found"}
            continue

        # Count phantoms before
        phantom_count = 0
        for aid in alloc_ids:
            row = conn.execute(text(
                "SELECT COUNT(*) FROM bot_positions "
                "WHERE allocation_id = :aid "
                "  AND closed_at IS NULL "
                "  AND option_type IS NULL"
            ), {"aid": aid}).fetchone()
            phantom_count += int(row[0] or 0)

        # Close them
        closed = 0
        for aid in alloc_ids:
            r = conn.execute(text(
                "UPDATE bot_positions "
                "SET closed_at = :ts, "
                "    exit_reason = 'm060_phantom_cleanup' "
                "WHERE allocation_id = :aid "
                "  AND closed_at IS NULL "
                "  AND option_type IS NULL"
            ), {"ts": now_iso, "aid": aid})
            closed += r.rowcount or 0

        # Count remaining real options positions
        real_count = 0
        for aid in alloc_ids:
            row = conn.execute(text(
                "SELECT COUNT(*) FROM bot_positions "
                "WHERE allocation_id = :aid "
                "  AND closed_at IS NULL "
                "  AND option_type IS NOT NULL"
            ), {"aid": aid}).fetchone()
            real_count += int(row[0] or 0)

        result[bot_name] = {
            "phantoms_closed": closed,
            "real_options_remaining": real_count,
            "alloc_ids": alloc_ids,
        }
        logger.warning(
            "[m060] %s: closed %d phantom NULL-option positions, %d real options remain",
            bot_name, closed, real_count,
        )

    record(conn, _MIGRATION_NAME)
    return {"executed": True, "per_bot": result}

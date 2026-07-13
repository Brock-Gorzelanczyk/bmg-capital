"""m094 — Backfill NULL exit_reason on closed bot_positions.

RIA-stats spec (2026-07-13): every closed position must have a canonical
exit_reason. Currently some historical rows have closed_at IS NOT NULL
but exit_reason IS NULL. Backfill those with 'manual' (safe default —
option_close_sync will fill real reasons going forward).

Also canonicalize any legacy verbose reasons to the enum bucket:
  hold_max_hours_force_exit → manual
  drawdown_circuit_breaker  → stop
  stop_loss / trailing_stop → stop
  target_hit                → take_profit
  time_stop                 → expiry

Idempotent via _gate.record().
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m094_backfill_exit_reasons_2026_07_13"

# Canonical enum: {take_profit, stop, expiry, assignment, roll, manual}
_LEGACY_TO_CANONICAL = [
    ("hold_max_hours_force_exit", "manual"),
    ("hold_max_hours", "manual"),
    ("drawdown_circuit_breaker", "stop"),
    ("stop_loss", "stop"),
    ("trailing_stop", "stop"),
    ("target_hit", "take_profit"),
    ("time_stop", "expiry"),
    ("reversed", "manual"),
]


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    actions: list[dict] = []

    # 1. Fill NULL reasons on closed positions
    r1 = conn.execute(text(
        "UPDATE bot_positions SET exit_reason = 'manual' "
        "WHERE closed_at IS NOT NULL AND exit_reason IS NULL"
    ))
    actions.append({"step": "null_reason_backfill", "rowcount": r1.rowcount})

    # 2. Canonicalize legacy verbose reasons
    for legacy, canonical in _LEGACY_TO_CANONICAL:
        r = conn.execute(text(
            "UPDATE bot_positions SET exit_reason = :c "
            "WHERE closed_at IS NOT NULL AND exit_reason = :l"
        ), {"c": canonical, "l": legacy})
        if r.rowcount:
            actions.append({
                "step": "canonicalize", "legacy": legacy,
                "canonical": canonical, "rowcount": r.rowcount,
            })

    if hasattr(conn, "commit"):
        conn.commit()

    logger.warning("[m094] backfill exit_reason: %s", actions)
    record(conn, _MIGRATION_NAME)
    return {"executed": True, "actions": actions}

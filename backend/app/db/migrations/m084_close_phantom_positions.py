"""m084 — Close 10 phantom bot_positions surfaced by 2026-07-09 audit.

Root cause: broker reconciliation flagged 10 open bot_positions rows for
user_id=1 where Alpaca has no matching position. These are stale DB rows
from pre-mleg / pre-real-only-mode eras where entry fills wrote to DB but
the corresponding broker position was rejected, cancelled, or closed at
the broker without a matching close-fill making it back into bot_trades.

Total phantom exposure: ~$4,000 across 8 stocks + 2 near-worthless
options. Real money impact: zero (broker has no leg). Impact on BMG:
overstates open-position count and skews sleeve deployment displays.

Symbols (all user_id=1, all closed_at IS NULL as of 2026-07-09 20:00 UTC):
  Stocks (~$4,000): COST, GOOGL, MARA, NFLX, NVDA, ORCL, SOFI, TSLA
  Options (~$2 worthless): IBIT260821C00036000, XLV260821P00149000

Predicate includes opened_at cutoff so any legitimate NEW positions on
the same symbol (opened after audit time) are not swept. Per
known-issues #8 — cleanup migrations MUST have date predicates.

Idempotent via _gate.record().
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m084_close_phantom_positions_2026_07_09"

_PHANTOM_SYMBOLS = [
    "COST", "GOOGL", "MARA", "NFLX", "NVDA", "ORCL", "SOFI", "TSLA",
    "IBIT260821C00036000", "XLV260821P00149000",
]

_AUDIT_CUTOFF = "2026-07-09T20:00:00+00:00"


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()

    rows = conn.execute(text("""
        SELECT bp.id, bp.symbol, bp.qty, bp.avg_cost_cents,
               bp.opened_at, p.name AS bot_name
          FROM bot_positions bp
          JOIN bot_allocations ba ON ba.id = bp.allocation_id
          JOIN bot_profiles p ON p.id = ba.profile_id
         WHERE ba.user_id = 1
           AND bp.closed_at IS NULL
           AND bp.quarantined_at IS NULL
           AND bp.opened_at < :cutoff
           AND bp.symbol IN :syms
    """).bindparams(
        __import__("sqlalchemy").bindparam("syms", expanding=True)
    ), {"cutoff": _AUDIT_CUTOFF, "syms": _PHANTOM_SYMBOLS}).fetchall()

    closed_ids: list[int] = []
    closed_detail: list[dict] = []
    for r in rows:
        pos_id = int(r[0])
        conn.execute(text(
            "UPDATE bot_positions SET closed_at = :ts, "
            "quarantine_reason = COALESCE(quarantine_reason, :r) "
            "WHERE id = :pid"
        ), {"ts": now_iso, "r": "phantom_broker_diff_2026_07_09", "pid": pos_id})
        closed_ids.append(pos_id)
        closed_detail.append({
            "position_id": pos_id,
            "bot": r[5],
            "symbol": r[1],
            "qty": float(r[2] or 0),
            "avg_cost_cents": int(r[3] or 0),
        })

    if hasattr(conn, "commit"):
        conn.commit()

    verify = conn.execute(text(
        "SELECT COUNT(*) FROM bot_positions bp "
        "JOIN bot_allocations ba ON ba.id = bp.allocation_id "
        "WHERE ba.user_id = 1 AND bp.closed_at IS NULL "
        "AND bp.opened_at < :cutoff "
        "AND bp.symbol IN :syms"
    ).bindparams(
        __import__("sqlalchemy").bindparam("syms", expanding=True)
    ), {"cutoff": _AUDIT_CUTOFF, "syms": _PHANTOM_SYMBOLS}).fetchone()
    remaining = int(verify[0] or 0) if verify else -1

    if remaining != 0:
        logger.error(
            "[m084] verify failed: %d phantom positions still open — NOT recording",
            remaining,
        )
        return {
            "executed": False,
            "error": "verify_failed",
            "closed_ids": closed_ids,
            "remaining_open": remaining,
        }

    logger.warning(
        "[m084] closed %d phantom bot_positions for user_id=1: %s",
        len(closed_ids), closed_detail,
    )
    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "closed_count": len(closed_ids),
        "closed_ids": closed_ids,
        "closed_detail": closed_detail,
    }

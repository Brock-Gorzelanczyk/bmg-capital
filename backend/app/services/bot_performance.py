"""Bot performance service — single source of truth for all-time % return.

SHIP 3: replaces the broken (portfolio_value - inception) / inception formula
with SUM(realized_cents) / inception_capital_cents so capital resets do not
silently re-zero historical track records.

Numerator: SUM(bot_daily_pnl.realized_cents) WHERE allocation_id = :aid
           AND (note IS NULL OR note != 'track_reset_marker')
Denominator: bot_allocations.inception_capital_cents
             (fallback: starting_capital_cents if inception NULL/0)

Standing decision (2026-06-28): inception_capital_cents is immutable.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TRACK_RESET_MARKER_NOTE = "track_reset_marker"


def get_all_time_pct(allocation_id: int, db: Session) -> float:
    """All-time % return using sum(realized) / inception_capital_cents.

    Numerator: SUM(bot_daily_pnl.realized_cents) WHERE allocation_id = :aid
               AND note IS NOT 'track_reset_marker'  (exclude marker rows)
    Denominator: bot_allocations.inception_capital_cents
                 (fallback to starting_capital_cents if inception NULL/0)
    Returns 0.0 when:
      - allocation not found
      - inception (and starting) both 0 or NULL
      - no bot_daily_pnl rows for this allocation
    Result rounded to 2 decimals.
    """
    try:
        row = db.execute(
            text(
                "SELECT inception_capital_cents, starting_capital_cents "
                "FROM bot_allocations WHERE id = :aid"
            ),
            {"aid": allocation_id},
        ).fetchone()
        if row is None:
            return 0.0

        inception = int(row[0] or 0) if row[0] else 0
        starting = int(row[1] or 0) if row[1] else 0
        denom = inception or starting
        if not denom:
            return 0.0

        pnl_row = db.execute(
            text(
                "SELECT COALESCE(SUM(realized_cents), 0) "
                "FROM bot_daily_pnl "
                "WHERE allocation_id = :aid "
                "  AND (note IS NULL OR note != :marker)"
            ),
            {"aid": allocation_id, "marker": TRACK_RESET_MARKER_NOTE},
        ).fetchone()
        sum_realized = int(pnl_row[0] or 0)

        return round(sum_realized / denom * 100, 2)

    except Exception as exc:
        logger.warning("[bot_performance] get_all_time_pct alloc=%d error: %s", allocation_id, exc)
        return 0.0


def get_all_time_pct_with_meta(allocation_id: int, db: Session) -> dict:
    """Same as get_all_time_pct but returns metadata for UI tooltips.

    Returns:
        {"pct": float,
         "is_post_reset": bool,       True when only track_reset marker rows exist
         "first_pnl_date": str | None,  ISO date of earliest non-marker row
         "reset_date": str | None,    ISO date of the marker row, if any
         "sum_realized_cents": int,
         "inception_capital_cents": int}
    """
    try:
        row = db.execute(
            text(
                "SELECT inception_capital_cents, starting_capital_cents "
                "FROM bot_allocations WHERE id = :aid"
            ),
            {"aid": allocation_id},
        ).fetchone()
        if row is None:
            return {
                "pct": 0.0,
                "is_post_reset": False,
                "first_pnl_date": None,
                "reset_date": None,
                "sum_realized_cents": 0,
                "inception_capital_cents": 0,
            }

        inception = int(row[0] or 0) if row[0] else 0
        starting = int(row[1] or 0) if row[1] else 0
        denom = inception or starting

        # Non-marker rows
        pnl_row = db.execute(
            text(
                "SELECT COALESCE(SUM(realized_cents), 0), MIN(date) "
                "FROM bot_daily_pnl "
                "WHERE allocation_id = :aid "
                "  AND (note IS NULL OR note != :marker)"
            ),
            {"aid": allocation_id, "marker": TRACK_RESET_MARKER_NOTE},
        ).fetchone()
        sum_realized = int(pnl_row[0] or 0)
        first_pnl_date_raw = pnl_row[1]
        first_pnl_date = str(first_pnl_date_raw) if first_pnl_date_raw else None

        # Marker row (if any)
        marker_row = db.execute(
            text(
                "SELECT date FROM bot_daily_pnl "
                "WHERE allocation_id = :aid AND note = :marker "
                "ORDER BY date ASC LIMIT 1"
            ),
            {"aid": allocation_id, "marker": TRACK_RESET_MARKER_NOTE},
        ).fetchone()
        reset_date = str(marker_row[0]) if marker_row else None

        # is_post_reset: True when we have a marker AND no non-marker rows
        #   (or only rows from on/after the reset date)
        has_real_pnl_rows = first_pnl_date is not None
        is_post_reset = (reset_date is not None) and (not has_real_pnl_rows)

        pct = round(sum_realized / denom * 100, 2) if denom else 0.0

        return {
            "pct": pct,
            "is_post_reset": is_post_reset,
            "first_pnl_date": first_pnl_date,
            "reset_date": reset_date,
            "sum_realized_cents": sum_realized,
            "inception_capital_cents": inception,
        }

    except Exception as exc:
        logger.warning(
            "[bot_performance] get_all_time_pct_with_meta alloc=%d error: %s",
            allocation_id, exc,
        )
        return {
            "pct": 0.0,
            "is_post_reset": False,
            "first_pnl_date": None,
            "reset_date": None,
            "sum_realized_cents": 0,
            "inception_capital_cents": 0,
        }

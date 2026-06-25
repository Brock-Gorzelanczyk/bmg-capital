"""
C8 — Daily NAV Calculation.

Runs at 4:30 PM ET on weekdays. Computes total portfolio NAV from:
  - Sum of realized P&L from bot_daily_pnl (correct source; bot_trades has no pnl column)
  - Sum of unrealized P&L from open positions (mark = avg_cost * qty, no live price)
  - Starting capital baseline from bot_allocations.starting_capital_cents

Stored in nav_history table, one row per date. Idempotent: UPSERT so
re-runs don't create duplicate rows.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

logger = logging.getLogger(__name__)

# ── $5K reclassification halt guard ──────────────────────────────────────────
# If a recompute would move today's stored NAV by more than $5K, halt the
# overwrite and alert ops. Protects against a quarantine wave or asset_class
# reclassification silently flipping the headline at midnight. Override via
# POST /api/admin/reconciliation/force-complete with a reason (admin-only).
HALT_GUARD_THRESHOLD_CENTS = 500_000  # $5,000

_FORCE_COMPLETE_REASONS: list[dict] = []  # in-process audit log of overrides


def _ensure_nav_history_table(db: Session) -> None:
    try:
        db.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS nav_history (
                date        TEXT PRIMARY KEY,
                nav_cents   INTEGER NOT NULL,
                pct_change  REAL,
                computed_at TEXT NOT NULL
            )
        """))
        db.commit()
    except Exception as exc:
        logger.debug("[compute_nav] table ensure failed: %s", exc)


def compute_and_store_nav(db: Session, *, force: bool = False, force_reason: Optional[str] = None) -> dict:
    """
    Compute today's NAV and persist to nav_history.
    Returns {"date", "nav_cents", "pct_change"} or {..., "halted": True, ...}.

    Halt guard: if |new_nav - existing_nav_for_today| > $5K and force=False,
    abort the write, alert ops, return halted=True. Existing row stays put.
    Operator reviews the diff in ops channel; can re-run with force=True via
    POST /api/admin/reconciliation/force-complete + a reason.
    """
    _ensure_nav_history_table(db)
    today = date.today().isoformat()
    now   = datetime.now(timezone.utc).isoformat()

    try:
        # Starting capital: sum across all paper allocations
        starting_cents = db.execute(sql_text("""
            SELECT COALESCE(SUM(starting_capital_cents), 0)
            FROM bot_allocations
            WHERE paper_mode = 1
        """)).scalar() or 0

        # All-time realized P&L from bot_daily_pnl (bot_trades has no pnl_cents column)
        realized_cents = db.execute(sql_text("""
            SELECT COALESCE(SUM(bdp.realized_cents), 0)
            FROM bot_daily_pnl bdp
            JOIN bot_allocations ba ON ba.id = bdp.allocation_id
            WHERE ba.paper_mode = 1
        """)).scalar() or 0

        # Unrealized from open positions: mark = avg_cost_cents * qty
        open_rows = db.execute(sql_text("""
            SELECT bp.avg_cost_cents, bp.qty
            FROM bot_positions bp
            JOIN bot_allocations ba ON ba.id = bp.allocation_id
            WHERE bp.closed_at IS NULL
              AND bp.quarantined_at IS NULL
              AND bp.avg_cost_cents IS NOT NULL
              AND bp.qty IS NOT NULL
              AND ba.paper_mode = 1
        """)).fetchall()
        unrealized_cents = int(sum((r[0] or 0) * (r[1] or 0) for r in open_rows))

        nav_cents = starting_cents + realized_cents + unrealized_cents

        prev_row = db.execute(sql_text("""
            SELECT nav_cents FROM nav_history
            WHERE date < :today
            ORDER BY date DESC
            LIMIT 1
        """), {"today": today}).fetchone()
        pct_change = None
        if prev_row and prev_row[0]:
            prev_nav = prev_row[0]
            pct_change = round((nav_cents - prev_nav) / prev_nav * 100, 4) if prev_nav != 0 else 0.0

        # ── HALT GUARD ─────────────────────────────────────────────────
        existing_today = db.execute(sql_text(
            "SELECT nav_cents FROM nav_history WHERE date = :today"
        ), {"today": today}).fetchone()
        if existing_today and existing_today[0] is not None and not force:
            swing_cents = abs(nav_cents - existing_today[0])
            if swing_cents > HALT_GUARD_THRESHOLD_CENTS:
                try:
                    from app.services.discord import send_ops_alert
                    send_ops_alert(
                        title="[EOD HALT] NAV recompute swing > $5K",
                        message=(
                            f"compute_and_store_nav refused to overwrite today's NAV.\n"
                            f"Existing nav: ${existing_today[0]/100:,.2f}\n"
                            f"New recompute: ${nav_cents/100:,.2f}\n"
                            f"Swing: ${swing_cents/100:,.2f} (threshold $5,000)\n"
                            f"Date: {today}\n"
                            f"Override: POST /api/admin/reconciliation/force-complete "
                            f"with a reason."
                        ),
                        severity="critical",
                        source="compute_nav.halt_guard",
                        fields=[
                            {"name": "Existing (¢)", "value": str(existing_today[0]), "inline": True},
                            {"name": "New (¢)",      "value": str(nav_cents),         "inline": True},
                            {"name": "Swing (¢)",    "value": str(swing_cents),       "inline": True},
                        ],
                    )
                except Exception as alert_exc:
                    logger.error("[compute_nav] ops alert failed: %s", alert_exc)
                logger.error(
                    "[compute_nav HALT] swing $%d > $5K threshold; existing=$%d new=$%d date=%s",
                    swing_cents, existing_today[0], nav_cents, today,
                )
                return {
                    "date": today,
                    "nav_cents": existing_today[0],
                    "pct_change": pct_change,
                    "halted": True,
                    "swing_cents": swing_cents,
                    "new_nav_cents": nav_cents,
                }

        db.execute(sql_text("""
            INSERT INTO nav_history (date, nav_cents, pct_change, computed_at)
            VALUES (:date, :nav, :pct, :ts)
            ON CONFLICT(date) DO UPDATE SET
                nav_cents   = excluded.nav_cents,
                pct_change  = excluded.pct_change,
                computed_at = excluded.computed_at
        """), {"date": today, "nav": nav_cents, "pct": pct_change, "ts": now})
        db.commit()

        if force:
            _FORCE_COMPLETE_REASONS.append({
                "date": today, "ts": now,
                "reason": force_reason or "(none)",
                "nav_cents": nav_cents,
            })
            try:
                from app.services.discord import send_ops_alert
                send_ops_alert(
                    title="[EOD] force-complete override accepted",
                    message=(
                        f"compute_and_store_nav written with force=True.\n"
                        f"Reason: {force_reason or '(none)'}\nNew nav: ${nav_cents/100:,.2f}"
                    ),
                    severity="warn",
                    source="compute_nav.force_complete",
                )
            except Exception:
                pass

        logger.warning(
            "[compute_nav] date=%s nav=$%.0f pct_change=%s realized=$%.0f unrealized=$%.0f",
            today, nav_cents / 100,
            f"{pct_change:+.4f}%" if pct_change is not None else "N/A",
            realized_cents / 100, unrealized_cents / 100,
        )
        return {"date": today, "nav_cents": nav_cents, "pct_change": pct_change}

    except Exception as exc:
        logger.error("[compute_nav] failed: %s", exc, exc_info=True)
        return {"date": today, "nav_cents": 0, "pct_change": None, "error": str(exc)}


def backfill_nav_history(db: Session) -> int:
    """
    Populate nav_history for all dates present in bot_daily_pnl.
    Idempotent — uses UPSERT. Returns number of rows written.
    """
    _ensure_nav_history_table(db)
    now = datetime.now(timezone.utc).isoformat()

    # Starting capital: sum across paper allocations
    starting_cents = db.execute(sql_text("""
        SELECT COALESCE(SUM(starting_capital_cents), 0)
        FROM bot_allocations WHERE paper_mode = 1
    """)).scalar() or 0

    # Per-date realized P&L across all paper allocations
    daily_rows = db.execute(sql_text("""
        SELECT bdp.date,
               COALESCE(SUM(bdp.realized_cents), 0) AS realized
          FROM bot_daily_pnl bdp
          JOIN bot_allocations ba ON ba.id = bdp.allocation_id
         WHERE ba.paper_mode = 1
         GROUP BY bdp.date
         ORDER BY bdp.date ASC
    """)).fetchall()

    if not daily_rows:
        logger.warning("[compute_nav] backfill: no bot_daily_pnl rows found")
        return 0

    written = 0
    cumulative_realized = 0
    prev_nav = None

    for row in daily_rows:
        d, realized = str(row[0]), int(row[1] or 0)
        cumulative_realized += realized
        nav_cents = starting_cents + cumulative_realized

        pct_change = None
        if prev_nav:
            pct_change = round((nav_cents - prev_nav) / prev_nav * 100, 4) if prev_nav != 0 else 0.0

        db.execute(sql_text("""
            INSERT INTO nav_history (date, nav_cents, pct_change, computed_at)
            VALUES (:date, :nav, :pct, :ts)
            ON CONFLICT(date) DO UPDATE SET
                nav_cents   = excluded.nav_cents,
                pct_change  = excluded.pct_change,
                computed_at = excluded.computed_at
        """), {"date": d, "nav": nav_cents, "pct": pct_change, "ts": now})
        prev_nav = nav_cents
        written += 1

    db.commit()
    logger.warning("[compute_nav] backfill wrote %d rows to nav_history", written)
    return written


def get_nav_history(db: Session, days: int = 30) -> list[dict]:
    """Fetch last N days of NAV for chart endpoint."""
    _ensure_nav_history_table(db)
    try:
        rows = db.execute(sql_text("""
            SELECT date, nav_cents, pct_change
            FROM nav_history
            ORDER BY date DESC
            LIMIT :n
        """), {"n": days}).fetchall()
        return [
            {"date": r[0], "nav_cents": r[1], "pct_change": r[2]}
            for r in reversed(rows)
        ]
    except Exception as exc:
        logger.warning("[compute_nav] get_nav_history failed: %s", exc)
        return []

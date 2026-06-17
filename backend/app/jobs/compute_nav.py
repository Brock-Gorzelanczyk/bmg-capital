"""
C8 — Daily NAV Calculation.

Runs at 4:30 PM ET on weekdays. Computes total portfolio NAV from:
  - Sum of realized P&L from all closed trades (BotTrade.pnl_cents)
  - Sum of unrealized P&L from open positions (mark = avg_cost * qty, no live price)
  - Starting capital baseline from strategy_portfolios

Stored in nav_history table, one row per date. Idempotent: UPSERT so
re-runs don't create duplicate rows.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text, func

logger = logging.getLogger(__name__)


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


def compute_and_store_nav(db: Session) -> dict:
    """
    Compute today's NAV and persist to nav_history.
    Returns {"date", "nav_cents", "pct_change"}.
    """
    _ensure_nav_history_table(db)
    today = date.today().isoformat()
    now   = datetime.now(timezone.utc).isoformat()

    try:
        from app.db.models.bots import BotTrade, BotPosition, BotAllocation

        # Starting capital across all portfolios
        starting_cents = db.execute(sql_text(
            "SELECT COALESCE(SUM(starting_capital_cents), 0) FROM strategy_portfolios"
        )).scalar() or 0

        # All-time realized P&L from closed trades (non-quarantined)
        realized_cents = db.execute(sql_text("""
            SELECT COALESCE(SUM(pnl_cents), 0)
            FROM bot_trades
            WHERE pnl_cents IS NOT NULL
              AND quarantined_at IS NULL
        """)).scalar() or 0

        # Unrealized P&L from open positions
        # Mark = avg_cost_cents * qty (no live price lookup to keep it offline-safe)
        open_rows = db.execute(sql_text("""
            SELECT avg_cost_cents, qty
            FROM bot_positions
            WHERE closed_at IS NULL
              AND quarantined_at IS NULL
              AND avg_cost_cents IS NOT NULL
              AND qty IS NOT NULL
        """)).fetchall()
        unrealized_cents = int(sum((r[0] or 0) * (r[1] or 0) for r in open_rows))

        nav_cents = starting_cents + realized_cents + unrealized_cents

        # Compute pct_change vs previous day
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

        db.execute(sql_text("""
            INSERT INTO nav_history (date, nav_cents, pct_change, computed_at)
            VALUES (:date, :nav, :pct, :ts)
            ON CONFLICT(date) DO UPDATE SET
                nav_cents   = excluded.nav_cents,
                pct_change  = excluded.pct_change,
                computed_at = excluded.computed_at
        """), {"date": today, "nav": nav_cents, "pct": pct_change, "ts": now})
        db.commit()

        logger.warning(
            "[compute_nav] date=%s nav=$%.0f pct_change=%s",
            today, nav_cents / 100, f"{pct_change:+.4f}%" if pct_change is not None else "N/A",
        )
        return {"date": today, "nav_cents": nav_cents, "pct_change": pct_change}

    except Exception as exc:
        logger.error("[compute_nav] failed: %s", exc, exc_info=True)
        return {"date": today, "nav_cents": 0, "pct_change": None, "error": str(exc)}


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
        # Return chronological order for chart rendering
        return [
            {"date": r[0], "nav_cents": r[1], "pct_change": r[2]}
            for r in reversed(rows)
        ]
    except Exception as exc:
        logger.warning("[compute_nav] get_nav_history failed: %s", exc)
        return []

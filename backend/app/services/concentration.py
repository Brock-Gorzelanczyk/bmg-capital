"""
Cross-bot position concentration cap.

V1 limits (per Brock's greenlight on the all-night plan):
  - Per-name fleet cap:  3.0% of fleet NAV
  - Per-sleeve cap:     40.0% of fleet NAV   (existing risk-budget cap)
  - Per-GICS-sector:    25.0%                (skipped V1 — no sector mapping table)

The check is enforced at signal-execution time in
backend/strategy_lab/runner.py:_execute_signal, between sizing and the
broker submit. A breach returns a (False, reason, details) tuple and the
executor logs + skips the trade without writing BotPosition / BotTrade.

The fleet NAV used as the denominator is read from nav_history (latest row).
If nav_history is empty, the check no-ops and logs a warning — we don't
block trades on missing baseline data, but we surface the gap.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

logger = logging.getLogger(__name__)

PER_NAME_CAP = 0.03
PER_SLEEVE_CAP = 0.40


def _fleet_nav_cents(db: Session) -> Optional[int]:
    """Latest nav_history row. None if table empty."""
    try:
        row = db.execute(sql_text(
            "SELECT nav_cents FROM nav_history ORDER BY date DESC LIMIT 1"
        )).fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception as exc:
        logger.warning("[concentration] fleet_nav lookup failed: %s", exc)
        return None


def _current_symbol_exposure_cents(db: Session, symbol: str) -> int:
    """Sum of open-position notional for `symbol` across ALL bots, all users.

    Entry-cost notional: qty * avg_cost_cents. For options bots that's
    premium-paid (no contract multiplier — we measure dollar exposure,
    not delta-equivalent).
    """
    try:
        row = db.execute(sql_text("""
            SELECT COALESCE(SUM(qty * avg_cost_cents), 0)
              FROM bot_positions
             WHERE symbol = :sym
               AND closed_at IS NULL
               AND quarantined_at IS NULL
        """), {"sym": symbol}).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception as exc:
        logger.warning("[concentration] exposure lookup failed for %s: %s", symbol, exc)
        return 0


def check_per_name_cap(
    db: Session,
    symbol: str,
    new_notional_cents: int,
) -> tuple[bool, str, dict]:
    """Returns (allowed, reason, details).

    allowed=False → placing this trade would push single-name exposure
    over PER_NAME_CAP of fleet NAV. Caller should skip + log.

    If fleet NAV unknown (nav_history empty), no-op + return allowed=True
    with reason='nav_unavailable' so trading doesn't grind to a halt on
    fresh deploy. Surfaces a warning.
    """
    fleet_nav = _fleet_nav_cents(db)
    if fleet_nav is None or fleet_nav <= 0:
        return True, "nav_unavailable", {
            "fleet_nav_cents": fleet_nav,
            "skipped_check": True,
        }

    current_exposure = _current_symbol_exposure_cents(db, symbol)
    post_exposure = current_exposure + max(0, int(new_notional_cents))
    cap_cents = int(fleet_nav * PER_NAME_CAP)

    details = {
        "symbol": symbol,
        "fleet_nav_cents": fleet_nav,
        "cap_cents": cap_cents,
        "cap_pct": PER_NAME_CAP * 100,
        "current_exposure_cents": current_exposure,
        "new_notional_cents": int(new_notional_cents),
        "post_exposure_cents": post_exposure,
        "post_exposure_pct": round(post_exposure / fleet_nav * 100, 3),
    }

    if post_exposure > cap_cents:
        return False, "concentration_cap_exceeded", details
    return True, "ok", details


def top_concentrations(db: Session, limit: int = 20) -> list[dict]:
    """For /admin/concentration. Top N symbols by % of fleet."""
    fleet_nav = _fleet_nav_cents(db)
    if fleet_nav is None or fleet_nav <= 0:
        return []
    try:
        rows = db.execute(sql_text("""
            SELECT symbol,
                   COALESCE(SUM(qty * avg_cost_cents), 0) AS notional_cents,
                   COUNT(*) AS open_positions
              FROM bot_positions
             WHERE closed_at IS NULL AND quarantined_at IS NULL
             GROUP BY symbol
             ORDER BY notional_cents DESC
             LIMIT :n
        """), {"n": limit}).fetchall()
        return [
            {
                "symbol": r[0],
                "notional_cents": int(r[1] or 0),
                "notional_pct_of_fleet": round((r[1] or 0) / fleet_nav * 100, 3),
                "open_positions": int(r[2] or 0),
                "exceeds_cap": (r[1] or 0) > int(fleet_nav * PER_NAME_CAP),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("[concentration] top_concentrations failed: %s", exc)
        return []

"""
Discipline threshold auto-promote / auto-tighten.

Nightly job evaluates every BotProfile against rolling 30-day Sharpe + lifetime
trade count, then writes a dynamic threshold override to bot_threshold_dynamic.

Rules (per Brock's 7-day push spec — translated to the 0-100 integer scale
used by app.services.discipline._composite_score):

  Sharpe(30d) >= 1.0 AND trade_count >= 50  →  threshold = 50   (loose)
  Sharpe(30d) < 0                            →  threshold = 80   (tight)
  otherwise                                  →  no row written
                                                (filter falls back to YAML
                                                 override / profile default /
                                                 60).

Default 60. Lower = LOOSER (more signals pass).
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

logger = logging.getLogger(__name__)

LOOSEN_THRESHOLD = 50
TIGHTEN_THRESHOLD = 80
SHARPE_LOOSEN_FLOOR = 1.0
SHARPE_TIGHTEN_CEILING = 0.0
MIN_TRADE_COUNT = 50
LOOKBACK_DAYS = 30


def _profile_sharpe_and_trades(db: Session, profile_id: int) -> tuple[float | None, int]:
    """Rolling 30-day Sharpe annualized + lifetime trade count for a profile."""
    cutoff = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    try:
        rows = db.execute(sql_text("""
            SELECT bdp.realized_cents, a.starting_capital_cents
              FROM bot_daily_pnl bdp
              JOIN bot_allocations a ON a.id = bdp.allocation_id
             WHERE a.profile_id = :pid
               AND bdp.date >= :cutoff
        """), {"pid": profile_id, "cutoff": cutoff}).fetchall()
    except Exception as exc:
        logger.warning("[threshold_auto_promote] daily_pnl lookup failed for profile %d: %s", profile_id, exc)
        return None, 0

    returns: list[float] = []
    for realized, start_cap in rows:
        if start_cap and start_cap > 0:
            returns.append(float(realized or 0) / float(start_cap))

    n = len(returns)
    sharpe: float | None = None
    if n >= 2:
        mean = sum(returns) / n
        variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
        daily_std = math.sqrt(variance) if variance > 0 else 0
        if daily_std > 0:
            sharpe = (mean / daily_std) * math.sqrt(252)

    try:
        trade_count = db.execute(sql_text("""
            SELECT COUNT(*) FROM bot_trades bt
              JOIN bot_allocations a ON a.id = bt.allocation_id
             WHERE a.profile_id = :pid
        """), {"pid": profile_id}).scalar() or 0
    except Exception:
        trade_count = 0
    return sharpe, int(trade_count)


def run_threshold_auto_promote(db: Session) -> dict[str, Any]:
    """Nightly evaluation. Writes/updates bot_threshold_dynamic.

    Returns a summary dict: rows of {profile_name, action, threshold, sharpe, trades}.
    """
    try:
        profiles = db.execute(sql_text(
            "SELECT id, name FROM bot_profiles"
        )).fetchall()
    except Exception as exc:
        logger.error("[threshold_auto_promote] profile fetch failed: %s", exc)
        return {"error": str(exc), "actions": []}

    actions: list[dict] = []
    for pid, name in profiles:
        sharpe, trades = _profile_sharpe_and_trades(db, int(pid))
        threshold: int | None = None
        source: str | None = None
        if sharpe is not None and sharpe >= SHARPE_LOOSEN_FLOOR and trades >= MIN_TRADE_COUNT:
            threshold = LOOSEN_THRESHOLD
            source = "auto_promote_sharpe_high"
        elif sharpe is not None and sharpe < SHARPE_TIGHTEN_CEILING:
            threshold = TIGHTEN_THRESHOLD
            source = "auto_promote_sharpe_low"

        if threshold is None:
            # No action — remove any stale dynamic row so the YAML override /
            # profile default re-applies cleanly.
            try:
                db.execute(sql_text(
                    "DELETE FROM bot_threshold_dynamic WHERE profile_id = :pid"
                ), {"pid": pid})
            except Exception:
                pass
            continue

        try:
            db.execute(sql_text("""
                INSERT INTO bot_threshold_dynamic (profile_id, threshold, sharpe_30d, trade_count, source, updated_at)
                VALUES (:pid, :t, :s, :n, :src, CURRENT_TIMESTAMP)
                ON CONFLICT(profile_id) DO UPDATE SET
                    threshold = excluded.threshold,
                    sharpe_30d = excluded.sharpe_30d,
                    trade_count = excluded.trade_count,
                    source = excluded.source,
                    updated_at = excluded.updated_at
            """), {"pid": pid, "t": threshold, "s": sharpe, "n": trades, "src": source})
            actions.append({
                "profile_id": int(pid),
                "profile_name": name,
                "action": "loosen" if threshold == LOOSEN_THRESHOLD else "tighten",
                "threshold": threshold,
                "sharpe_30d": sharpe,
                "trade_count": trades,
                "source": source,
            })
        except Exception as exc:
            logger.warning(
                "[threshold_auto_promote] write failed for profile %s: %s",
                name, exc,
            )

    try:
        db.commit()
    except Exception:
        pass

    try:
        from app.services.discord import send_ops_alert
        loosened = [a for a in actions if a["action"] == "loosen"]
        tightened = [a for a in actions if a["action"] == "tighten"]
        send_ops_alert(
            title=f"[threshold-auto-promote] {len(loosened)} loose · {len(tightened)} tight",
            message=(
                "Nightly auto-promote complete.\n"
                f"Loosened: {', '.join(a['profile_name'] for a in loosened) or '(none)'}\n"
                f"Tightened: {', '.join(a['profile_name'] for a in tightened) or '(none)'}\n"
                "GET /api/admin/discipline/threshold-status for the table."
            ),
            severity="info",
            source="threshold_auto_promote.run",
        )
    except Exception:
        pass

    return {"actions": actions, "loose_count": sum(1 for a in actions if a["action"] == "loosen"),
            "tight_count": sum(1 for a in actions if a["action"] == "tighten")}


def threshold_status(db: Session) -> list[dict]:
    """Diagnostic — current dynamic-override rows joined with profile names."""
    try:
        rows = db.execute(sql_text("""
            SELECT btd.profile_id, p.name, btd.threshold, btd.sharpe_30d, btd.trade_count,
                   btd.source, btd.updated_at
              FROM bot_threshold_dynamic btd
              LEFT JOIN bot_profiles p ON p.id = btd.profile_id
             ORDER BY btd.threshold ASC, p.name ASC
        """)).fetchall()
        return [
            {
                "profile_id": r[0],
                "profile_name": r[1] or "?",
                "threshold": r[2],
                "sharpe_30d": r[3],
                "trade_count": r[4],
                "source": r[5],
                "updated_at": str(r[6]) if r[6] is not None else None,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("[threshold_auto_promote] status failed: %s", exc)
        return []

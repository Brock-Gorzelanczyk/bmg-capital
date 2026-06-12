"""
Tier B executor: allocation change.

Validates and applies a capital_pct change to a bot allocation.
All guard rails enforced here — if ANY check fails the change is
not applied and the reason is returned so the caller can log it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, date

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Tier C hard caps — these cannot be overridden by any proposal
MAX_SINGLE_CHANGE_PCT  = 3.0   # max |current → proposed| per proposal
MAX_DAILY_CHURN_PCT    = 8.0   # sum of |delta| for all executed changes today
MAX_CONCENTRATION_PCT  = 85.0  # no single bot > 85% (absolute ceiling)
MIN_CONCENTRATION_PCT  = 0.5   # no bot reduced below 0.5%


def execute_allocation_change(
    db: Session,
    *,
    proposal_id: str,
    bot_name: str,
    proposed_pct: float,
) -> dict:
    """
    Apply a capital_pct change for bot_name.

    Returns {"ok": bool, "reason": str, "old_pct": float, "new_pct": float}.
    On success, updates bot_allocations and writes execution result to proposal_audit.
    """
    now = datetime.now(timezone.utc).isoformat()

    # 1. Look up the allocation
    row = db.execute(
        text("""
            SELECT ba.id, ba.capital_pct
            FROM bot_allocations ba
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE bp.name = :bot AND ba.enabled = 1
            ORDER BY ba.id ASC LIMIT 1
        """),
        {"bot": bot_name},
    ).fetchone()

    if not row:
        return {"ok": False, "reason": f"No active allocation found for bot '{bot_name}'"}

    alloc_id, current_pct = row[0], float(row[1])
    delta = abs(proposed_pct - current_pct)

    # 2. Tier C: single change guard
    if delta > MAX_SINGLE_CHANGE_PCT:
        return {
            "ok": False,
            "reason": f"Proposed change {delta:.2f}% exceeds Tier C limit ({MAX_SINGLE_CHANGE_PCT}%)",
        }

    # 3. Tier C: concentration guard
    if proposed_pct > MAX_CONCENTRATION_PCT:
        return {
            "ok": False,
            "reason": f"Proposed {proposed_pct:.1f}% exceeds concentration cap ({MAX_CONCENTRATION_PCT}%)",
        }
    if proposed_pct < MIN_CONCENTRATION_PCT:
        return {
            "ok": False,
            "reason": f"Proposed {proposed_pct:.1f}% below minimum ({MIN_CONCENTRATION_PCT}%)",
        }

    # 4. Tier C: daily churn guard
    today = date.today().isoformat()
    churn_today = _get_daily_churn(db, today)
    if churn_today + delta > MAX_DAILY_CHURN_PCT:
        return {
            "ok": False,
            "reason": (
                f"Daily churn would reach {churn_today + delta:.1f}% "
                f"(limit {MAX_DAILY_CHURN_PCT}%). Already changed {churn_today:.1f}% today."
            ),
        }

    # 5. Apply the change
    try:
        db.execute(
            text("UPDATE bot_allocations SET capital_pct = :pct WHERE id = :id"),
            {"pct": proposed_pct, "id": alloc_id},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        return {"ok": False, "reason": f"DB update failed: {exc}"}

    result = {
        "ok": True,
        "reason": "executed",
        "bot": bot_name,
        "old_pct": round(current_pct, 2),
        "new_pct": round(proposed_pct, 2),
        "delta_pct": round(proposed_pct - current_pct, 2),
    }

    # 6. Write executor result to proposal_audit
    try:
        db.execute(
            text("""
                UPDATE proposal_audit
                SET executed_ts = :ts, executor_result = :result
                WHERE proposal_id = :pid
            """),
            {"ts": now, "result": str(result), "pid": proposal_id},
        )
        db.commit()
    except Exception as exc:
        logger.warning("[executor] proposal_audit update failed: %s", exc)

    # 7. Notify Risk Sentinel via bus
    try:
        from agents.bus import publish as _pub
        _pub(
            db,
            channel="sentinel.health",
            from_agent="executor",
            to_agent="risk_sentinel",
            msg_type="allocation_changed",
            subject=f"Allocation change executed: {bot_name} {current_pct:.1f}%→{proposed_pct:.1f}%",
            payload=result,
            priority=6,
        )
    except Exception:
        pass

    logger.warning(
        "[executor] allocation change applied: %s %.1f%%→%.1f%% (proposal=%s)",
        bot_name, current_pct, proposed_pct, proposal_id,
    )
    return result


def _get_daily_churn(db: Session, today: str) -> float:
    """Sum |delta_pct| for all executed allocation changes today."""
    try:
        rows = db.execute(
            text("""
                SELECT executor_result FROM proposal_audit
                WHERE proposal_type = 'allocation_change'
                  AND decision = 'approved'
                  AND DATE(executed_ts) = :today
                  AND executor_result IS NOT NULL
            """),
            {"today": today},
        ).fetchall()

        import json
        total = 0.0
        for row in rows:
            try:
                r = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                if isinstance(r, dict):
                    total += abs(r.get("delta_pct", 0))
            except Exception:
                pass
        return total
    except Exception:
        return 0.0

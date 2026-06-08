"""Admin endpoints — internal ops, not exposed in public docs."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/backfill-bridge")
def backfill_bridge(
    max_age_hours: int = Query(48, description="How far back to copy signals"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Copy recent local bot_signals to the discord-worker Postgres bridge.

    Run once after deploy to backfill signals that were written before the
    bridge integration went live. On CONFLICT DO NOTHING — safe to call repeatedly.
    """
    bridge_url = os.environ.get("DISCORD_BRIDGE_DATABASE_URL")
    if not bridge_url:
        return {"ok": False, "error": "DISCORD_BRIDGE_DATABASE_URL env var not set on this service"}

    from app.db.models.bots import BotSignal, BotAllocation, BotProfile

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    signals = (
        db.query(BotSignal)
        .filter(BotSignal.ts >= cutoff)
        .order_by(BotSignal.ts.asc())
        .all()
    )

    written = skipped = errors = 0
    try:
        import psycopg2
        with psycopg2.connect(bridge_url) as conn:
            with conn.cursor() as cur:
                for sig in signals:
                    try:
                        alloc = db.get(BotAllocation, sig.allocation_id)
                        if not alloc:
                            skipped += 1
                            continue
                        prof = db.get(BotProfile, alloc.profile_id)
                        if not prof:
                            skipped += 1
                            continue

                        cur.execute(
                            "INSERT INTO bot_profiles (id, name) VALUES (%s, %s) "
                            "ON CONFLICT (id) DO NOTHING",
                            (prof.id, prof.name),
                        )
                        cur.execute(
                            "INSERT INTO bot_allocations (id, user_id, profile_id) "
                            "VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
                            (alloc.id, alloc.user_id, alloc.profile_id),
                        )
                        cur.execute(
                            """
                            INSERT INTO bot_signals
                              (allocation_id, ts, symbol, side, confidence, size_hint,
                               reason, strategy, entry_price, stop_price, target_price,
                               discord_posted_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL)
                            ON CONFLICT DO NOTHING
                            """,
                            (sig.allocation_id, sig.ts, sig.symbol, sig.side,
                             sig.confidence, sig.size_hint, sig.reason, sig.strategy,
                             sig.entry_price, sig.stop_price, sig.target_price),
                        )
                        written += 1
                    except Exception as row_exc:
                        errors += 1
                        logger.warning("backfill row %d error: %s", sig.id if sig else -1, row_exc)
            conn.commit()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "written": written}

    return {
        "ok": True,
        "written": written,
        "skipped": skipped,
        "errors": errors,
        "max_age_hours": max_age_hours,
    }


@router.get("/guardrail/{user_id}")
def get_guardrail(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Read the guardrail settings for a user."""
    from app.db.models.autonomous import AutonomousGuardrail
    g = db.query(AutonomousGuardrail).filter_by(user_id=user_id).first()
    if not g:
        return {"user_id": user_id, "exists": False}
    return {
        "user_id": user_id,
        "max_open_positions": g.max_open_positions,
        "daily_loss_limit_pct": g.daily_loss_limit_pct,
        "autonomous_paused": g.autonomous_paused,
    }


@router.post("/guardrail/{user_id}/position-cap")
def set_position_cap(
    user_id: int,
    value: int = Query(..., ge=1, le=500, description="New max_open_positions cap"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Directly set max_open_positions for a user's guardrail."""
    from app.db.models.autonomous import AutonomousGuardrail
    from app.services.guardrail_checker import get_or_create_guardrail
    g = get_or_create_guardrail(user_id, db)
    old = g.max_open_positions
    g.max_open_positions = value
    db.commit()
    logger.info("admin: set max_open_positions user=%d %d→%d by user=%d", user_id, old, value, current_user.id)
    return {"ok": True, "user_id": user_id, "old": old, "new": value}

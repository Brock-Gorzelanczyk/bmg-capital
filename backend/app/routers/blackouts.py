"""Blackout windows — read-only view of upcoming earnings/macro blocks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User

router = APIRouter(prefix="/api/blackouts", tags=["blackouts"])


@router.get("/upcoming")
def upcoming_blackouts(
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    end = now + timedelta(days=days)
    try:
        rows = db.execute(text(
            "SELECT id, symbol, blackout_type, event_date, "
            "blackout_start, blackout_end, source, notes "
            "FROM trading_blackouts "
            "WHERE blackout_end >= :now AND blackout_start <= :end "
            "ORDER BY blackout_start"
        ), {"now": now, "end": end}).fetchall()
    except Exception:
        return {"blackouts": [], "error": "table not yet created"}

    return {
        "blackouts": [
            {
                "id": r[0], "symbol": r[1], "blackout_type": r[2],
                "event_date": str(r[3]) if r[3] else None,
                "blackout_start": str(r[4]) if r[4] else None,
                "blackout_end": str(r[5]) if r[5] else None,
                "source": r[6], "notes": r[7],
                "is_active": r[4] <= now <= r[5] if r[4] and r[5] else False,
            }
            for r in rows
        ]
    }

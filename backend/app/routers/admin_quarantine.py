"""GET /api/admin/cross-sleeve-quarantine — read-only view of the quarantine table."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/cross-sleeve-quarantine")
def get_cross_sleeve_quarantine(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict:
    """Return the cross-sleeve quarantine table rows.

    Returns {"as_of": ..., "unresolved_count": 0, "rows": []} if the table
    does not exist yet OR has zero rows. Never raises.
    """
    as_of = datetime.now(timezone.utc).isoformat()
    try:
        # Check if table exists first (migration may not have run yet)
        table_check = db.execute(text(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='cross_sleeve_quarantine_s14'"
        )).fetchone()
        if table_check is None:
            return {"as_of": as_of, "unresolved_count": 0, "rows": []}

        unresolved = db.execute(text(
            "SELECT COUNT(*) FROM cross_sleeve_quarantine_s14 WHERE resolved_at IS NULL"
        )).scalar() or 0

        rows = db.execute(text("""
            SELECT id, position_id, bot_id, user_id,
                   declared_asset_class, actual_symbol, actual_asset_class,
                   detected_at, action, resolved_at, resolution_note
              FROM cross_sleeve_quarantine_s14
             ORDER BY id DESC
             LIMIT :lim
        """), {"lim": limit}).fetchall()

        return {
            "as_of": as_of,
            "unresolved_count": int(unresolved),
            "rows": [
                {
                    "id": r[0],
                    "position_id": r[1],
                    "bot_id": r[2],
                    "user_id": r[3],
                    "declared_asset_class": r[4],
                    "actual_symbol": r[5],
                    "actual_asset_class": r[6],
                    "detected_at": r[7],
                    "action": r[8],
                    "resolved_at": r[9],
                    "resolution_note": r[10],
                }
                for r in rows
            ],
        }
    except Exception as exc:
        logger.error("[admin_quarantine] get_cross_sleeve_quarantine failed: %s", exc)
        return {"as_of": as_of, "unresolved_count": 0, "rows": []}

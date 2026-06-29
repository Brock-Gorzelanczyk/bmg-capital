"""Admin endpoint: manually trigger track-record reconstruction.

POST /api/admin/reconstruct-track-record
  - Requires admin auth
  - Idempotent: re-running never overwrites existing daily_pnl rows
  - Calls reconstruct_for_user(admin.id, db)

Spec: SHIP 3 admin endpoint for track-record preservation.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_admin
from app.db.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/reconstruct-track-record")
def post_reconstruct_track_record(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """Manually trigger track-record reconstruction for the calling admin's user_id.

    Idempotent: re-running never overwrites existing daily_pnl rows.

    Response shape:
        {"ok": True,
         "user_id": int,
         "result": {<same shape as reconstruct_for_user>}}
    """
    from app.services.track_record_reconstruction import reconstruct_for_user

    logger.info("[admin_reconstruct] triggered by admin user_id=%d", admin.id)
    result = reconstruct_for_user(admin.id, db)

    return {
        "ok": True,
        "user_id": admin.id,
        "result": result,
    }

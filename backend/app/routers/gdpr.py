"""
GDPR data export endpoint.
GET /api/gdpr/export — returns all data for the authenticated user as JSON.
"""
from __future__ import annotations
from datetime import timezone, datetime
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.dependencies import get_db, get_current_user

router = APIRouter(prefix="/api/gdpr", tags=["gdpr"])


@router.get("/export")
async def export_my_data(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Export all data for the authenticated user. Returns JSON."""
    from app.db.models.paper import PaperAccount, PaperPosition, PaperOrder, PaperTransaction
    from app.db.models.tier import UserTier
    from app.db.models.journal import JournalEntry
    from app.db.models.alert import AlertConfig
    from app.db.models.watchlist import Watchlist

    uid = current_user.id

    def row_to_dict(obj, exclude=None):
        exclude = exclude or set()
        return {
            c.key: getattr(obj, c.key)
            for c in obj.__table__.columns
            if c.key not in exclude
        }

    def safe_list(model, field, uid):
        try:
            rows = db.query(model).filter(getattr(model, field) == uid).all()
            return [row_to_dict(r, exclude={"hashed_password"}) for r in rows]
        except Exception:
            return []

    export = {
        "user_id": uid,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "paper_account": safe_list(PaperAccount, "user_id", uid),
        "paper_positions": safe_list(PaperPosition, "user_id", uid),
        "paper_orders": safe_list(PaperOrder, "user_id", uid),
        "paper_transactions": safe_list(PaperTransaction, "user_id", uid),
        "tier": safe_list(UserTier, "user_id", uid),
        "alerts": safe_list(AlertConfig, "user_id", uid),
        "journal": safe_list(JournalEntry, "user_id", uid),
        "watchlists": safe_list(Watchlist, "user_id", uid),
    }

    return JSONResponse(
        content=export,
        headers={"Content-Disposition": "attachment; filename=bmg-capital-export.json"},
    )

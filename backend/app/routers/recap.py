from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models.recap import DailyRecap
from app.db.models.users import User
from app.db.session import get_db
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recap", tags=["recap"])


def _serialize_recap(r: DailyRecap) -> Dict[str, Any]:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "recap_date": r.recap_date,
        "market_summary": r.market_summary,
        "strategy_summary": r.strategy_summary,
        "top_setups": r.top_setups,
        "narrative": r.narrative,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("", response_model=None)
async def list_recaps(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, List[Dict[str, Any]]]:
    """Return the last 30 recaps for the current user, newest first."""
    recaps = (
        db.query(DailyRecap)
        .filter(DailyRecap.user_id == current_user.id)
        .order_by(DailyRecap.recap_date.desc())
        .limit(30)
        .all()
    )
    return {"recaps": [_serialize_recap(r) for r in recaps]}


@router.get("/latest", response_model=None)
async def get_latest_recap(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return the single most recent recap for the current user."""
    recap = (
        db.query(DailyRecap)
        .filter(DailyRecap.user_id == current_user.id)
        .order_by(DailyRecap.recap_date.desc())
        .first()
    )
    if not recap:
        raise HTTPException(status_code=404, detail="No recap found")
    return {"recap": _serialize_recap(recap)}


@router.post("/generate", response_model=None)
async def generate_recap(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Manually trigger recap generation for today. Returns the recap."""
    from app.services.recap import generate_daily_recap

    try:
        recap = await generate_daily_recap(user_id=current_user.id)
    except Exception as exc:
        logger.error(f"Recap generation failed for user {current_user.id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Recap generation failed: {exc}")

    return {"recap": _serialize_recap(recap)}

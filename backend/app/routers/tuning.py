"""Tuning Advisor endpoints — Monday triage view + promotion candidates."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_admin
from app.services.tuning_advisor import get_promotion_candidates, get_tuning_recommendations

router = APIRouter(prefix="/api/admin/tuning", tags=["tuning"])
logger = logging.getLogger(__name__)


@router.get("/recommendations", dependencies=[Depends(require_admin)])
def recommendations(
    days: int = Query(1, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """Per-strategy signal volume + rejection breakdown + suggested action."""
    try:
        return get_tuning_recommendations(db, days=days)
    except Exception as exc:
        logger.error("[tuning] recommendations failed: %s", exc, exc_info=True)
        return {
            "window_days": days,
            "error": str(exc),
            "by_volume": [], "by_reject_rate": [], "red_flags": [],
            "volume_bombs": [], "too_loose": [],
            "total_strategies_with_activity": 0, "total_analyzed": 0, "total_executed": 0,
        }


@router.get("/promotion-candidates", dependencies=[Depends(require_admin)])
def promotion_candidates(db: Session = Depends(get_db)):
    """TESTING hypotheses ready for LIVE promotion (manual confirm required)."""
    try:
        return get_promotion_candidates(db)
    except Exception as exc:
        logger.error("[tuning] promotion_candidates failed: %s", exc, exc_info=True)
        return {"candidates": [], "rejected": [], "error": str(exc)}

"""Hypothesis Tracking — live status, factor exposure, system events."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_admin
from app.services import hypotheses as hyp_svc

router = APIRouter(prefix="/api/hypotheses", tags=["hypotheses"])
logger = logging.getLogger(__name__)


@router.get("/live")
def get_live_hypotheses(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Hypothesis dashboard payload — every hypothesis with derived live stats,
    plus aggregated factor exposures and the recent system event log.
    """
    items = hyp_svc.list_live_hypotheses(db)
    factors = hyp_svc.aggregate_factor_exposures(items)
    events = hyp_svc.list_system_events(db, limit=20)

    live_count = sum(1 for h in items if h["status"] == "live")
    testing_count = sum(1 for h in items if h["status"] == "testing")
    retired_count = sum(1 for h in items if h["status"] == "retired")
    lessons_count = 0
    try:
        from app.db.models.hypotheses import Lesson
        lessons_count = db.query(Lesson).count()
    except Exception:
        pass

    return {
        "hypotheses": items,
        "factor_exposures": factors,
        "system_events": events,
        "summary": {
            "live": live_count,
            "testing": testing_count,
            "retired": retired_count,
            "lessons": lessons_count,
            "total": len(items),
        },
    }


@router.get("/system-events")
def get_system_events(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return {"items": hyp_svc.list_system_events(db, limit=limit)}


@router.post("/{hypothesis_id}/promote", dependencies=[Depends(require_admin)])
def promote_hypothesis(hypothesis_id: int, db: Session = Depends(get_db)):
    """Move hypothesis status TESTING → LIVE. Manual gate per Brock's rule
    (no auto-promotion)."""
    result = hyp_svc.set_hypothesis_status(db, hypothesis_id, "live")
    if not result:
        raise HTTPException(404, "hypothesis not found")
    return result


@router.post("/{hypothesis_id}/retire", dependencies=[Depends(require_admin)])
def retire_hypothesis(hypothesis_id: int, db: Session = Depends(get_db)):
    result = hyp_svc.set_hypothesis_status(db, hypothesis_id, "retired")
    if not result:
        raise HTTPException(404, "hypothesis not found")
    return result


@router.post("/{hypothesis_id}/demote-testing", dependencies=[Depends(require_admin)])
def demote_to_testing(hypothesis_id: int, db: Session = Depends(get_db)):
    result = hyp_svc.set_hypothesis_status(db, hypothesis_id, "testing")
    if not result:
        raise HTTPException(404, "hypothesis not found")
    return result


@router.post("/system-events", dependencies=[Depends(require_admin)])
def log_system_event(
    event_type: str = Body(..., embed=True),
    message: str = Body(..., embed=True),
    payload: Optional[dict] = Body(None, embed=True),
    db: Session = Depends(get_db),
):
    eid = hyp_svc.record_system_event(db, event_type, message, payload)
    if eid is None:
        raise HTTPException(500, "failed to record event")
    return {"id": eid}

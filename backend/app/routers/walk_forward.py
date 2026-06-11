"""Walk-forward analysis pipeline endpoint."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models.pipeline import CandidateStateHistory, StrategyCandidate, WfaRun
from app.db.models.users import User
from app.db.session import get_db
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/walk-forward", tags=["walk-forward"])


class WfaRunBody(BaseModel):
    candidate_name: str
    is_years: float = 5.0
    oos_years: float = 1.0
    embargo_days: int = 21


@router.post("/run")
def enqueue_wfa(
    body: WfaRunBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Enqueue a walk-forward analysis run for a named candidate.

    Candidate must be in BACKTEST_DONE state. The pipeline worker picks up
    queued WfaRun records every 60 seconds.
    """
    c = db.query(StrategyCandidate).filter(StrategyCandidate.name == body.candidate_name).first()
    if not c:
        raise HTTPException(status_code=404, detail=f"Candidate '{body.candidate_name}' not found")
    if c.state not in ("BACKTEST_DONE", "WFA_QUEUED"):
        raise HTTPException(
            status_code=409,
            detail=f"Candidate must be in BACKTEST_DONE state (currently '{c.state}'). "
                   "Run a backtest first via POST /api/backtest/run.",
        )

    job_id = str(uuid.uuid4())
    run = WfaRun(
        candidate_id=c.id,
        job_id=job_id,
        status="queued",
        is_years=body.is_years,
        oos_years=body.oos_years,
        embargo_days=body.embargo_days,
    )
    db.add(run)
    from_state = c.state
    c.state = "WFA_QUEUED"
    c.updated_at = datetime.now(timezone.utc)
    db.add(CandidateStateHistory(
        candidate_id=c.id, from_state=from_state, to_state="WFA_QUEUED",
        reason="enqueued via /api/walk-forward/run", triggered_by=str(current_user.id),
    ))
    db.commit()
    logger.info("[walk-forward/run] enqueued candidate=%s job=%s", body.candidate_name, job_id)
    return {
        "job_id": job_id,
        "candidate_name": body.candidate_name,
        "is_years": body.is_years,
        "oos_years": body.oos_years,
        "embargo_days": body.embargo_days,
    }


@router.get("/status/{job_id}")
def wfa_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Poll status of a specific WFA job."""
    run = db.query(WfaRun).filter(WfaRun.job_id == job_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="WFA job not found")
    return {
        "job_id": job_id,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "wfe": run.wfe,
        "pbo": run.pbo,
        "dsr": run.dsr,
        "aggregate_oos_sharpe": run.aggregate_oos_sharpe,
        "n_walks": run.n_walks,
        "error_message": run.error_message,
    }

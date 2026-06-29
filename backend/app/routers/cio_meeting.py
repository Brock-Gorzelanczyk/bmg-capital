"""CIO Meeting router — start/query meeting, Brock veto override.

POST /api/agents/cio/meeting/start     — kick off a new meeting (sync, ≤10min)
GET  /api/agents/cio/meeting/latest    — latest meeting + briefing
POST /api/agents/cio/veto/{id}/override — Brock override a Dick veto
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.agents.cio_orchestrator import kick_off_cio_meeting

router = APIRouter(prefix="/api/agents/cio", tags=["agents", "meetings"])


class MeetingKickoffRequest(BaseModel):
    runner_label: str = "manual_api"
    budget_cap_usd: float = 1.50
    dry_run: bool = False


@router.post("/meeting/start")
def start_meeting(
    body: MeetingKickoffRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Kick off a CIO Morning Meeting. Synchronous — returns when meeting completes.

    409 guard: rejects if another meeting has status='running' started within last 15 min.
    v1 is manual-trigger only; no cron/scheduler.
    """
    row = db.execute(
        text(
            "SELECT meeting_id FROM fund_meetings "
            "WHERE status='running' AND started_at > datetime('now', '-15 minutes') LIMIT 1"
        )
    ).fetchone()
    if row:
        raise HTTPException(409, f"meeting already in progress: {row[0]}")

    return kick_off_cio_meeting(
        db,
        runner_label=body.runner_label,
        budget_cap_usd=body.budget_cap_usd,
        dry_run=body.dry_run,
    )


@router.get("/meeting/latest")
def latest_meeting(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Return the most recent meeting joined with its briefing."""
    row = db.execute(
        text(
            "SELECT m.meeting_id, m.started_at, m.ended_at, m.duration_seconds, "
            "       m.model_cost_usd, m.status, m.vetoes_used, m.failure_reason, "
            "       b.briefing_id, b.markdown_body, b.summary_one_liner, b.needs_brock, "
            "       b.posted_at, b.discord_message_id "
            "FROM fund_meetings m "
            "LEFT JOIN fund_briefings b ON b.meeting_id = m.meeting_id "
            "ORDER BY m.started_at DESC LIMIT 1"
        )
    ).fetchone()
    if not row:
        raise HTTPException(404, "no meetings yet")
    return dict(row._mapping)


@router.post("/veto/{veto_id}/override")
def brock_override_veto(
    veto_id: int,
    note: str = "",
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Brock override a Dick veto. Data-only endpoint — writes brock_override=1."""
    result = db.execute(
        text(
            "UPDATE veto_log "
            "SET brock_override=1, override_at=CURRENT_TIMESTAMP, override_note=:n "
            "WHERE id=:id AND brock_override=0"
        ),
        {"id": veto_id, "n": note[:500]},
    )
    db.commit()
    if (result.rowcount or 0) == 0:
        raise HTTPException(404, "veto not found or already overridden")
    return {"veto_id": veto_id, "brock_override": True}

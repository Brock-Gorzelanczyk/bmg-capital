"""CIO Meeting router — start/query meeting, Brock veto override.

POST /api/agents/cio/meeting/start            — spawn background meeting, returns <2s
GET  /api/agents/cio/meeting/{id}/status      — poll progress
GET  /api/agents/cio/meeting/latest           — latest meeting + briefing
POST /api/agents/cio/veto/{veto_id}/override  — Brock override a Dick veto
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.agents.cio_orchestrator import create_meeting_record
from app.services.cio_meeting_runner import run_meeting_background

router = APIRouter(prefix="/api/agents/cio", tags=["agents", "meetings"])


class MeetingKickoffRequest(BaseModel):
    runner_label: str = "manual_api"
    budget_cap_usd: float = 1.50
    dry_run: bool = False  # retained for parity; routes dry_run through sync path


class MeetingStartResponse(BaseModel):
    meeting_id: str
    status: str
    started_at: str


@router.post("/meeting/start", response_model=MeetingStartResponse, status_code=202)
def start_meeting(
    body: MeetingKickoffRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Kick off a CIO Morning Meeting. Returns IMMEDIATELY with meeting_id.

    Heavy work (snapshot, 9 parallel opening reads, debate, veto, Discord post)
    runs in BackgroundTasks. Poll /meeting/{meeting_id}/status for progress.

    409 if another meeting has status='running' started within last 15 min.
    """
    if body.dry_run:
        # Dry run: run sync (no DB writes, no Discord). Use orchestrator directly.
        from app.agents.cio_orchestrator import kick_off_cio_meeting
        result = kick_off_cio_meeting(
            db,
            runner_label=body.runner_label,
            budget_cap_usd=body.budget_cap_usd,
            dry_run=True,
        )
        return MeetingStartResponse(
            meeting_id=result["meeting_id"],
            status=result["status"],
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    # Eager row insert + 409 guard (raises HTTPException(409) if blocked)
    meeting_id = create_meeting_record(db, runner_label=body.runner_label)

    # Spawn the heavy work. BackgroundTasks runs AFTER response sends, in same process,
    # so the spawned coroutine is awaited by FastAPI's executor — fine for asyncio entry.
    background_tasks.add_task(
        _spawn_runner,
        meeting_id=meeting_id,
        runner_label=body.runner_label,
        budget_cap_usd=body.budget_cap_usd,
    )

    return MeetingStartResponse(
        meeting_id=meeting_id,
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
    )


def _spawn_runner(meeting_id: str, runner_label: str, budget_cap_usd: float) -> None:
    """BackgroundTasks shim: spawns the async runner via asyncio.run.

    BackgroundTasks accepts coroutine functions but here we wrap in asyncio.run
    so the runner owns its own event loop independent of the FastAPI worker loop.
    """
    import asyncio
    asyncio.run(run_meeting_background(
        meeting_id,
        runner_label=runner_label,
        budget_cap_usd=budget_cap_usd,
    ))


@router.get("/meeting/{meeting_id}/status")
def meeting_status(
    meeting_id: str,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Poll meeting status. Status='running' if ended_at IS NULL.

    Response shape:
      {meeting_id, status, started_at, ended_at, duration_seconds,
       model_cost_usd, briefing_id, summary_one_liner, posted_to_discord,
       discord_message_id, failure_reason, vetoes_used}
    """
    row = db.execute(
        text(
            "SELECT m.meeting_id, m.started_at, m.ended_at, m.duration_seconds, "
            "       m.model_cost_usd, m.status, m.vetoes_used, m.failure_reason, "
            "       b.briefing_id, b.summary_one_liner, b.discord_message_id, b.posted_at "
            "FROM fund_meetings m "
            "LEFT JOIN fund_briefings b ON b.meeting_id = m.meeting_id "
            "WHERE m.meeting_id = :mid"
        ),
        {"mid": meeting_id},
    ).fetchone()
    if not row:
        raise HTTPException(404, f"meeting {meeting_id} not found")

    d = dict(row._mapping)
    return {
        "meeting_id": d["meeting_id"],
        "status": d["status"],
        "started_at": d["started_at"],
        "ended_at": d["ended_at"],
        "duration_seconds": d["duration_seconds"],
        "model_cost_usd": d["model_cost_usd"],
        "vetoes_used": d["vetoes_used"],
        "failure_reason": d["failure_reason"],
        "briefing_id": d["briefing_id"],
        "summary_one_liner": d["summary_one_liner"],
        "discord_message_id": d["discord_message_id"],
        "posted_to_discord": bool(d["discord_message_id"]),
    }


@router.get("/meeting/latest")
def latest_meeting(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Return the most recent meeting joined with its briefing. UNCHANGED."""
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
    """Brock override a Dick veto. UNCHANGED."""
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

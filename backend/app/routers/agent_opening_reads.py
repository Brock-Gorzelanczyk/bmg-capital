"""Agent opening-read endpoints — one per agent, called from CIO orchestrator or directly.

POST /api/agents/{agent_name}/meeting/opening-read
Returns structured opening read JSON for the given agent.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.services.agent_opening_read import (
    VALID_AGENTS,
    OpeningReadResult,
    run_opening_read,
)

router = APIRouter(prefix="/api/agents", tags=["agents", "meetings"])


class OpeningReadRequest(BaseModel):
    meeting_id: str
    canonical_snapshot: dict
    recent_activity: list[dict]
    open_commitments: list[dict]


class OpeningReadResponse(BaseModel):
    agent_name: str
    meeting_id: str
    what_im_seeing: str
    whats_working: str
    whats_broken: str
    asks: str
    metrics_i_track: dict
    confidence_in_book: str
    cost_usd: float
    response_time_ms: int
    status: str
    raw_text: str


@router.post("/{agent_name}/meeting/opening-read", response_model=OpeningReadResponse)
def opening_read_endpoint(
    agent_name: str,
    body: OpeningReadRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Run a single-agent opening read for the given meeting.

    Admin-only endpoint (get_current_user raises 401 if unauthenticated).
    Uses monkeypatch seam: tests patch 'app.services.agent_opening_read.call_llm'.
    """
    if agent_name not in VALID_AGENTS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_name}")
    r: OpeningReadResult = run_opening_read(
        agent_name=agent_name,
        meeting_id=body.meeting_id,
        canonical_snapshot=body.canonical_snapshot,
        recent_activity=body.recent_activity,
        open_commitments=body.open_commitments,
        db=db,
    )
    return OpeningReadResponse(
        **{k: getattr(r, k) for k in OpeningReadResponse.model_fields}
    )

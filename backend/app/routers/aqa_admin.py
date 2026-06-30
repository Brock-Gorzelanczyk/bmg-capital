"""AQA admin endpoints -- Phase A (read-only proposals).

Endpoints:
  GET  /api/admin/aqa/status                -- aqa_state row + last 5 proposals
  POST /api/admin/aqa/freeze                -- freeze the agent
  POST /api/admin/aqa/unfreeze              -- unfreeze the agent
  GET  /api/admin/aqa/proposals             -- paginated proposal list (no LLM body)
  GET  /api/admin/aqa/proposals/{id}        -- full proposal including llm_response_md

All endpoints require authenticated user (get_current_user). No manual run-cycle
endpoint in Phase A (scheduler-only per spec).

# TODO PHASE B: POST /api/admin/aqa/run-cycle (manual trigger)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.services import aqa_safety

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/aqa", tags=["aqa-admin"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class FreezeRequest(BaseModel):
    reason: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_aqa_state_row(db: Session) -> dict:
    """Return aqa_state as dict. Raises HTTPException(503) if table missing or empty."""
    try:
        row = db.execute(
            text(
                "SELECT frozen, frozen_reason, frozen_at, frozen_by, "
                "       deploys_today, llm_calls_today, counter_date, updated_at "
                "FROM aqa_state "
                "WHERE id = (SELECT MIN(id) FROM aqa_state)"
            )
        ).fetchone()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="aqa_state not initialized -- m048 pending",
        )
    if row is None:
        raise HTTPException(
            status_code=503,
            detail="aqa_state not initialized -- m048 pending",
        )
    return dict(row._mapping)


def _parse_proposal_row(row) -> dict:
    """Convert a proposal DB row to a dict with issue_tags parsed from JSON."""
    d = dict(row._mapping)
    try:
        d["issue_tags"] = json.loads(d["issue_tags"]) if d.get("issue_tags") else []
    except (json.JSONDecodeError, TypeError):
        d["issue_tags"] = []
    return d


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def compute_aqa_status(db: Session) -> dict:
    """Extract AQA status logic for in-process callers (e.g. daily audit).

    Returns a subset of the full AQA status dict:
      enabled, frozen, deploys_today, llm_calls_today
    Returns defaults if aqa_state table is missing or empty (non-fatal).
    """
    try:
        state = _get_aqa_state_row(db)
    except Exception:
        return {
            "aqa_enabled": False,
            "frozen": False,
            "deploys_today": 0,
            "llm_calls_today": 0,
        }
    return {
        "aqa_enabled": os.getenv("AQA_ENABLED", "false").strip().lower() == "true",
        "frozen": bool(state.get("frozen", False)),
        "deploys_today": int(state.get("deploys_today", 0)),
        "llm_calls_today": int(state.get("llm_calls_today", 0)),
    }


@router.get("/status")
def get_aqa_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return aqa_state row + last 5 proposals.

    Response shape:
      {
        "frozen": bool, "frozen_reason": str|None, "frozen_at": iso|None,
        "frozen_by": str|None,
        "deploys_today": int, "llm_calls_today": int, "counter_date": iso,
        "max_deploys_per_24h": int, "max_llm_calls_per_day": int,
        "aqa_enabled": bool,
        "recent_proposals": [
          {"id": int, "cycle_id": str, "created_at": iso, "issue_tags": list,
           "outcome": str|None}, ...
        ]
      }
    """
    state = _get_aqa_state_row(db)

    try:
        proposal_rows = db.execute(
            text(
                "SELECT id, cycle_id, created_at, issue_tags, outcome "
                "FROM aqa_proposals "
                "ORDER BY created_at DESC "
                "LIMIT 5"
            )
        ).fetchall()
        recent_proposals = [_parse_proposal_row(r) for r in proposal_rows]
    except Exception:
        recent_proposals = []

    return {
        "frozen": bool(state["frozen"]),
        "frozen_reason": state.get("frozen_reason"),
        "frozen_at": state.get("frozen_at"),
        "frozen_by": state.get("frozen_by"),
        "deploys_today": int(state.get("deploys_today", 0)),
        "llm_calls_today": int(state.get("llm_calls_today", 0)),
        "counter_date": str(state.get("counter_date", "")),
        "max_deploys_per_24h": int(os.getenv("AQA_MAX_DEPLOYS_PER_24H", "10")),
        "max_llm_calls_per_day": int(os.getenv("AQA_DAILY_MAX_LLM_CALLS", "2000")),
        "aqa_enabled": os.getenv("AQA_ENABLED", "false").strip().lower() == "true",
        "recent_proposals": recent_proposals,
    }


@router.post("/freeze")
def post_aqa_freeze(
    body: FreezeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Freeze the AQA agent.

    Body: {"reason": "..."}.
    Returns: {"frozen": True, "reason": ..., "by": <user.email>}.
    """
    by = getattr(current_user, "email", str(getattr(current_user, "id", "unknown")))
    aqa_safety.freeze(db, reason=body.reason, by=by)
    logger.warning("[aqa-admin] freeze requested by %s reason=%r", by, body.reason)
    return {"frozen": True, "reason": body.reason, "by": by}


@router.post("/unfreeze")
def post_aqa_unfreeze(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Unfreeze the AQA agent.

    Returns: {"frozen": False, "by": <user.email>}.
    """
    by = getattr(current_user, "email", str(getattr(current_user, "id", "unknown")))
    aqa_safety.unfreeze(db, by=by)
    logger.warning("[aqa-admin] unfreeze requested by %s", by)
    return {"frozen": False, "by": by}


@router.post("/run-now")
def post_aqa_run_now(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Manually trigger an AQA cycle. Bypasses the APScheduler interval.

    Useful for:
      - Debugging when scheduler not firing (e.g. interval mis-set,
        next_run_time conflict)
      - Smoke-testing AQA logic after deploy
      - Brock-on-demand: when he wants to see a proposal now, not in 30 min
    """
    by = getattr(current_user, "email", str(getattr(current_user, "id", "unknown")))
    logger.warning("[aqa-admin] run-now triggered by %s", by)
    try:
        from app.agents.aqa import run_aqa_cycle
        outcome = run_aqa_cycle(db)
        return {"ok": True, "triggered_by": by, "outcome": outcome}
    except Exception as exc:
        logger.error("[aqa-admin] run-now raised: %s", exc, exc_info=True)
        return {"ok": False, "triggered_by": by, "error": str(exc)[:500]}


@router.get("/proposals")
def list_aqa_proposals(
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return paginated proposal list (no llm_response_md to keep payloads small).

    Each row: id, cycle_id, created_at, issue_tags (parsed list), outcome,
    discord_message_id, posted_at.
    """
    # Cap limit silently
    if limit > 100:
        limit = 100

    try:
        rows = db.execute(
            text(
                "SELECT id, cycle_id, created_at, issue_tags, outcome, "
                "       discord_message_id, posted_at "
                "FROM aqa_proposals "
                "ORDER BY created_at DESC "
                "LIMIT :limit"
            ),
            {"limit": limit},
        ).fetchall()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"aqa_proposals query failed: {exc}")

    proposals = [_parse_proposal_row(r) for r in rows]
    return {"proposals": proposals, "count": len(proposals)}


@router.get("/proposals/{proposal_id}")
def get_aqa_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return full proposal row including llm_response_md and context_summary.

    404 if not found.
    """
    try:
        row = db.execute(
            text("SELECT * FROM aqa_proposals WHERE id = :id"),
            {"id": proposal_id},
        ).fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"aqa_proposals query failed: {exc}")

    if row is None:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")

    d = dict(row._mapping)
    # Parse issue_tags JSON
    try:
        d["issue_tags"] = json.loads(d["issue_tags"]) if d.get("issue_tags") else []
    except (json.JSONDecodeError, TypeError):
        d["issue_tags"] = []
    # Parse context_summary JSON
    try:
        d["context_summary"] = json.loads(d["context_summary"]) if d.get("context_summary") else {}
    except (json.JSONDecodeError, TypeError):
        pass  # leave as raw string
    return d

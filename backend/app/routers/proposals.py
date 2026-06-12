"""
/api/proposals — proposal history and manual trigger endpoint.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.dependencies import get_db

router = APIRouter(prefix="/api/proposals", tags=["proposals"])
logger = logging.getLogger(__name__)


@router.get("/history")
def get_proposal_history(db: Session = Depends(get_db), limit: int = 50):
    """Return recent proposals with their full audit trail."""
    try:
        rows = db.execute(
            text("""
                SELECT proposal_id, proposal_type, generated_ts,
                       posted_message_id, proposed_change, rationale,
                       decision, decision_ts, decision_reason,
                       executed_ts, executor_result
                FROM proposal_audit
                ORDER BY generated_ts DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()

        proposals = []
        for r in rows:
            change = r[4]
            try:
                change = json.loads(change) if isinstance(change, str) else change
            except Exception:
                pass
            proposals.append({
                "proposal_id":    r[0],
                "proposal_type":  r[1],
                "generated_ts":   str(r[2]),
                "has_message":    r[3] is not None,
                "proposed_change": change,
                "rationale":      r[5],
                "decision":       r[6],
                "decision_ts":    str(r[7]) if r[7] else None,
                "decision_reason": r[8],
                "executed_ts":    str(r[9]) if r[9] else None,
                "executor_result": r[10],
            })

        return {"proposals": proposals, "count": len(proposals)}
    except Exception as exc:
        logger.warning("[proposals] history query failed: %s", exc)
        return {"proposals": [], "count": 0}


@router.get("/stats")
def get_proposal_stats(db: Session = Depends(get_db)):
    """Today's proposal counters used by /fund Portfolio Manager card."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        def _count(where: str, params: dict) -> int:
            return db.execute(
                text(f"SELECT COUNT(*) FROM proposal_audit WHERE {where}"),
                params,
            ).scalar() or 0

        return {
            "generated_today":    _count("generated_ts >= :c", {"c": cutoff}),
            "pending":            _count("decision = 'pending'", {}),
            "approved_today":     _count("decision = 'approved' AND decision_ts >= :c", {"c": cutoff}),
            "rejected_today":     _count("decision = 'rejected' AND decision_ts >= :c", {"c": cutoff}),
            "deferred_today":     _count("decision = 'deferred' AND decision_ts >= :c", {"c": cutoff}),
            "auto_rejected_today": _count("decision = 'auto_rejected' AND generated_ts >= :c", {"c": cutoff}),
        }
    except Exception as exc:
        logger.warning("[proposals] stats query failed: %s", exc)
        return {
            "generated_today": 0, "pending": 0, "approved_today": 0,
            "rejected_today": 0, "deferred_today": 0, "auto_rejected_today": 0,
        }


@router.post("/generate-test")
def generate_test_proposal(db: Session = Depends(get_db)):
    """
    Manually trigger one proposal generation cycle for testing.
    Runs the same logic as the morning Queen session proposal step.
    """
    try:
        from strategy_lab.agents.queen import _generate_proposals
        from strategy_lab.agents.researcher import run_daily_research
        from strategy_lab.agents.strategy_monitor import run_strategy_health_check

        health   = run_strategy_health_check(db)
        research = run_daily_research(db)
        results  = _generate_proposals(db, research=research, health=health)
        return {"ok": True, "proposals_generated": len(results), "proposals": results}
    except Exception as exc:
        logger.warning("[proposals] test generation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

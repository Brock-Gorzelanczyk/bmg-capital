"""Sentinel status and control endpoints."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.sentinel import AgentEvent, AgentFix, AgentCircuitBreaker
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/sentinel", tags=["sentinel"])


@router.get("/status")
def sentinel_status(db: Session = Depends(get_db)):
    """Public status probe — no auth required so the dashboard can poll it."""
    enabled = os.getenv("SENTINEL_ENABLED", "false").lower() == "true"
    channel_id = os.getenv("DISCORD_CHANNEL_ID_SENTINEL_OPS", "")

    try:
        events_open = db.query(AgentEvent).filter(AgentEvent.state == "open").count()
    except Exception:
        events_open = None

    try:
        from sqlalchemy import func
        now = datetime.now(timezone.utc)
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        cost_24h = (
            db.query(func.coalesce(func.sum(AgentFix.cost_usd), 0))
            .filter(AgentFix.created_at >= cutoff)
            .scalar()
        )
        cost_24h = float(cost_24h) if cost_24h is not None else 0.0
    except Exception:
        cost_24h = None

    try:
        active_breakers = (
            db.query(AgentCircuitBreaker)
            .filter(AgentCircuitBreaker.resets_at > datetime.now(timezone.utc))
            .count()
        )
    except Exception:
        active_breakers = None

    return {
        "enabled": enabled,
        "channel_id": channel_id if channel_id else None,
        "events_open": events_open,
        "cost_24h_usd": cost_24h,
        "active_circuit_breakers": active_breakers,
    }


@router.post("/test-heartbeat")
def test_heartbeat(_current_user=Depends(get_current_user)):
    """Post a test heartbeat to #sentinel-ops to verify bot token + channel permissions."""
    from app.services.sentinel_monitor import send_test_heartbeat
    result = send_test_heartbeat()
    if not result["ok"]:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=result.get("error", "Discord post failed"))
    return result

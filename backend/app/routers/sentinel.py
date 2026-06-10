"""Sentinel status and control endpoints."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.sentinel import AgentEvent, AgentFix, AgentCircuitBreaker
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/sentinel", tags=["sentinel"])

# IPs allowed to call kill-switch and test-action without a Bearer token
_ALLOWED_IPS: set[str] = {"127.0.0.1", "::1"}


def _check_ip(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    allowed_raw = os.getenv("SENTINEL_ADMIN_IPS", "")
    extra = {ip.strip() for ip in allowed_raw.split(",") if ip.strip()}
    allowed = _ALLOWED_IPS | extra
    if client_ip not in allowed:
        raise HTTPException(status_code=403, detail=f"IP {client_ip} not in SENTINEL_ADMIN_IPS allowlist")


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

    from app.services.sentinel_actions import autofix_enabled, get_autofix_tier
    return {
        "enabled": enabled,
        "channel_id": channel_id if channel_id else None,
        "events_open": events_open,
        "cost_24h_usd": cost_24h,
        "active_circuit_breakers": active_breakers,
        "autofix_enabled": autofix_enabled(),
        "autofix_tier": get_autofix_tier(),
    }


@router.post("/test-heartbeat")
def test_heartbeat(_current_user=Depends(get_current_user)):
    """Post a test heartbeat to #sentinel-ops to verify bot token + channel permissions."""
    from app.services.sentinel_monitor import send_test_heartbeat
    result = send_test_heartbeat()
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Discord post failed"))
    return result


class TestEventBody(BaseModel):
    agent_id: str = "test-agent"
    severity: str = "warning"
    category: str = "test-event"
    message: str = "Manual test event"


@router.post("/test-event")
def test_event(body: TestEventBody):
    """
    Inject a fake AgentEvent and, if SENTINEL_ESCALATION_MODE=true,
    post a real escalation embed to #sentinel-ops.
    Gated on SENTINEL_ENABLED — no Bearer token required.
    """
    if not os.getenv("SENTINEL_ENABLED", "false").lower() == "true":
        raise HTTPException(status_code=403, detail="SENTINEL_ENABLED is not set")
    from app.services.sentinel_monitor import (
        create_agent_event,
        _escalation_enabled,
        _post_escalation_embed,
    )

    # Unique fingerprint per call so it never dedupes
    now_str = datetime.now(timezone.utc).isoformat()
    fingerprint = hashlib.sha256(
        f"test:{body.agent_id}:{body.category}:{now_str}".encode()
    ).hexdigest()[:64]

    payload = {"message": body.message, "source": "test-event endpoint"}

    event_id = create_agent_event(
        agent_id=body.agent_id,
        severity=body.severity,
        category=body.category,
        fingerprint=fingerprint,
        payload=payload,
    )

    if event_id is None:
        raise HTTPException(status_code=500, detail="Failed to create test event")

    escalation_posted = False
    if _escalation_enabled():
        escalation_posted = _post_escalation_embed(
            event_id=event_id,
            agent_id=body.agent_id,
            severity=body.severity,
            category=body.category,
            payload=payload,
            message=body.message,
        )

    return {
        "event_id": event_id,
        "fingerprint": fingerprint[:16] + "…",
        "escalation_mode": _escalation_enabled(),
        "escalation_posted": escalation_posted,
    }


# ── Autofix endpoints ─────────────────────────────────────────────────────────

@router.post("/disable-autofix")
def disable_autofix_endpoint(request: Request):
    """
    Kill switch — disables autofix in process memory until next restart.
    IP-allowlist gated (no Bearer token required for emergency access).
    Set SENTINEL_ADMIN_IPS env var to allow additional IPs.
    """
    _check_ip(request)
    from app.services.sentinel_actions import disable_autofix
    disable_autofix()
    return {"autofix_enabled": False, "note": "Disabled until next restart. SENTINEL_AUTOFIX_ENABLED env var unchanged."}


class TestActionBody(BaseModel):
    action: str
    params: dict = {}


@router.post("/test-action")
def test_action(body: TestActionBody, request: Request):
    """
    Test a whitelisted autofix action end-to-end.
    Posts pre/post Discord embeds. IP-allowlist gated.
    Returns 403 if action is permanently blocked.
    """
    if not os.getenv("SENTINEL_ENABLED", "false").lower() == "true":
        raise HTTPException(status_code=403, detail="SENTINEL_ENABLED is not set")

    _check_ip(request)

    from app.services.sentinel_actions import (
        execute_action,
        SentinelBlockedAction,
        autofix_enabled,
        get_autofix_tier,
    )

    # Let blocked actions 403 before checking autofix flag
    try:
        from app.services.sentinel_actions import _validate_action
        _validate_action(body.action)
    except SentinelBlockedAction as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        result = execute_action(body.action, body.params)
    except SentinelBlockedAction as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "action": body.action,
        "tier": get_autofix_tier(),
        "autofix_enabled": autofix_enabled(),
        "result": result,
    }

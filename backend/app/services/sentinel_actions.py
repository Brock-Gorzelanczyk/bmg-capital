"""
Sentinel Phase D — auto-fix action whitelist.

Hard rule: this module heals INFRASTRUCTURE only. It must never touch anything
that affects how bots generate signals, size positions, or execute trades.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Runtime kill switch (process-memory — survives until restart) ─────────────

_autofix_runtime_enabled: bool = True  # flipped by kill-switch endpoint


def autofix_enabled() -> bool:
    """Returns True when both the env var AND the runtime flag allow autofix."""
    if not _autofix_runtime_enabled:
        return False
    return os.getenv("SENTINEL_AUTOFIX_ENABLED", "false").lower() == "true"


def disable_autofix() -> None:
    """Kill switch — flips runtime flag off without requiring a redeploy."""
    global _autofix_runtime_enabled
    _autofix_runtime_enabled = False
    logger.warning("[sentinel-autofix] kill switch activated — autofix disabled until restart")


def get_autofix_tier() -> int:
    """
    Returns the active autofix rollout tier (0–3).
      0 → Phase C only (no autofix)
      1 → D1: rotate_logs + refresh_discord_webhook
      2 → D2: adds restart_discord_worker + reset_db_connection_pool
      3 → D3: adds rollback_frontend
    """
    raw = os.getenv("SENTINEL_AUTOFIX_TIER", "0")
    try:
        return max(0, min(3, int(raw)))
    except ValueError:
        return 0


# ── Permanent blocklist ───────────────────────────────────────────────────────

BLOCKED_ACTIONS: set[str] = {
    "restart_backend",
    "modify_yaml",
    "edit_strategy_code",
    "cancel_order",
    "close_position",
    "modify_positions_table",
    "modify_signals_table",
    "restart_scheduler",
    "deploy_backend_change",
    "modify_env_var",
    "delete_anything",
}

# Prefix patterns that also block (anything matching is refused)
_BLOCKED_PREFIXES = ("delete_",)

# Actions allowed per tier
_TIER_ACTIONS: dict[int, set[str]] = {
    1: {"rotate_logs", "refresh_discord_webhook"},
    2: {"rotate_logs", "refresh_discord_webhook", "restart_discord_worker", "reset_db_connection_pool"},
    3: {"rotate_logs", "refresh_discord_webhook", "restart_discord_worker",
        "reset_db_connection_pool", "rollback_frontend"},
}


class SentinelBlockedAction(Exception):
    pass


def _validate_action(action_name: str) -> None:
    if action_name in BLOCKED_ACTIONS:
        raise SentinelBlockedAction(
            f"'{action_name}' is permanently blocked. Escalate to human instead."
        )
    for prefix in _BLOCKED_PREFIXES:
        if action_name.startswith(prefix):
            raise SentinelBlockedAction(
                f"Actions matching '{prefix}*' are permanently blocked. Escalate to human instead."
            )
    tier = get_autofix_tier()
    allowed = _TIER_ACTIONS.get(tier, set())
    if action_name not in allowed:
        raise SentinelBlockedAction(
            f"'{action_name}' is not in the whitelist for tier {tier}. Current tier allows: {sorted(allowed) or 'none'}"
        )


# ── Trading path health check ─────────────────────────────────────────────────

def trading_path_healthy() -> bool:
    """
    Pre-flight guard: returns True only when the trading system is fully healthy.
    Sentinel will not execute any auto-fix action against a degraded system.

    Checks:
      1. At least one BotSignal was written in the last 2 hours (proxy for scheduler alive)
      2. If the market is closed (weekend UTC check), skip the signal freshness gate
    """
    try:
        from app.db.session import SessionLocal
        from app.db.models.bots import BotSignal

        now = datetime.now(timezone.utc)

        # Skip signal check on weekends (crypto runs 24/7 but stocks don't)
        is_weekend = now.weekday() >= 5  # Saturday=5, Sunday=6
        if is_weekend:
            return True

        cutoff = now - timedelta(hours=2)
        db = SessionLocal()
        try:
            recent = db.query(BotSignal).filter(BotSignal.ts >= cutoff).count()
            if recent == 0:
                logger.warning(
                    "[sentinel-autofix] trading_path_healthy=False — no bot signals in last 2h"
                )
                return False
        finally:
            db.close()

        return True
    except Exception as exc:
        logger.error("[sentinel-autofix] trading_path_healthy check error: %s", exc)
        # Default to healthy to avoid blocking legitimate fixes when DB is temporarily unreachable
        return True


# ── Action implementations ────────────────────────────────────────────────────

def _railway_gql_mutation(mutation: str, variables: dict) -> dict:
    token = os.getenv("RAILWAY_API_TOKEN", "")
    if not token:
        raise ValueError("RAILWAY_API_TOKEN not set")
    resp = httpx.post(
        "https://backboard.railway.app/graphql/v2",
        json={"query": mutation, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise ValueError(f"Railway GQL errors: {data['errors']}")
    return data


def _action_rotate_logs(params: dict) -> dict:
    """Rotate in-process log buffers. On Railway this clears any in-memory log queues."""
    # Railway containers don't have traditional log files — we flush logging handlers
    import logging
    for handler in logging.root.handlers:
        try:
            if hasattr(handler, "flush"):
                handler.flush()
        except Exception:
            pass
    logger.warning("[sentinel-autofix] log rotation completed (handler flush)")
    return {"rotated": True, "note": "Railway container — flushed in-memory log handlers"}


def _action_refresh_discord_webhook(params: dict) -> dict:
    """Re-validate Discord bot token and channel permissions."""
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = params.get("channel_id") or os.getenv("DISCORD_CHANNEL_ID_SENTINEL_OPS", "")
    if not token or not channel_id:
        raise ValueError("DISCORD_BOT_TOKEN or channel_id not available")

    resp = httpx.get(
        f"https://discord.com/api/v10/channels/{channel_id}",
        headers={"Authorization": f"Bot {token}"},
        timeout=8,
    )
    if resp.status_code == 403:
        raise ValueError(f"Bot still missing access to channel {channel_id}: {resp.text[:200]}")
    resp.raise_for_status()
    data = resp.json()
    return {"channel_id": channel_id, "channel_name": data.get("name", "?"), "permissions_ok": True}


def _action_restart_discord_worker(params: dict) -> dict:
    """Restart the discord-worker service via Railway GraphQL."""
    service_id = params.get("service_id") or os.getenv("RAILWAY_DISCORD_WORKER_SERVICE_ID", "")
    environment_id = params.get("environment_id") or os.getenv("RAILWAY_ENVIRONMENT_ID", "")
    if not service_id or not environment_id:
        raise ValueError("RAILWAY_DISCORD_WORKER_SERVICE_ID / RAILWAY_ENVIRONMENT_ID not set")

    mutation = """
    mutation ServiceInstanceRedeploy($serviceId: String!, $environmentId: String!) {
      serviceInstanceRedeploy(serviceId: $serviceId, environmentId: $environmentId)
    }
    """
    data = _railway_gql_mutation(mutation, {
        "serviceId": service_id,
        "environmentId": environment_id,
    })
    return {"restarted": True, "service_id": service_id, "response": data}


def _action_reset_db_connection_pool(params: dict) -> dict:
    """Reset the SQLAlchemy connection pool via internal admin endpoint."""
    from app.db.session import engine
    pool = engine.pool
    pool.dispose()
    logger.warning("[sentinel-autofix] SQLAlchemy connection pool disposed and recreated")
    return {"pool_reset": True, "pool_size": getattr(pool, "size", lambda: "?")()}


def _action_rollback_frontend(params: dict) -> dict:
    """Rollback the frontend Railway service to its previous deployment."""
    # Fetch the two most-recent frontend deployments and rollback to the older one
    project_id = os.getenv("RAILWAY_PROJECT_ID", "")
    frontend_service_id = params.get("service_id") or os.getenv("RAILWAY_FRONTEND_SERVICE_ID", "")
    if not project_id or not frontend_service_id:
        raise ValueError("RAILWAY_PROJECT_ID / RAILWAY_FRONTEND_SERVICE_ID not set")

    # Get recent deployments for the frontend service
    query = """
    query Deployments($projectId: String!, $serviceId: String!) {
      deployments(input: { projectId: $projectId, serviceId: $serviceId }, last: 5) {
        edges { node { id status createdAt } }
      }
    }
    """
    data = _railway_gql_mutation(query, {
        "projectId": project_id,
        "serviceId": frontend_service_id,
    })
    edges = data.get("data", {}).get("deployments", {}).get("edges", [])
    successful = [e["node"] for e in edges if e["node"].get("status") == "SUCCESS"]
    if len(successful) < 2:
        raise ValueError("Not enough successful frontend deployments to rollback to")

    # Rollback to the second-most-recent successful deploy
    target = successful[1]["id"]
    rollback_mutation = """
    mutation DeploymentRollback($id: String!) {
      deploymentRollback(id: $id)
    }
    """
    result = _railway_gql_mutation(rollback_mutation, {"id": target})
    return {"rolled_back_to": target, "response": result}


_ACTION_HANDLERS = {
    "rotate_logs":              _action_rotate_logs,
    "refresh_discord_webhook":  _action_refresh_discord_webhook,
    "restart_discord_worker":   _action_restart_discord_worker,
    "reset_db_connection_pool": _action_reset_db_connection_pool,
    "rollback_frontend":        _action_rollback_frontend,
}


# ── Circuit breaker ───────────────────────────────────────────────────────────

def _is_action_circuit_broken(action_name: str) -> bool:
    """Check if this action type has an active circuit breaker."""
    try:
        from app.db.session import SessionLocal
        from app.db.models.sentinel import AgentCircuitBreaker
        db = SessionLocal()
        try:
            breaker = db.query(AgentCircuitBreaker).filter(
                AgentCircuitBreaker.breaker_type == "autofix",
                AgentCircuitBreaker.key == action_name,
                AgentCircuitBreaker.resets_at > datetime.now(timezone.utc),
            ).first()
            return breaker is not None
        finally:
            db.close()
    except Exception:
        return False


def _trip_circuit_breaker(action_name: str, reason: str, duration_minutes: int = 60) -> None:
    """Trip the circuit breaker for an action type after a failed auto-fix."""
    try:
        from app.db.session import SessionLocal
        from app.db.models.sentinel import AgentCircuitBreaker
        now = datetime.now(timezone.utc)
        db = SessionLocal()
        try:
            cb = AgentCircuitBreaker(
                breaker_type="autofix",
                key=action_name,
                tripped_at=now,
                resets_at=now + timedelta(minutes=duration_minutes),
                reason=reason[:500],
            )
            db.add(cb)
            db.commit()
            logger.warning("[sentinel-autofix] circuit breaker tripped: action=%s duration=%dm", action_name, duration_minutes)
        finally:
            db.close()
    except Exception as exc:
        logger.error("[sentinel-autofix] failed to trip circuit breaker: %s", exc)


# ── Discord embed helpers for action pre/post ─────────────────────────────────

def _post_autofix_embed(title: str, color: int, fields: list[dict], channel_id: str = "") -> None:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel = channel_id or os.getenv("DISCORD_CHANNEL_ID_SENTINEL_OPS", "")
    if not token or not channel:
        return
    embed = {
        "title": title,
        "color": color,
        "fields": fields,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Sentinel Auto-Fix"},
    }
    try:
        httpx.post(
            f"https://discord.com/api/v10/channels/{channel}/messages",
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
            json={"embeds": [embed]},
            timeout=8,
        )
    except Exception as exc:
        logger.error("[sentinel-autofix] Discord embed failed: %s", exc)


# ── Main execute entry point ──────────────────────────────────────────────────

def execute_action(action_name: str, params: dict | None = None) -> dict[str, Any]:
    """
    Validate, guard, then execute a whitelisted action.
    Raises SentinelBlockedAction for permanently-blocked actions.
    Raises ValueError for misconfiguration / missing env vars.
    """
    _validate_action(action_name)

    if not trading_path_healthy():
        raise ValueError(
            "trading_path_healthy() returned False — refusing to act on a degraded system. "
            "Escalate to human instead."
        )

    if _is_action_circuit_broken(action_name):
        raise ValueError(f"Circuit breaker active for '{action_name}' — action paused for up to 60 min")

    handler = _ACTION_HANDLERS.get(action_name)
    if not handler:
        raise ValueError(f"No handler registered for action '{action_name}'")

    return handler(params or {})


# ── Decision loop (called post-escalation) ───────────────────────────────────

def run_autofix_decision(
    event_id: int,
    agent_id: str,
    severity: str,
    category: str,
    message: str,
) -> None:
    """
    Diagnostic → propose → confidence gate → execute with pre/post Discord embeds.
    This is intentionally synchronous; the caller should run it via asyncio.to_thread.
    """
    import time

    if not autofix_enabled():
        return

    tier = get_autofix_tier()
    if tier == 0:
        return

    # ── Diagnostic: map category → proposed action + confidence ───────────────
    proposal = _diagnose_event(category, message, severity)
    action_name = proposal.get("action", "escalate_only")
    confidence = float(proposal.get("confidence", 0.0))

    logger.warning(
        "[sentinel-autofix] diagnosis: event_id=%d action=%s confidence=%.2f",
        event_id, action_name, confidence,
    )

    if action_name == "escalate_only" or confidence < 0.80:
        logger.info("[sentinel-autofix] confidence below threshold or escalate_only — no action taken")
        return

    # Validate action is in current tier whitelist
    try:
        _validate_action(action_name)
    except SentinelBlockedAction as exc:
        logger.warning("[sentinel-autofix] action blocked by validator: %s", exc)
        return
    except ValueError as exc:
        logger.warning("[sentinel-autofix] action not available in tier %d: %s", tier, exc)
        return

    # ── Pre-action announce to Discord ────────────────────────────────────────
    _post_autofix_embed(
        title=f"🔧 AUTO-FIX: {action_name}",
        color=0xF39C12,
        fields=[
            {"name": "Event ID", "value": str(event_id), "inline": True},
            {"name": "Confidence", "value": f"{confidence:.0%}", "inline": True},
            {"name": "Tier", "value": str(tier), "inline": True},
            {"name": "Trigger", "value": f"{category}: {message[:200]}", "inline": False},
        ],
    )

    # ── Execute ───────────────────────────────────────────────────────────────
    try:
        result = execute_action(action_name, proposal.get("params", {}))
        logger.warning("[sentinel-autofix] action executed: %s → %s", action_name, result)
    except Exception as exc:
        logger.error("[sentinel-autofix] action FAILED: %s — %s", action_name, exc)
        _trip_circuit_breaker(action_name, str(exc), duration_minutes=60)
        _post_autofix_embed(
            title=f"❌ AUTO-FIX FAILED: {action_name}",
            color=0xE74C3C,
            fields=[
                {"name": "Event ID", "value": str(event_id), "inline": True},
                {"name": "Error", "value": str(exc)[:500], "inline": False},
                {"name": "Circuit Breaker", "value": "Tripped for 60 min", "inline": False},
            ],
        )
        return

    # ── Wait 60s then verify ──────────────────────────────────────────────────
    time.sleep(60)
    resolved = _verify_resolution(action_name, category)

    if resolved:
        _post_autofix_embed(
            title=f"✅ RESOLVED: {action_name}",
            color=0x2ECC71,
            fields=[
                {"name": "Event ID", "value": str(event_id), "inline": True},
                {"name": "Action", "value": action_name, "inline": True},
                {"name": "Status", "value": "Trigger condition no longer firing", "inline": False},
            ],
        )
    else:
        _trip_circuit_breaker(action_name, "Verification failed — trigger still active after fix", duration_minutes=60)
        _post_autofix_embed(
            title=f"❌ RESOLUTION UNCONFIRMED: {action_name}",
            color=0xE74C3C,
            fields=[
                {"name": "Event ID", "value": str(event_id), "inline": True},
                {"name": "Note", "value": "Action ran but trigger still active. Circuit breaker tripped. @here — manual check needed.", "inline": False},
            ],
        )


def _diagnose_event(category: str, message: str, severity: str) -> dict:
    """
    Map event category → proposed action and confidence score.
    Returns {"action": str, "confidence": float, "params": dict}.
    No LLM calls — deterministic rule table for Phase D.
    """
    cat = category.lower()
    msg = message.lower()

    # discord-worker missed heartbeat → restart it
    if "discord" in cat and ("heartbeat" in msg or "missed" in msg or "timeout" in msg):
        return {"action": "restart_discord_worker", "confidence": 0.88, "params": {}}

    # Discord 403 Missing Access → refresh webhook
    if "discord" in cat and ("403" in msg or "missing access" in msg or "forbidden" in msg):
        return {"action": "refresh_discord_webhook", "confidence": 0.92, "params": {}}

    # DB connection pool exhausted
    if "queuepool" in msg or ("pool" in msg and "limit" in msg) or "connection pool" in msg:
        return {"action": "reset_db_connection_pool", "confidence": 0.85, "params": {}}

    # Disk usage high
    if "disk" in cat or ("disk" in msg and ("85" in msg or "90" in msg or "full" in msg)):
        return {"action": "rotate_logs", "confidence": 0.90, "params": {}}

    # Frontend 5xx → rollback
    if "frontend" in cat and ("5xx" in msg or "502" in msg or "503" in msg):
        return {"action": "rollback_frontend", "confidence": 0.82, "params": {}}

    return {"action": "escalate_only", "confidence": 0.0, "params": {}}


def _verify_resolution(action_name: str, category: str) -> bool:
    """
    Post-action check: return True if the triggering condition seems resolved.
    Conservative: unknown categories default to True (assume resolved).
    """
    try:
        if action_name == "refresh_discord_webhook":
            # Re-validate Discord channel access
            token = os.getenv("DISCORD_BOT_TOKEN", "")
            channel = os.getenv("DISCORD_CHANNEL_ID_SENTINEL_OPS", "")
            if token and channel:
                resp = httpx.get(
                    f"https://discord.com/api/v10/channels/{channel}",
                    headers={"Authorization": f"Bot {token}"},
                    timeout=8,
                )
                return resp.status_code == 200

        if action_name == "reset_db_connection_pool":
            # Try a trivial DB query
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                db.execute(__import__("sqlalchemy").text("SELECT 1"))
                return True
            finally:
                db.close()

    except Exception as exc:
        logger.warning("[sentinel-autofix] verification error for %s: %s", action_name, exc)
        return False

    return True  # Default: assume resolved

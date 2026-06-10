"""
Sentinel integration — lightweight observation layer wired into the main backend.

Responsibilities:
  1. Startup heartbeat: post to #sentinel-ops on service start
  2. Hourly status: rich heartbeat with event counts and 24h cost
  3. Escalation gate: SENTINEL_ESCALATION_MODE controls whether events Discord-post
  4. Railway watcher: polls Railway GraphQL every 30s for failed deployments
  5. Test-event endpoint support

This runs inside the main disciplined-intuition service (not a separate sentinel
service), so it uses the same DISCORD_BOT_TOKEN the signal poster already has.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── counters (in-process, reset on restart) ──────────────────────────────────
_events_observed: int = 0
_events_deduped: int = 0
_events_resolved: int = 0
_cycles_complete: int = 0
_events_since_last_hb: int = 0   # resets each time we post the hourly heartbeat


def increment_observed() -> None:
    global _events_observed, _events_since_last_hb
    _events_observed += 1
    _events_since_last_hb += 1


def increment_deduped() -> None:
    global _events_deduped
    _events_deduped += 1


def increment_resolved() -> None:
    global _events_resolved
    _events_resolved += 1


def _get_cost_24h() -> float:
    """Query agent_fixes for total LLM cost in the last 24 hours."""
    try:
        from datetime import timedelta
        from sqlalchemy import func
        from app.db.session import SessionLocal
        from app.db.models.sentinel import AgentFix
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        db = SessionLocal()
        try:
            result = db.query(func.coalesce(func.sum(AgentFix.cost_usd), 0)).filter(
                AgentFix.created_at >= cutoff
            ).scalar()
            return float(result) if result else 0.0
        finally:
            db.close()
    except Exception:
        return 0.0


# ── Discord helpers ───────────────────────────────────────────────────────────

def _token() -> str:
    return os.getenv("DISCORD_BOT_TOKEN", "")


def _channel() -> str:
    return os.getenv("DISCORD_CHANNEL_ID_SENTINEL_OPS", "")


def _post_plain(text: str) -> bool:
    """Post a plain-text message to #sentinel-ops. Returns True on success."""
    token = _token()
    channel = _channel()
    if not token or not channel:
        logger.warning(
            "[sentinel] cannot post — DISCORD_BOT_TOKEN=%s DISCORD_CHANNEL_ID_SENTINEL_OPS=%s",
            "SET" if token else "MISSING",
            channel if channel else "MISSING",
        )
        return False
    url = f"https://discord.com/api/v10/channels/{channel}/messages"
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
                json={"content": text},
            )
        if resp.status_code == 429:
            logger.warning("[sentinel] Discord rate limited on sentinel-ops")
            return False
        if not resp.is_success:
            logger.warning(
                "[sentinel] Discord post failed status=%s: %s",
                resp.status_code, resp.text[:200],
            )
            return False
        return True
    except Exception as exc:
        logger.error("[sentinel] Discord post error: %s", exc)
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def log_config() -> None:
    """Log resolved Discord config once at startup — helps diagnose missing env vars."""
    token = _token()
    channel = _channel()
    sentinel_enabled = os.getenv("SENTINEL_ENABLED", "false").lower() == "true"
    logger.warning(
        "[sentinel] enabled=%s discord_token=%s discord_channel=%s",
        sentinel_enabled,
        "SET" if token else "MISSING",
        channel if channel else "MISSING",
    )


def send_startup_heartbeat() -> None:
    """Post a one-time startup message to #sentinel-ops."""
    enabled = os.getenv("SENTINEL_ENABLED", "false").lower() == "true"
    if not enabled:
        logger.info("[sentinel] SENTINEL_ENABLED=false — skipping startup heartbeat")
        return

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    ok = _post_plain(
        f"🤖 **Sentinel online** · {now}\n"
        f"> Observation mode active · `SENTINEL_ENABLED=true`\n"
        f"> Monitoring Railway builds · Discord health · App scanner"
    )
    if ok:
        logger.warning("[sentinel] startup heartbeat sent to #sentinel-ops")
    else:
        logger.warning("[sentinel] startup heartbeat failed — check Discord env vars above")


def _post_hourly_heartbeat() -> None:
    """Build and post the rich hourly heartbeat. Resets the per-hour event counter."""
    global _events_since_last_hb, _cycles_complete
    cost = _get_cost_24h()
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    text = (
        f"💓 **Sentinel** @ {now} — "
        f"events observed (1h): **{_events_since_last_hb}**, "
        f"cost (24h): **${cost:.2f}**, "
        f"cycles complete: **{_cycles_complete}**"
    )
    _post_plain(text)
    _events_since_last_hb = 0  # reset window


def send_hourly_status() -> None:
    """APScheduler fallback — delegates to the same rich heartbeat post."""
    enabled = os.getenv("SENTINEL_ENABLED", "false").lower() == "true"
    if not enabled:
        return
    _post_hourly_heartbeat()


async def sentinel_loop() -> None:
    """
    Internal tick loop — runs every 60 s for responsiveness.
    Posts to Discord ONCE PER HOUR; individual ticks only log.
    """
    import asyncio

    TICK_S = 60
    DISCORD_EVERY_N = 60   # 60 ticks × 60 s = 3600 s = 1 hour

    enabled = os.getenv("SENTINEL_ENABLED", "false").lower() == "true"
    channel = _channel()
    logger.warning(
        "[sentinel] loop starting — enabled=%s channel=%s tick=%ds discord_every=%d ticks",
        enabled, channel if channel else "MISSING", TICK_S, DISCORD_EVERY_N,
    )

    global _cycles_complete
    tick = 0
    while True:
        await asyncio.sleep(TICK_S)
        tick += 1
        _cycles_complete += 1
        logger.debug("[sentinel] tick=%d cycles=%d", tick, _cycles_complete)

        if enabled and channel and tick % DISCORD_EVERY_N == 0:
            await asyncio.to_thread(_post_hourly_heartbeat)


# ── Escalation gate ──────────────────────────────────────────────────────────

def _escalation_enabled() -> bool:
    return os.getenv("SENTINEL_ESCALATION_MODE", "false").lower() == "true"


_SEVERITY_COLOR = {
    "critical": 0xE74C3C,   # red
    "warning":  0xF39C12,   # orange
    "info":     0x3498DB,   # blue
}


def _post_escalation_embed(
    event_id: int,
    agent_id: str,
    severity: str,
    category: str,
    payload: dict[str, Any],
    message: str = "",
) -> bool:
    """Post a rich escalation embed to #sentinel-ops."""
    token = _token()
    channel = _channel()
    if not token or not channel:
        return False

    color = _SEVERITY_COLOR.get(severity.lower(), 0x95A5A6)
    now_iso = datetime.now(timezone.utc).isoformat()
    desc = message or payload.get("error", payload.get("error_block", ""))
    if len(desc) > 300:
        desc = desc[:297] + "…"

    fields = [
        {"name": "Agent", "value": agent_id, "inline": True},
        {"name": "Severity", "value": severity.upper(), "inline": True},
        {"name": "Category", "value": category, "inline": True},
    ]
    if "deploy_id" in payload:
        fields.append({"name": "Deploy ID", "value": payload["deploy_id"][:32], "inline": False})
    if payload.get("file"):
        loc = f"`{payload['file']}`"
        if payload.get("line"):
            loc += f" line {payload['line']}"
        fields.append({"name": "Location", "value": loc, "inline": False})

    embed = {
        "title": f"📌 ESCALATION: {category}",
        "description": desc or "_no detail_",
        "color": color,
        "fields": fields,
        "timestamp": now_iso,
        "footer": {"text": f"Sentinel · event_id: {event_id}"},
    }

    url = f"https://discord.com/api/v10/channels/{channel}/messages"
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
                json={"embeds": [embed]},
            )
        if resp.status_code == 429:
            logger.warning("[sentinel] Discord rate limited posting escalation event_id=%d", event_id)
            return False
        if not resp.is_success:
            logger.warning("[sentinel] escalation embed failed status=%s: %s",
                           resp.status_code, resp.text[:200])
            return False
        logger.warning("[sentinel] escalation embed posted event_id=%d category=%s", event_id, category)
        return True
    except Exception as exc:
        logger.error("[sentinel] escalation embed error: %s", exc)
        return False


# ── DB helpers (main backend session) ────────────────────────────────────────

def _event_exists(fingerprint: str) -> bool:
    """Return True if an open event with this fingerprint already exists."""
    try:
        from app.db.session import SessionLocal
        from app.db.models.sentinel import AgentEvent
        db = SessionLocal()
        try:
            return db.query(AgentEvent).filter(
                AgentEvent.fingerprint == fingerprint,
                AgentEvent.state == "open",
            ).first() is not None
        finally:
            db.close()
    except Exception as exc:
        logger.error("[sentinel] event_exists query failed: %s", exc)
        return False


def create_agent_event(
    agent_id: str,
    severity: str,
    category: str,
    fingerprint: str,
    payload: dict[str, Any],
) -> int | None:
    """
    Insert an AgentEvent row and return its id.
    Returns None if a duplicate open event already exists (dedup'd).
    """
    if _event_exists(fingerprint):
        increment_deduped()
        logger.info("[sentinel] dedup'd event fingerprint=%s", fingerprint[:16])
        return None

    try:
        from app.db.session import SessionLocal
        from app.db.models.sentinel import AgentEvent
        db = SessionLocal()
        try:
            ev = AgentEvent(
                agent_id=agent_id,
                severity=severity,
                category=category,
                fingerprint=fingerprint,
                payload=json.dumps(payload),
                state="open",
                detected_at=datetime.now(timezone.utc),
            )
            db.add(ev)
            db.commit()
            db.refresh(ev)
            increment_observed()
            logger.warning("[sentinel] event created id=%d agent=%s category=%s",
                           ev.id, agent_id, category)
            return ev.id
        finally:
            db.close()
    except Exception as exc:
        logger.error("[sentinel] create_agent_event failed: %s", exc)
        return None


# ── Railway watcher ───────────────────────────────────────────────────────────

_RAILWAY_API = "https://backboard.railway.app/graphql/v2"

_DEPLOYMENTS_QUERY = """
query Deployments($projectId: String!, $serviceId: String!) {
  deployments(
    input: { projectId: $projectId, serviceId: $serviceId }
    last: 20
  ) {
    edges {
      node {
        id
        status
        createdAt
        meta {
          commitMessage
          commitHash
        }
      }
    }
  }
}
"""

_BUILD_LOGS_QUERY = """
query BuildLogs($deploymentId: String!) {
  buildLogs(deploymentId: $deploymentId, limit: 200) {
    message
    severity
    timestamp
  }
}
"""


def _railway_fingerprint(deploy_id: str, first_error_line: str) -> str:
    raw = f"railway:{deploy_id}:{first_error_line[:120]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _railway_gql(query: str, variables: dict) -> dict:
    token = os.getenv("RAILWAY_API_TOKEN", "")
    if not token:
        raise ValueError("RAILWAY_API_TOKEN not set")
    resp = httpx.post(
        _RAILWAY_API,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _extract_error_block(logs: list[dict]) -> str:
    lines = [l.get("message", "") for l in logs]
    for i, line in enumerate(lines):
        if "error" in line.lower():
            start = max(0, i - 5)
            end = min(len(lines), i + 45)
            return "\n".join(lines[start:end])
    return "\n".join(lines[:50])


def _check_railway_deploys() -> None:
    """Synchronous Railway poll — called from the async loop via to_thread."""
    project_id = os.getenv("RAILWAY_PROJECT_ID", "")
    service_id = os.getenv("RAILWAY_SERVICE_ID", "")
    if not project_id or not service_id:
        return

    data = _railway_gql(_DEPLOYMENTS_QUERY, {
        "projectId": project_id,
        "serviceId": service_id,
    })
    edges = data.get("data", {}).get("deployments", {}).get("edges", [])

    for edge in edges:
        node = edge["node"]
        if node.get("status") != "FAILED":
            continue

        deploy_id = node["id"]
        try:
            logs_data = _railway_gql(_BUILD_LOGS_QUERY, {"deploymentId": deploy_id})
            logs = logs_data.get("data", {}).get("buildLogs", [])
        except Exception:
            logs = []

        error_block = _extract_error_block(logs)
        first_line = error_block.split("\n")[0] if error_block else deploy_id
        fp = _railway_fingerprint(deploy_id, first_line)

        payload = {
            "deploy_id": deploy_id,
            "error_block": error_block[:3000],
            "commit_message": node.get("meta", {}).get("commitMessage", ""),
        }

        event_id = create_agent_event(
            agent_id="railway-watcher",
            severity="critical",
            category="deploy-failed",
            fingerprint=fp,
            payload=payload,
        )

        if event_id and _escalation_enabled():
            _post_escalation_embed(
                event_id=event_id,
                agent_id="railway-watcher",
                severity="critical",
                category="deploy-failed",
                payload=payload,
                message=f"Deploy `{deploy_id[:12]}` failed\n```\n{first_line[:200]}\n```",
            )


async def railway_watcher_loop() -> None:
    """Poll Railway every 30s for failed deployments."""
    import asyncio

    logger.warning("[railway-watcher] loop starting")
    while True:
        try:
            await asyncio.to_thread(_check_railway_deploys)
        except Exception as exc:
            logger.error("[railway-watcher] %s", exc)
        await asyncio.sleep(30)


def send_test_heartbeat() -> dict:
    """
    Called from POST /api/admin/sentinel/test-heartbeat.
    Returns a result dict with ok/error info.
    """
    token = _token()
    channel = _channel()
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    if not token:
        return {"ok": False, "error": "DISCORD_BOT_TOKEN not set in environment"}
    if not channel:
        return {"ok": False, "error": "DISCORD_CHANNEL_ID_SENTINEL_OPS not set in environment"}

    ok = _post_plain(f"🤖 Sentinel test heartbeat · {now}")
    if ok:
        return {"ok": True, "channel": channel, "posted_at": now}
    return {"ok": False, "error": "Discord post failed — check bot token / channel permissions"}
